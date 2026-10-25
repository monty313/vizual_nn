// Vizual NN — Strategy Evolution Lab front end (vanilla JS, no build step, works offline).
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const api = async (path, body, method) => {
  const res = await fetch(`/api${path}`, {
    method: method || (body ? 'POST' : 'GET'),
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const js = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(js.detail || res.statusText);
  return js;
};
const toast = (msg, err = false) => {
  const t = $('#toast'); t.textContent = msg; t.hidden = false; t.classList.toggle('err', err);
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), err ? 6000 : 3000);
};
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const sideCls = (s) => (s > 0 || s === 'long_only' || s === 'up' ? 'c-long' : s < 0 || s === 'short_only' || s === 'down' ? 'c-short' : 'c-flat');
const actCls = (a) => (a === 'fire_buy' ? 'c-long' : a === 'fire_sell' ? 'c-short' : a === 'wait_loaded' ? 'c-load' : a === 'kill' ? 'c-kill' : 'c-flat');
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const S = {
  st: null, frame: null, step: 0, len: 0, set: 2, playing: false, timer: null, busy: false,
  studentView: 'candidate', llm: null, measured: null, labOn: false, overrides: {}, source: 'synthetic',
  cond: {}, lastAct: null, graphKey: '',
};

// ---------------------------------------------------------------- boot
async function boot() {
  S.st = await api('/state');
  S.cond = { ...S.st.conditions, ...(S.st.market.request.conditions || {}) };
  buildSetSeg(); buildConditions(); buildLabFields(); buildCorrForm();
  renderStrategies(); renderLLMBadge(); renderEvolution();
  S.len = S.st.market.replay_len;
  S.step = Math.min(S.len - 1, Math.floor(S.len * 0.55));
  bind();
  await refresh();
  addMsg('bot', S.st.llm.ready
    ? `Fable 5.1 online (${S.st.llm.provider}: ${S.st.llm.model}). I read the frame you are on. Ask me why, correct me, or describe a new strategy.`
    : 'Offline student online. I start naive and only learn from your lessons. Add an LLM in .env to talk to a language model. You can still add strategies by typing: add strategy NAME: CCI 100 on supports as force, CCI 30 on anchor as velocity');
}

function buildSetSeg() {
  const seg = $('#setSeg'); seg.innerHTML = '';
  Object.entries(S.st.sets).forEach(([id, s]) => {
    const b = document.createElement('button');
    b.textContent = id; b.title = `${s.anchor} | ${s.supports.join(', ')}`; b.dataset.set = id;
    if (+id === S.set) b.classList.add('on');
    b.onclick = async () => { S.set = +id; $$('#setSeg button').forEach((x) => x.classList.toggle('on', x === b)); S.graphKey = ''; await refreshLen(); refresh(); };
    seg.appendChild(b);
  });
}

const SLIDERS = [
  ['trend', 'HTF trend (side × strength)', -1, 1, 0.05],
  ['pullback_depth', 'Pullback depth', 0, 1, 0.05],
  ['pullback_hours', 'Pullback length (h)', 0.5, 12, 0.5],
  ['noise', 'Noise', 0.3, 3, 0.1],
  ['volatility', 'Volatility', 0.3, 3, 0.1],
];
function buildConditions() {
  const sel = $('#story'); sel.innerHTML = '';
  Object.keys(S.st.stories).forEach((k) => { const o = new Option(k.replace(/_/g, ' '), k); sel.add(o); });
  sel.value = S.cond.story; $('#storyHelp').textContent = S.st.stories[S.cond.story];
  sel.onchange = () => { S.cond.story = sel.value; $('#storyHelp').textContent = S.st.stories[sel.value]; rebuildMarket(); };
  const box = $('#condSliders'); box.innerHTML = '';
  SLIDERS.forEach(([k, label, mn, mx, st]) => {
    const d = document.createElement('div'); d.className = 'slider';
    d.innerHTML = `<div class="top"><span>${label}</span><b id="v_${k}">${(+S.cond[k]).toFixed(2)}</b></div><input type="range" min="${mn}" max="${mx}" step="${st}" value="${S.cond[k]}" aria-label="${label}">`;
    const inp = $('input', d);
    inp.oninput = () => { $(`#v_${k}`).textContent = (+inp.value).toFixed(2); S.cond[k] = +inp.value; debounceMarket(); };
    box.appendChild(d);
  });
}
let mTimer; const debounceMarket = () => { clearTimeout(mTimer); mTimer = setTimeout(rebuildMarket, 350); };
async function rebuildMarket() {
  try {
    const r = await api('/market', { source: 'synthetic', conditions: S.cond, set_id: S.set });
    S.len = r.replay_len; S.step = Math.min(S.step, S.len - 1); S.measured = null; S.llm = null;
    await refresh();
  } catch (e) { toast(e.message, true); }
}
async function refreshLen() {
  const st = await api('/state'); S.st = { ...S.st, ...st };
}

const LAB_FIELDS = {
  support_force: ['agree', 'conflict', 'missing'], tide: ['long_only', 'short_only', 'flat'], G: ['none', 'with', 'against', 'inside'],
  regime_gate: ['none', 'tradable', 'chop'], expansion: ['none', 'contracting', 'expanding', 'shock'],
  inertia: ['with', 'against', 'flat'], velocity: ['with', 'against', 'flat'], recent_load: [false, true], heat: ['ok', 'blocked'],
};
function buildLabFields() {
  const box = $('#labFields'); box.innerHTML = '';
  Object.entries(LAB_FIELDS).forEach(([k, vals]) => {
    const l = document.createElement('label'); l.className = 'fld';
    l.innerHTML = `${k.replace(/_/g, ' ')}<select class="inp sm" data-k="${k}"><option value="">(live)</option>${vals.map((v) => `<option value="${v}">${v}</option>`).join('')}</select>`;
    $('select', l).onchange = (e) => {
      const v = e.target.value;
      if (v === '') delete S.overrides[k]; else S.overrides[k] = v === 'true' ? true : v === 'false' ? false : v;
      if (k === 'tide' && v) S.overrides.support_force = v === 'flat' ? 'conflict' : 'agree';
      refresh();
    };
    box.appendChild(l);
  });
  $('#labOn').onchange = (e) => { S.labOn = e.target.checked; box.classList.toggle('on', S.labOn); refresh(); };
}

function buildCorrForm() {
  const f = $('#corrForm'); const v = S.st.vocab;
  const fill = (name, arr) => { f[name].innerHTML = arr.map((x) => `<option value="${x ?? ''}">${x ?? '(none)'}</option>`).join(''); };
  fill('tide', ['long_only', 'short_only', 'flat']); fill('topology', v.topologies); fill('act', v.actions); fill('wait_subtype', [null, 'loaded', 'no_trade', 'heat']);
}

// ---------------------------------------------------------------- frame loop
const finish = () => ({ daily_target: +$('#fTarget').value, daily_risk: +$('#fRisk').value, risk_used: +$('#fUsed').value, pnl_today: +$('#fPnl').value });
async function refresh() {
  if (S.busy) return; S.busy = true;
  try {
    const fr = await api('/frame', { step: S.step, set_id: S.set, finish: finish(), overrides: S.labOn ? S.overrides : null, window: 120 });
    const moved = S.frame && S.frame.t !== fr.t;
    S.frame = fr; S.len = fr.replay_len;
    if (moved) { S.measured = null; }
    render();
  } catch (e) { toast(e.message, true); stop(); }
  S.busy = false;
}
function play() {
  S.playing = true; $('#bPlay').textContent = '❚❚';
  const fps = +$('#speed').value;
  clearInterval(S.timer);
  S.timer = setInterval(async () => {
    if (S.busy) return;
    if (S.step >= S.len - 1) { stop(); return; }
    S.step += 1; await refresh();
  }, 1000 / fps);
}
function stop() { S.playing = false; clearInterval(S.timer); $('#bPlay').textContent = '▶'; }

function bind() {
  $('#bPlay').onclick = () => (S.playing ? stop() : play());
  $('#bStart').onclick = () => { S.step = 0; refresh(); };
  $('#bBack').onclick = () => { S.step = Math.max(0, S.step - 1); refresh(); };
  $('#bFwd').onclick = () => { S.step = Math.min(S.len - 1, S.step + 1); refresh(); };
  $('#speed').onchange = () => S.playing && play();
  $('#scrub').oninput = (e) => { S.step = Math.round((+e.target.value / 1000) * (S.len - 1)); refresh(); };
  $('#regen').onclick = () => { S.cond.seed = Math.floor(Math.random() * 9000) + 1; rebuildMarket(); };
  ['#fTarget', '#fRisk', '#fUsed', '#fPnl'].forEach((id) => ($(id).onchange = refresh));
  document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    if (e.code === 'Space') { e.preventDefault(); S.playing ? stop() : play(); }
    if (e.code === 'ArrowRight') { S.step = Math.min(S.len - 1, S.step + 1); refresh(); }
    if (e.code === 'ArrowLeft') { S.step = Math.max(0, S.step - 1); refresh(); }
  });
  $$('#sourceSeg button').forEach((b) => (b.onclick = async () => {
    $$('#sourceSeg button').forEach((x) => x.classList.toggle('on', x === b));
    S.source = b.dataset.src; $('#loadAlpaca').hidden = S.source !== 'alpaca';
    if (S.source === 'synthetic') rebuildMarket();
    else if (!S.st.alpaca.configured) toast('Alpaca keys not set. Add ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY to .env and restart.', true);
    else loadAlpaca();
  }));
  $('#loadAlpaca').onclick = loadAlpaca;
  $$('#studentSeg button').forEach((b) => (b.onclick = () => {
    $$('#studentSeg button').forEach((x) => x.classList.toggle('on', x === b)); S.studentView = b.dataset.s; render();
    if (S.studentView === 'llm' && !S.llm) askLLM(false);
  }));
  $('#bAsk').onclick = () => askLLM(false);
  $('#bProbe').onclick = () => askLLM(true);
  $('#bConfirm').onclick = () => saveLesson(null, 'Confirmed doctrine reading');
  $('#bCorrect').onclick = openCorrection;
  $('#corrCancel').onclick = () => ($('#corrForm').hidden = true);
  $('#corrForm').onsubmit = (e) => {
    e.preventDefault(); const f = e.target;
    saveLesson({ tide: f.tide.value, topology: f.topology.value, act: f.act.value, wait_subtype: f.wait_subtype.value || null }, f.note.value);
    f.hidden = true;
  };
  $('#chatForm').onsubmit = (e) => { e.preventDefault(); sendChat(); };
  $('#chatIn').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } };
  $('#stratSel').onchange = (e) => selectStrategy(e.target.value);
  $('#bNewJson').onclick = () => openSpec({ name: 'My new strategy', primary_set: 2, sensors: [
    { family: 'CCI', period: 100, slot: 'supports', role: 'force' }, { family: 'CCI', period: 100, slot: 'anchor', role: 'inertia' },
    { family: 'CCI', period: 30, slot: 'anchor', role: 'velocity' }, { family: 'ADX', period: 14, slot: 'anchor', role: 'regime_gate' }] });
  $('#bValidate').onclick = validateSpec;
  $('#bSaveSpec').onclick = () => saveSpec(false);
  $('#bSaveAct').onclick = () => saveSpec(true);
  $('#bCloseSpec').onclick = () => ($('#specBox').hidden = true);
  $('#bTeach').onclick = () => runJob('/evolve/auto_teach', { k: 4 }, 'Auto-teach');
  $('#bCp').onclick = () => runJob('/evolve/checkpoint', { student: 'offline', survival_days: 100 }, 'Checkpoint');
  $('#bCpLlm').onclick = () => {
    if (!S.st.llm.ready) return toast('LLM not configured in .env', true);
    if (confirm('LLM checkpoint sends about 40 model calls (12 samples × 3 packs + retention). Continue?')) runJob('/evolve/checkpoint', { student: 'llm', llm_limit: 12, survival_days: 0 }, 'LLM checkpoint');
  };
  $('#bReset').onclick = async () => { if (!confirm('Erase the candidate lesson memory? The approved student is not touched.')) return; await api('/lessons/reset', {}); await afterLearn(); };
  window.addEventListener('resize', () => { if (S.frame) drawChart(); drawEvo(S.st.checkpoints || []); });
}

async function loadAlpaca() {
  try {
    toast('Fetching Alpaca bars for every official timeframe…');
    const r = await api('/market', { source: 'alpaca', symbol: $('#symbol').value, set_id: S.set });
    S.len = r.replay_len; S.step = S.len - 1; await refresh(); toast(`Loaded ${r.symbol} from Alpaca (read-only data).`);
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- render
function currentStudent() {
  if (S.studentView === 'approved') return S.frame.approved;
  if (S.studentView === 'llm') return S.llm && S.llm.t === S.frame.t ? S.llm : null;
  return S.frame.student;
}
function render() {
  const fr = S.frame;
  $('#scrub').value = Math.round((S.step / Math.max(1, S.len - 1)) * 1000); $('#scrub').max = 1000;
  $('#stepLbl').textContent = `${S.step + 1}/${S.len}`;
  $('#chartTitle').textContent = `${fr.chart.tf} anchor · Set ${S.set} · ${fr.strategy.name} v${fr.strategy.version}`;
  drawChart(); drawMind(); renderChain(); renderSets(); renderThinking();
}

function drawChart() {
  const fr = S.frame; if (!fr) return; const ch = fr.chart;
  const cv = $('#chart'); const oc = $('#osc');
  for (const c of [cv, oc]) { const w = c.clientWidth; c.width = w * devicePixelRatio; c.height = (+c.getAttribute('height')) * devicePixelRatio; }
  const g = cv.getContext('2d'); g.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  const W = cv.clientWidth, H = +cv.getAttribute('height'); const n = ch.c.length; const pad = { l: 8, r: 56, t: 10, b: 14 };
  g.clearRect(0, 0, W, H);
  let lo = Math.min(...ch.l), hi = Math.max(...ch.h);
  ch.overlays.forEach((o) => (o.upper || o.v || []).concat(o.lower || []).forEach((v) => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
  const padY = (hi - lo) * 0.06; lo -= padY; hi += padY;
  const x = (i) => pad.l + (i + 0.5) * ((W - pad.l - pad.r) / n); const y = (v) => pad.t + (hi - v) / (hi - lo) * (H - pad.t - pad.b);
  const bw = Math.max(1, ((W - pad.l - pad.r) / n) * 0.62);
  // grid
  g.strokeStyle = css('--line'); g.lineWidth = 1; g.fillStyle = css('--faint'); g.font = '10px ' + css('--mono');
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; g.beginPath(); g.moveTo(pad.l, y(v)); g.lineTo(W - pad.r, y(v)); g.stroke(); g.fillText(v.toFixed(2), W - pad.r + 6, y(v) + 3); }
  // overlays
  ch.overlays.forEach((o, oi) => {
    const col = oi % 2 ? 'rgba(180,140,255,' : 'rgba(90,169,255,';
    if (o.kind === 'band') {
      g.fillStyle = col + '0.08)'; g.beginPath(); let started = false;
      o.upper.forEach((v, i) => { if (v == null) return; started ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v)); started = true; });
      for (let i = o.lower.length - 1; i >= 0; i--) if (o.lower[i] != null) g.lineTo(x(i), y(o.lower[i]));
      g.closePath(); g.fill();
      for (const arr of [o.upper, o.lower]) { g.strokeStyle = col + '0.55)'; g.lineWidth = 1; g.beginPath(); let s = false; arr.forEach((v, i) => { if (v == null) return; s ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v)); s = true; }); g.stroke(); }
    } else {
      g.strokeStyle = col + '0.8)'; g.lineWidth = 1.2; g.beginPath(); let s = false; o.v.forEach((v, i) => { if (v == null) return; s ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v)); s = true; }); g.stroke();
    }
  });
  // candles
  for (let i = 0; i < n; i++) {
    const up = ch.c[i] >= ch.o[i]; g.strokeStyle = g.fillStyle = up ? css('--long') : css('--short');
    g.beginPath(); g.moveTo(x(i), y(ch.h[i])); g.lineTo(x(i), y(ch.l[i])); g.stroke();
    const yo = y(ch.o[i]), yc = y(ch.c[i]); g.fillRect(x(i) - bw / 2, Math.min(yo, yc), bw, Math.max(1, Math.abs(yc - yo)));
  }
  // doctrine markers
  ch.markers.forEach((m) => {
    const col = m.act === 'fire_buy' ? css('--long') : m.act === 'fire_sell' ? css('--short') : m.act === 'kill' ? css('--kill') : css('--load');
    const yy = m.act === 'fire_sell' ? y(ch.h[m.k]) - 9 : y(ch.l[m.k]) + 9;
    g.fillStyle = col; g.beginPath();
    if (m.act === 'wait_loaded') g.arc(x(m.k), y(ch.h[m.k]) - 6, 2.2, 0, 7);
    else if (m.act === 'kill') { g.rect(x(m.k) - 3, y(ch.h[m.k]) - 12, 6, 6); }
    else { const d = m.act === 'fire_buy' ? -1 : 1; g.moveTo(x(m.k), yy + 5 * d); g.lineTo(x(m.k) - 5, yy - 4 * d); g.lineTo(x(m.k) + 5, yy - 4 * d); }
    g.fill();
  });
  // cursor
  g.strokeStyle = 'rgba(255,255,255,.25)'; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(x(n - 1), pad.t); g.lineTo(x(n - 1), H - pad.b); g.stroke(); g.setLineDash([]);
  // oscillators
  const o = oc.getContext('2d'); o.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  const OH = +oc.getAttribute('height'); o.clearRect(0, 0, W, OH);
  const oy = (v, a, b) => 6 + (b - v) / (b - a) * (OH - 12);
  const cols = { velocity: css('--student'), inertia: css('--accent'), force: css('--load') };
  let lx = pad.l + 4;
  ch.oscillators.forEach((s) => {
    const vals = s.v.filter((v) => v != null); if (!vals.length) return;
    let a = Math.min(...vals), b = Math.max(...vals);
    const mid = { RSI: 50, Stochastic: 50, WPR: -50, Momentum: 100, MFI: 50 }[s.family] ?? 0;
    const span = Math.max(Math.abs(a - mid), Math.abs(b - mid)) || 1; a = mid - span; b = mid + span;
    o.strokeStyle = 'rgba(255,255,255,.12)'; o.beginPath(); o.moveTo(pad.l, oy(mid, a, b)); o.lineTo(W - pad.r, oy(mid, a, b)); o.stroke();
    o.strokeStyle = cols[s.role] || css('--muted'); o.lineWidth = 1.4; o.beginPath(); let st = false;
    s.v.forEach((v, i) => { if (v == null) return; st ? o.lineTo(x(i), oy(v, a, b)) : o.moveTo(x(i), oy(v, a, b)); st = true; }); o.stroke();
    o.fillStyle = cols[s.role] || css('--muted'); o.font = '10px ' + css('--mono'); o.fillText(`${s.id} (${s.role})`, lx, 12); lx += o.measureText(`${s.id} (${s.role})`).width + 14;
  });
}

// ---------- mind map
const ROLE_ORDER = ['force', 'inertia', 'velocity', 'regime_gate', 'expansion', 'equilibrium', 'volume_confirm'];
const FEATS = [
  ['support_force', 'HTF force', ['force']], ['G', 'Macro G tunnel', ['force']], ['regime_gate', 'Regime gate', ['regime_gate']],
  ['expansion', 'Expansion clock', ['expansion']], ['inertia', 'Inertia vs tide', ['inertia']], ['velocity', 'Velocity vs tide', ['velocity']],
  ['recent_load', 'Load memory', ['velocity', 'inertia']], ['velocity_hold', 'Velocity hold', ['velocity']], ['heat', 'Heat / goal', []],
];
const FEAT_STEP = { support_force: 'tide', G: 'regime', regime_gate: 'regime', expansion: 'regime', inertia: 'breath_launch', velocity: 'breath_launch', recent_load: 'breath_launch', velocity_hold: 'breath_launch', heat: 'finish' };
const STEPS = ['tide', 'regime', 'breath_launch', 'act', 'finish'];
const STUDENT_FEAT = { support_force: 'support_force', G: 'G', regime_gate: 'regime_gate', expansion: 'expansion', inertia: 'inertia', velocity: 'velocity', recent_load: 'recent_load', velocity_hold: 'velocity_hold', heat: 'heat' };

function drawMind() {
  const fr = S.frame; const svg = $('#mind'); const d = fr.doctrine;
  const readings = d.readings;
  const roles = ROLE_ORDER.filter((r) => readings.some((x) => x.role === r));
  const feats = FEATS.filter(([k, , src]) => k === 'heat' || (k === 'G' ? readings.some((x) => x.family === 'Envelopes' && x.slot === 'support') : src.some((r) => roles.includes(r))));
  const key = `${fr.strategy.id}@${fr.strategy.version}|${S.set}|${readings.map((r) => r.iid).join(',')}`;
  const W = 1000, H = 420; const X = [20, 250, 450, 690, 860];
  const ys = (n, i, top = 40, bot = H - 16) => top + (i + 0.5) * ((bot - top) / n);
  if (S.graphKey !== key) {
    S.graphKey = key;
    let h = `<text class="col-h" x="${X[0]}" y="18">Sensors (${fr.doctrine.anchor} · ${fr.doctrine.supports.join(', ')})</text><text class="col-h" x="${X[1]}" y="18">Roles</text><text class="col-h" x="${X[2]}" y="18">Relations</text><text class="col-h" x="${X[3]}" y="18">Decision chain</text><text class="col-h" x="${X[4]}" y="18">Output</text>`;
    // edges first
    readings.forEach((r, i) => { const ri = roles.indexOf(r.role); h += `<path class="edge" id="e_s_${i}" d="M${X[0] + 180},${ys(readings.length, i)} C${X[0] + 215},${ys(readings.length, i)} ${X[1] - 35},${ys(roles.length, ri)} ${X[1]},${ys(roles.length, ri)}"/>`; });
    feats.forEach(([k, , src], fi) => {
      src.filter((r) => roles.includes(r)).forEach((r) => { const ri = roles.indexOf(r); h += `<path class="edge rf" data-f="${k}" d="M${X[1] + 130},${ys(roles.length, ri)} C${X[1] + 165},${ys(roles.length, ri)} ${X[2] - 35},${ys(feats.length, fi)} ${X[2]},${ys(feats.length, fi)}" stroke="${css('--line2')}" stroke-width="1.2"/>`; });
      const si = STEPS.indexOf(FEAT_STEP[k]);
      h += `<path class="edge fs" id="e_f_${k}" d="M${X[2] + 170},${ys(feats.length, fi)} C${X[2] + 205},${ys(feats.length, fi)} ${X[3] - 35},${ys(5, si)} ${X[3]},${ys(5, si)}"/>`;
    });
    for (let i = 0; i < 4; i++) h += `<path class="edge" d="M${X[3] + 70},${ys(5, i) + 16} L${X[3] + 70},${ys(5, i + 1) - 16}" stroke="${css('--line2')}" stroke-width="1.5"/>`;
    h += `<path class="edge" id="e_out" d="M${X[3] + 140},${ys(5, 4)} C${X[3] + 160},${ys(5, 4)} ${X[4] - 20},${H / 2} ${X[4]},${H / 2}"/>`;
    // nodes
    readings.forEach((r, i) => {
      const yy = ys(readings.length, i);
      h += `<ellipse class="halo" id="h_s_${i}" cx="${X[0] + 90}" cy="${yy}" rx="0" ry="0"/><rect class="nbox" id="n_s_${i}" x="${X[0]}" y="${yy - 15}" width="180" height="30" rx="6"/>` +
        `<circle id="d_s_${i}" cx="${X[0] + 12}" cy="${yy}" r="4"/><text x="${X[0] + 22}" y="${yy - 2}">${esc(r.sensor_id.split('_')[0])}<tspan class="sub"> ${r.tf}</tspan></text><text class="sub" id="v_s_${i}" x="${X[0] + 22}" y="${yy + 10}"></text>`;
    });
    roles.forEach((r, i) => { const yy = ys(roles.length, i); h += `<rect class="nbox" x="${X[1]}" y="${yy - 14}" width="130" height="28" rx="14"/><text x="${X[1] + 14}" y="${yy + 4}">${r.replace('_', ' ')}</text>`; });
    feats.forEach(([k, label], i) => { const yy = ys(feats.length, i); h += `<ellipse class="halo" id="h_f_${k}" cx="${X[2] + 85}" cy="${yy}" rx="0" ry="0"/><rect class="nbox" id="n_f_${k}" x="${X[2]}" y="${yy - 15}" width="170" height="30" rx="6"/><text x="${X[2] + 10}" y="${yy - 2}">${label}</text><text class="sub" id="v_f_${k}" x="${X[2] + 10}" y="${yy + 10}"></text>`; });
    STEPS.forEach((s, i) => { const yy = ys(5, i); h += `<rect class="nbox" id="n_c_${s}" x="${X[3]}" y="${yy - 16}" width="140" height="32" rx="6"/><text x="${X[3] + 10}" y="${yy - 2}">${i + 1} ${s.replace('_', ' / ').toUpperCase()}</text><text class="sub" id="v_c_${s}" x="${X[3] + 10}" y="${yy + 11}"></text>`; });
    h += `<rect class="nbox" id="n_out" x="${X[4]}" y="${H / 2 - 44}" width="130" height="88" rx="10"/><text class="col-h" x="${X[4] + 12}" y="${H / 2 - 24}">doctrine</text><text id="v_out" x="${X[4] + 12}" y="${H / 2 - 4}" style="font-size:15px;font-weight:600"></text><text class="col-h" x="${X[4] + 12}" y="${H / 2 + 16}">student</text><text id="v_out2" x="${X[4] + 12}" y="${H / 2 + 34}" style="font-size:13px"></text>`;
    svg.innerHTML = h;
  }
  // dynamic update
  const st = currentStudent();
  const att = st ? (S.measured ? Object.fromEntries(Object.entries(S.measured).map(([k, v]) => [k, v.score])) : st.attention || {}) : {};
  readings.forEach((r, i) => {
    const inf = d.influence[r.sensor_id]?.score || 0; const col = r.side > 0 ? css('--long') : r.side < 0 ? css('--short') : css('--faint');
    const e = $(`#e_s_${i}`, svg); e.setAttribute('stroke', inf ? col : css('--line2')); e.setAttribute('stroke-width', 1 + inf * 5); e.setAttribute('opacity', inf ? 0.95 : 0.5);
    $(`#d_s_${i}`, svg).setAttribute('fill', col);
    const vtxt = `${r.value == null ? '—' : (+r.value).toFixed(1)} ${r.side > 0 ? '▲' : r.side < 0 ? '▼' : '·'} ${r.state || ''}`;
    const vt = $(`#v_s_${i}`, svg); if (vt.textContent !== vtxt) { vt.textContent = vtxt; const nb = $(`#n_s_${i}`, svg); nb.classList.remove('pulse'); void nb.getBBox(); nb.classList.add('pulse'); }
    const a = att[r.sensor_id] || 0; const hh = $(`#h_s_${i}`, svg); hh.setAttribute('rx', a ? 96 + a * 6 : 0); hh.setAttribute('ry', a ? 19 + a * 3 : 0); hh.setAttribute('stroke-width', 1 + a * 3); hh.setAttribute('opacity', a ? 0.3 + a * 0.7 : 0);
  });
  const fx = d.features; const fatt = st?.feature_attention || {};
  feats.forEach(([k]) => {
    let v = fx[k]; if (k === 'heat') v = `${fx.heat} · goal ${fx.goal}`; if (k === 'support_force') v = `${fx.support_force} → ${fx.tide}`;
    $(`#v_f_${k}`, svg).textContent = String(v);
    const good = { with: 1, agree: 1, tradable: 1, true: 1, ok: 1 }[String(fx[k])]; const bad = { against: 1, conflict: 1, chop: 1, shock: 1, blocked: 1, inside: 1 }[String(fx[k])];
    $(`#n_f_${k}`, svg).style.stroke = good ? css('--long') : bad ? css('--short') : '';
    const e = $(`#e_f_${k}`, svg); e.setAttribute('stroke', good ? css('--long') : bad ? css('--short') : css('--line2')); e.setAttribute('stroke-width', good || bad ? 2 : 1);
    const a = fatt[STUDENT_FEAT[k]] || 0; const hh = $(`#h_f_${k}`, svg); hh.setAttribute('rx', a ? 91 + a * 6 : 0); hh.setAttribute('ry', a ? 19 + a * 3 : 0); hh.setAttribute('stroke-width', 1 + a * 3); hh.setAttribute('opacity', a ? 0.35 + a : 0);
  });
  d.chain.forEach((c) => {
    $(`#v_c_${c.step}`, svg).textContent = c.result;
    const n = $(`#n_c_${c.step}`, svg); const loaded = c.result === 'wait_loaded' || c.result === 'slingshot_load';
    n.style.stroke = loaded ? css('--load') : c.passed ? css('--long') : css('--short');
    const sv = st ? { tide: st.tide, regime: st.regime, breath_launch: st.topology, act: st.act, finish: st.act }[c.step] : null;
    n.style.strokeDasharray = st && sv !== c.result ? '4 3' : '';
  });
  const out = $('#v_out', svg); out.textContent = d.act; out.setAttribute('class', actCls(d.act)); out.style.fill = css(`--${{ 'c-long': 'long', 'c-short': 'short', 'c-load': 'load', 'c-kill': 'kill', 'c-flat': 'muted' }[actCls(d.act)]}`);
  const o2 = $('#v_out2', svg); o2.textContent = st ? st.act : '—'; o2.style.fill = css('--student');
  $('#n_out', svg).style.stroke = st && st.act === d.act ? css('--long') : st ? css('--student') : '';
  if (S.lastAct && S.lastAct !== d.act) { const n = $('#n_out', svg); n.classList.remove('pulse'); void n.getBBox(); n.classList.add('pulse'); }
  S.lastAct = d.act;
}

// ---------- decision chain table
function renderChain() {
  const d = S.frame.doctrine; const st = currentStudent();
  const head = { candidate: 'Candidate student', approved: 'Approved (frozen)', llm: 'LLM student' }[S.studentView];
  $('#studentHead').textContent = head + (st && st.mode ? ` · ${st.mode}` : '');
  const sv = (step) => (st ? { tide: st.tide, regime: st.regime, breath_launch: st.topology, act: st.act, finish: st.act + (st.wait_subtype ? ` (${st.wait_subtype})` : '') }[step] : null);
  $('#chain tbody').innerHTML = d.chain.map((c) => {
    const s = sv(c.step); const res = c.step === 'finish' ? c.result + (d.wait_subtype ? ` (${d.wait_subtype})` : '') : c.result;
    const mis = s != null && s !== res;
    const cls = c.result === 'wait_loaded' || c.result === 'slingshot_load' ? 'loaded' : c.passed ? 'pass' : 'block';
    return `<tr class="${mis ? 'mismatch' : ''}"><td>${c.step.replace('_', ' / ')}</td><td><div class="val ${cls}">${esc(res)}</div><div class="why">${esc(c.why)} · <span class="mono">${esc(c.form)}</span></div></td>` +
      `<td><div class="val c-stud">${s == null ? '<span class="muted">—</span>' : esc(s)}</div></td></tr>`;
  }).join('');
  let txt;
  if (!st) txt = S.studentView === 'approved' ? 'No approved student yet. Promote a checkpoint that passes every gate.' : S.studentView === 'llm' ? 'Press Ask LLM to have the LLM read this exact frame.' : '';
  else {
    const keys = ['tide', 'regime', 'topology', 'act', 'wait_subtype']; const ok = keys.filter((k) => (st[k] ?? null) === (d[k] ?? null));
    txt = `Agreement <b>${ok.length}/${keys.length}</b> · relations: <span class="mono">${d.relations.join(', ') || '—'}</span> · principles: <span class="mono">${d.principle_ids.join(', ')}</span>`;
    if (st.attention_kind) txt += ` · attention: ${st.attention_kind}${S.measured ? ' + measured by masking' : ''}`;
  }
  $('#agree').innerHTML = txt;
}

function renderThinking() {
  const st = currentStudent(); const ol = $('#thinking');
  if (!st) { ol.innerHTML = '<li class="muted">No reading for this frame yet.</li>'; return; }
  const items = (st.thinking || []).map((t) => (typeof t === 'string' ? { step: '', thought: t } : t));
  let html = items.map((t) => `<li><span class="st">${esc(t.step)}</span><span class="${/\[naive\]/.test(t.thought) ? 'naive' : ''}">${esc(t.thought)}</span></li>`).join('');
  if (st.meta) html += `<li class="muted mono small">${esc(st.meta.provider)}:${esc(st.meta.model)} · ${st.meta.latency_s}s · lessons retrieved ${(st.retrieved || []).length}</li>`;
  if (S.measured) html += `<li class="muted small">Measured attention (mask each sensor, re-ask): ${Object.entries(S.measured).map(([k, v]) => `${k}=${v.score}${v.changed.length ? ' [' + v.changed.join('; ') + ']' : ''}`).join(' · ')}</li>`;
  ol.innerHTML = html;
}

function renderSets() {
  const fr = S.frame;
  $('#sets tbody').innerHTML = Object.entries(fr.sets).map(([id, s]) => `<tr class="${+id === S.set ? 'primary' : ''}"><td>${id}</td><td>${s.anchor} | ${s.supports.join(',')}</td>` +
    `<td class="${sideCls(s.tide)}">${s.tide.replace('_only', '')}</td><td>${s.topology.replace('slingshot_', 'sl_')}</td><td class="${actCls(s.act)}">${s.act}</td><td class="c-stud">${s.student_act}</td></tr>`).join('');
  const c = fr.doctrine.consensus; const b = $('#consensus');
  b.textContent = `${c} · conviction ${fr.doctrine.conviction} · ${fr.doctrine.size_feel}`; b.className = 'badge ' + (c.startsWith('agree') ? 'ok' : c === 'conflict' ? 'bad' : 'warn');
}

// ---------------------------------------------------------------- teaching
function openCorrection() {
  const f = $('#corrForm'); const d = S.frame.doctrine;
  f.tide.value = d.tide; f.topology.value = d.topology; f.act.value = d.act; f.wait_subtype.value = d.wait_subtype || '';
  f.note.value = ''; f.hidden = false; f.note.focus();
}
async function saveLesson(labels, note) {
  try {
    const st = currentStudent();
    const r = await api('/lesson', { t: S.frame.t, set_id: S.set, finish: finish(), overrides: S.labOn ? S.overrides : null, labels, note,
      student: st ? { tide: st.tide, regime: st.regime, topology: st.topology, act: st.act, wait_subtype: st.wait_subtype } : null });
    const L = r.lesson;
    toast(`Lesson ${L.lesson_id}: ${L.topology} → ${L.act}${L.conflicts_with_doctrine?.length ? ' (differs from doctrine on ' + L.conflicts_with_doctrine.join(', ') + ')' : ''}`);
    addMsg('bot', `Lesson saved. I now hold ${r.lessons} principle applications.\n${JSON.stringify({ lesson_type: L.lesson_type, not: L.not, set_id: L.set_id, relations: L.relations, topology: L.topology, act: L.act, principle_ids: L.principle_ids, goal_link: L.goal_link, forward_note: L.forward_note }, null, 1)}`);
    await afterLearn();
  } catch (e) { toast(e.message, true); }
}
async function afterLearn() { S.st = await api('/state'); renderLLMBadge(); renderEvolution(); S.llm = null; await refresh(); }

async function askLLM(probe) {
  if (!S.st.llm.ready && S.studentView === 'llm') { toast('LLM not configured. Set LLM_PROVIDER, LLM_API_KEY and LLM_MODEL in .env, or run Ollama locally.', true); }
  try {
    $('#bAsk').disabled = $('#bProbe').disabled = true; $('#bAsk').textContent = probe ? 'Probing…' : 'Thinking…';
    const r = await api('/student/ask', { t: S.frame.t, set_id: S.set, finish: finish(), overrides: S.labOn ? S.overrides : null, probe });
    if (r.student === 'llm') { S.llm = r; S.measured = r.measured_attention || null; S.studentView = 'llm'; $$('#studentSeg button').forEach((x) => x.classList.toggle('on', x.dataset.s === 'llm')); }
    else { toast(r.note || 'Offline student answered.'); S.measured = null; }
    render();
  } catch (e) { toast(e.message, true); }
  $('#bAsk').disabled = $('#bProbe').disabled = false; $('#bAsk').textContent = 'Ask LLM';
}

// ---------------------------------------------------------------- chat
function addMsg(who, text, extra) {
  const d = document.createElement('div'); d.className = `msg ${who}`; d.textContent = text;
  if (extra) d.appendChild(extra);
  $('#chatLog').appendChild(d); $('#chatLog').scrollTop = 1e9; return d;
}
async function sendChat() {
  const inp = $('#chatIn'); const m = inp.value.trim(); if (!m) return; inp.value = '';
  addMsg('me', m); const wait = addMsg('bot', '…');
  try {
    const r = await api('/chat', { message: m, t: S.frame?.t, set_id: S.set, finish: finish() });
    wait.remove();
    const extra = document.createElement('div');
    if (r.thinking?.length) { const det = document.createElement('details'); det.innerHTML = `<summary>How I thought about it (${r.thinking.length} steps)</summary><ol>${r.thinking.map((t) => `<li>${esc(typeof t === 'string' ? t : t.thought)}</li>`).join('')}</ol>`; extra.appendChild(det); }
    if (r.strategy_spec) {
      const v = r.strategy_spec.validation; const box = document.createElement('div'); box.className = 'act';
      box.innerHTML = `<span class="badge ${v.ok ? 'ok' : 'bad'}">${v.ok ? 'passes doctrine validator' : 'fails validator'}</span>`;
      const b1 = document.createElement('button'); b1.className = 'btn sm'; b1.textContent = 'Review JSON'; b1.onclick = () => openSpec(r.strategy_spec);
      const b2 = document.createElement('button'); b2.className = 'btn sm primary'; b2.textContent = 'Save & activate'; b2.disabled = !v.ok;
      b2.onclick = async () => { const s = await api('/strategies', { spec: { ...r.strategy_spec, status: 'draft' } }); await api(`/strategies/${s.id}/activate`, {}); await reloadStrategies(s.id); toast(`Activated ${s.name} v${s.version}`); };
      box.append(b1, b2); extra.appendChild(box);
      if (v.errors.length || v.warnings.length) { const p = document.createElement('div'); p.className = 'val'; p.innerHTML = v.errors.map((e) => `<div class="e">✕ ${esc(e)}</div>`).join('') + v.warnings.map((e) => `<div class="w">! ${esc(e)}</div>`).join(''); extra.appendChild(p); }
    }
    if (r.correction) {
      const c = r.correction; const box = document.createElement('div'); box.className = 'act';
      const b = document.createElement('button'); b.className = 'btn sm primary'; b.textContent = `Save lesson: ${c.topology || c.act || c.wait_subtype}`;
      b.onclick = () => { const d = S.frame.doctrine; saveLesson({ tide: c.tide || d.tide, topology: c.topology || d.topology, act: c.act || (c.topology ? null : d.act), wait_subtype: c.wait_subtype ?? null }, c.note || m); };
      box.appendChild(b); extra.appendChild(box);
    }
    const meta = document.createElement('div'); meta.className = 'meta'; meta.textContent = `${r.student}${r.meta ? ` · ${r.meta.model} · ${r.meta.latency_s}s` : ''} · intent ${r.intent}`; extra.appendChild(meta);
    addMsg('bot', r.reply || '(no reply)', extra);
  } catch (e) { wait.remove(); addMsg('bot', `Error: ${e.message}`); }
}

// ---------------------------------------------------------------- strategy library
function renderStrategies() {
  const sel = $('#stratSel'); sel.innerHTML = '';
  S.st.strategies.forEach((s) => sel.add(new Option(`${s.name} v${s.version}${s.status === 'active' ? ' ●' : ''}`, s.id)));
  sel.value = S.st.strategy.id;
  $('#stratList').innerHTML = S.st.strategies.map((s) => `<li class="${s.id === S.st.strategy.id ? 'sel' : ''}" data-id="${s.id}">
      <div class="row between"><span class="nm">${esc(s.name)}</span><span class="badge ${s.status === 'active' ? 'ok' : s.status === 'archived' ? '' : 'warn'}">${s.status}</span></div>
      <div class="meta">${s.id} · v${s.version} · ${s.versions.length} versions${s.parent ? ' · fork of ' + s.parent : ''} · ${s.valid ? 'valid' : 'INVALID'}</div>
      <div class="acts"><button class="btn sm" data-a="select">Load in lab</button><button class="btn sm" data-a="edit">Edit</button><button class="btn sm" data-a="activate">Activate</button><button class="btn sm ghost" data-a="fork">Fork</button><button class="btn sm ghost" data-a="archive">Archive</button></div></li>`).join('');
  $$('#stratList li').forEach((li) => $$('button', li).forEach((b) => (b.onclick = () => stratAction(li.dataset.id, b.dataset.a))));
}
async function stratAction(id, a) {
  try {
    if (a === 'select') return selectStrategy(id);
    if (a === 'edit') return openSpec(await api(`/strategies/${id}`));
    if (a === 'fork') { const n = prompt('Name of the fork?', `${id} variant`); if (!n) return; const r = await api(`/strategies/${id}/fork?name=${encodeURIComponent(n)}`, {}); await reloadStrategies(r.strategy.id); return; }
    await api(`/strategies/${id}/${a}`, {}); await reloadStrategies(a === 'activate' ? id : S.st.strategy.id);
  } catch (e) { toast(e.message, true); }
}
async function selectStrategy(id) { await api(`/strategies/${id}/select`, {}); await reloadStrategies(id); }
async function reloadStrategies(id) {
  if (id && id !== S.st.strategy.id) await api(`/strategies/${id}/select`, {});
  S.st = await api('/state'); S.graphKey = ''; renderStrategies(); renderEvolution(); await refresh();
}
function openSpec(spec) {
  const clean = { ...spec }; delete clean.validation; delete clean.saved_at;
  $('#specText').value = JSON.stringify(clean, null, 2); $('#specBox').hidden = false; $('#specVal').innerHTML = '';
  $('#specBox').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function readSpec() { try { return JSON.parse($('#specText').value); } catch (e) { toast('JSON error: ' + e.message, true); return null; } }
function showVal(v) { $('#specVal').innerHTML = (v.ok ? '<div class="o">✓ passes doctrine validator</div>' : '') + v.errors.map((e) => `<div class="e">✕ ${esc(e)}</div>`).join('') + v.warnings.map((e) => `<div class="w">! ${esc(e)}</div>`).join(''); }
async function validateSpec() { const s = readSpec(); if (!s) return; const r = await api('/strategies/validate', { spec: s }); $('#specText').value = JSON.stringify({ ...r.spec, validation: undefined }, null, 2); showVal(r.validation); }
async function saveSpec(activate) {
  const s = readSpec(); if (!s) return;
  try { const r = await api('/strategies', { spec: s }); showVal(r.validation); if (activate) await api(`/strategies/${r.id}/activate`, {}); await reloadStrategies(r.id); toast(`Saved ${r.name} v${r.version}`); }
  catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- evolution
function renderLLMBadge() {
  const b = $('#llmBadge'); const l = S.st.llm;
  b.textContent = l.ready ? `LLM · ${l.model}` : 'LLM off · offline student'; b.className = 'badge ' + (l.ready ? 'student' : '');
  $('#memBadge').textContent = `${S.st.memory.candidate_lessons} lessons${S.st.memory.approved_lessons != null ? ' · approved ' + S.st.memory.approved_lessons : ''}`;
  $('#chatMode').textContent = l.ready ? `${l.provider} · ${l.model}` : 'offline parser + lesson-memory student';
  $('#bCpLlm').disabled = !l.ready;
}
function renderEvolution() {
  const cps = S.st.checkpoints || []; const last = cps[cps.length - 1];
  const p = S.st.memory.principles; $('#principles').innerHTML = Object.keys(p).length ? Object.entries(p).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<span class="chip">${k} ×${v}</span>`).join('') : '<span class="muted small">None yet. Teach it.</span>';
  $('#gates').innerHTML = last ? `<div class="muted small">${last.id} · ${last.student} · ${last.lessons} lessons · ${last.strategy}${last.approved ? ' · APPROVED' : ''}</div>` + last.gates.map((g) => `<div class="gate ${g.ok ? 'ok' : 'no'}"><span>${esc(g.label)}</span><span class="v">${g.value == null ? 'not run' : g.value} ${g.ok ? '✓' : '✕'}</span></div>`).join('') +
    (last.survival ? `<div class="muted small">Survival harness: ${last.survival.days} synthetic days · breaches ${last.survival.breaches} · raw violations ${last.survival.raw_violations} · total ${last.survival.total_R}R · worst day ${last.survival.worst_day_R}R. ${esc(last.survival.note)}</div>` : '') +
    `<div class="row gap" style="margin-top:6px"><button class="btn sm ${last.promotable ? 'primary' : ''}" id="bPromote" ${last.promotable ? '' : 'disabled'}>Promote ${last.id} to approved</button></div>`
    : '<div class="muted small">No checkpoint yet. Press Checkpoint to measure the student before teaching.</div>';
  const bp = $('#bPromote'); if (bp) bp.onclick = async () => { try { await api(`/evolve/promote/${last.id}`, {}); toast(`${last.id} promoted. Approved student frozen at ${last.lessons} lessons.`); await afterLearn(); } catch (e) { toast(e.message, true); } };
  api('/lessons').then((r) => {
    $('#lessonCount').textContent = `(${r.candidate.length})`;
    $('#lessonList').innerHTML = r.candidate.map((L) => `<li><span>${L.lesson_id} · ${L.source.replace('_', ' ')} · ${L.topology} → ${L.act_rel}${L.wait_subtype ? ' (' + L.wait_subtype + ')' : ''}${L.conflicts_with_doctrine?.length ? ' <span class="conf">≠ doctrine</span>' : ''}</span><button class="x" data-id="${L.lesson_id}" title="Forget lesson">✕</button></li>`).join('') || '<li class="muted">No lessons. The student is naive.</li>';
    $$('#lessonList .x').forEach((b) => (b.onclick = async () => { await api(`/lessons/${b.dataset.id}`, null, 'DELETE'); await afterLearn(); }));
  });
  drawEvo(cps);
}
function drawEvo(cps) {
  const cv = $('#evoChart'); const W = cv.clientWidth || 400, H = +cv.getAttribute('height');
  cv.width = W * devicePixelRatio; cv.height = H * devicePixelRatio; const g = cv.getContext('2d'); g.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  g.clearRect(0, 0, W, H); const pad = { l: 28, r: 8, t: 30, b: 18 };
  g.strokeStyle = css('--line'); g.fillStyle = css('--faint'); g.font = '10px ' + css('--mono');
  [0, 0.5, 1].forEach((v) => { const y = pad.t + (1 - v) * (H - pad.t - pad.b); g.beginPath(); g.moveTo(pad.l, y); g.lineTo(W - pad.r, y); g.stroke(); g.fillText(`${v * 100}%`, 0, y + 3); });
  if (!cps.length) { g.fillText('checkpoints will plot here', pad.l + 8, H / 2); return; }
  const x = (i) => pad.l + (cps.length === 1 ? (W - pad.l - pad.r) / 2 : i * (W - pad.l - pad.r) / (cps.length - 1));
  const y = (v) => pad.t + (1 - v) * (H - pad.t - pad.b);
  const series = [['held-out topology', (c) => c.heldout?.topology, css('--accent')], ['transfer topology', (c) => c.transfer?.topology, css('--student')],
    ['wait subtype', (c) => c.heldout?.wait_subtype, css('--load')], ['retention', (c) => c.retention, css('--long')]];
  const maxV = Math.max(1, ...cps.map((c) => c.heldout?.violations || 0));
  cps.forEach((c, i) => { const v = (c.heldout?.violations || 0) / maxV; g.fillStyle = 'rgba(240,96,90,.25)'; g.fillRect(x(i) - 5, y(v * 0.5), 10, y(0) - y(v * 0.5)); });
  let lx = pad.l, ly = 10;
  series.forEach(([name, fn, col]) => {
    g.strokeStyle = g.fillStyle = col; g.lineWidth = 1.8; g.beginPath(); let s = false;
    cps.forEach((c, i) => { const v = fn(c); if (v == null) return; s ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v)); s = true; }); g.stroke();
    cps.forEach((c, i) => { const v = fn(c); if (v == null) return; g.beginPath(); g.arc(x(i), y(v), 2.5, 0, 7); g.fill(); });
    const wv = g.measureText(name).width; if (lx + wv > W - pad.r) { lx = pad.l; ly += 11; }
    g.fillText(name, lx, ly); lx += wv + 12;
  });
  g.fillStyle = 'rgba(240,96,90,.8)'; if (lx + 60 > W - pad.r) { lx = pad.l; ly += 11; } g.fillText('violations', lx, ly);
}

async function runJob(path, body, label) {
  try {
    const { job } = await api(path, body); $('#jobLbl').textContent = `${label} running…`;
    $$('.evo-card button').forEach((b) => (b.disabled = true));
    for (;;) {
      await new Promise((r) => setTimeout(r, 600));
      const j = await api(`/jobs/${job}`); $('#prog').style.width = `${Math.round(j.progress * 100)}%`;
      if (j.status === 'done') {
        const r = j.result; const cp = r.checkpoint || r;
        $('#jobLbl').textContent = `${label} done`;
        if (r.new_lessons) addMsg('bot', `Auto-teach: the doctrine teacher found my mistakes on the training pack and wrote ${r.new_lessons.length} lessons:\n` + r.new_lessons.map((L) => `• ${L.relations.join(', ')} → ${L.topology} / ${L.act_rel}`).join('\n'));
        if (cp && cp.heldout) addMsg('bot', `${cp.id}: held-out topology ${(cp.heldout.topology * 100).toFixed(0)}%, transfer ${(cp.transfer.topology * 100).toFixed(0)}%, violations ${cp.heldout.violations}, retention ${cp.retention ?? '—'}. ${cp.promotable ? 'All gates pass: promotable.' : 'Not promotable yet.'}`);
        break;
      }
      if (j.status === 'error') { $('#jobLbl').textContent = `${label} failed`; toast(j.error.split('\n')[0], true); break; }
    }
  } catch (e) { toast(e.message, true); }
  $$('.evo-card button').forEach((b) => (b.disabled = false)); setTimeout(() => ($('#prog').style.width = '0'), 800);
  await afterLearn();
}

boot().catch((e) => toast(e.message, true));
