# Vizual NN — Strategy Evolution Lab

A local, visual, interactive lab where you **watch a student mind learn Momentum Conservation**, correct it frame by frame, add new strategies by talking to it, and only promote it when it passes hard gates.

Runs 100% on your machine (Cursor / VS Code). No hosting, no build step, no CDN.

```
pip install -r requirements.txt
cp .env.example .env        # optional: LLM + Alpaca keys
python run.py               # opens http://127.0.0.1:8000
```

In Cursor: **Run and Debug → "Vizual NN lab (run.py)"**, or **Terminal → Run Task → Run lab**.

---

## What you see

| Panel | What it shows | What you can do |
|---|---|---|
| Top bar | Market source, official Set 1–4, strategy, replay transport | Play / pause / step / scrub (Space, ← →) |
| Market conditions | Synthetic story + sliders (HTF trend, pullback depth/length, noise, volatility) | Change the world; the replay rebuilds |
| Finish line | Daily target / risk / risk used / PnL in R | Watch FINISH flip to heat / bank |
| Predicate lab | Override any relation (support force, G, regime gate, inertia, velocity, heat …) | Ask "what if" directly on the chain |
| Chart | Anchor candles, bands/lines, oscillators, doctrine act markers | — |
| Mind map | Sensors → roles → relations → TIDE/REGIME/BREATH/ACT/FINISH → output. Edge width = measured influence (masking). Violet halos = student attention | See which sensor drove the decision |
| Decision chain | Doctrine teacher vs student (candidate / approved / LLM), mismatches highlighted | Confirm → lesson, Correct → lesson, Ask LLM, Probe |
| Student thinking | Step-by-step reasoning, `[naive]` where it has not been taught | — |
| Official sets | All four sets read at the same moment + consensus / conviction / size feel | — |
| Talk to Fable | Chat with the student about the current frame | Add strategies, corrections, "why" questions |
| Strategy library | Versioned strategies (draft / active / archived), validator results | Load, edit JSON, activate, fork, archive |
| Evolution | Checkpoint metrics over time, gates, principles absorbed, lessons | Auto-teach, checkpoint, promote, forget |

## Architecture

```
lab/
  indicators.py   MT5-style indicators (SMA/EMA/Wilder, forward shift, CCI, RSI, Stoch, W%R, Bulls/Bears, ADX, StdDev …)
  market.py       Synthetic multi-TF market from one 1m path (stories: pullback_resume, pullback_hold, launch,
                  reversal, chop, vol_shock) + Alpaca READ-ONLY bars
  strategy.py     Official sets (immutable), roles, allowed MT5 universe, zero-shot role assignment,
                  validator (logical forms), offline text parser, versioned registry
  doctrine.py     The teacher: sensors → roles → relational features → fixed chain
                  tide → regime → breath/launch → act → finish, plus ablation influence and set consensus
  lessons.py      principle_application lessons (learn ≠ copy), candidate vs frozen approved memory
  student.py      OfflineStudent (lesson-memory, starts naive) and LLMStudent (in-context lessons,
                  self-reported attention + measured attention by masking)
  llm.py          OpenAI-compatible (OpenAI, OpenRouter, LM Studio, Ollama) or Anthropic client
  evaluator.py    train / held-out / transfer packs, scoring, retention, auto-teach, 100-day survival harness, gates
  server.py       FastAPI API + static UI
web/              index.html, styles.css, app.js (vanilla JS canvas + SVG)
seeds/strategies  Dual CCI Slingshot, Shifted SMA Gravity Tunnel, Dual RSI Slingshot
doctrine/         Put your private kag_mark_doctrine files here (git-ignored)
```

## How the LLM "learns" (plain language)

- The LLM's weights are frozen. It learns **in context**: every lesson you save is a `principle_application` record (relations → topology → act → principle_ids). The most similar lessons are retrieved and put in front of the model each time it reads a frame.
- Lessons store **relations, not indicator values**, so a lesson taught on CCI transfers to RSI or Stochastic doing the same job (the transfer pack tests exactly this).
- **Attention is shown two ways:** what the LLM *says* it looked at (self-reported), and what it *actually* depended on (Probe: mask each sensor, re-ask, see if the answer changes). Trust the measured one.
- Candidate memory learns live. **Approved memory is frozen** and only changes when a checkpoint passes every gate and you press Promote.
- No LLM key? The offline student does the same loop with lesson matching, so the whole lab works offline.

## Adding a strategy by talking

Type in chat (works offline too):

```
add strategy Stoch Slingshot: Stochastic 50 on supports as force, Stochastic 14 on anchor as velocity, ADX 14 on anchor as regime_gate
```

The validator enforces: allowed MT5 indicators only, every sensor has a role, force + velocity composition (no lone indicator), official sets only, and it warns on missing inertia / dual clock. Unknown roles are assigned zero-shot from TF slot and period relativity. Then **Save & activate**.

## Gates (promotion)

| Gate | Threshold |
|---|---|
| Held-out topology agreement | ≥ 0.85 |
| Held-out wait-subtype agreement | ≥ 0.85 |
| Doctrine violations on held-out | = 0 |
| Transfer topology (velocity family swapped) | ≥ 0.80 |
| Old-lesson retention | ≥ 0.95 |
| 100-day survival harness | breach = 0 and 0 doctrine violations |

## Observed results (offline student, Dual CCI Slingshot, clean start)

| Checkpoint | Lessons | Held-out topology | Transfer | Held-out violations | Survival raw violations |
|---|---|---|---|---|---|
| cp001 | 0 (naive) | 0.217 | 0.209 | 30 | 11,327 |
| cp002 | 4 | 0.674 | 0.767 | 7 | 3,302 |
| cp003 | 8 | 0.913 | 0.953 | 3 | 1,916 |
| cp004 | 9 | 0.978 | 1.000 | 0 | 142 |

Auto-teach runs out of training mistakes at 9 lessons. The survival harness still finds 142 untaught states, so the candidate is **not promotable** until you teach those frames yourself. That is the gate doing its job.

## Alpaca

Set `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` (paper keys work), switch the source to **Alpaca**, enter a symbol (`SPY`, `BTC/USD`) and press Load. The lab only calls the **market-data** API. There is no order code anywhere in this repo.

## Honest caveats

- The doctrine teacher is a coded approximation of the method. Your private doctrine files sharpen the LLM's reasoning but do not change the coded teacher.
- Synthetic stories are a harness, not a market. A high score here means the student copies the doctrine's *reasoning*, not that the doctrine has a live edge.
- The survival harness uses R units, spread per trade, and gap-through stops on synthetic days. It is a filter, not proof.
- Alpaca IEX data is thin outside regular hours; HTF supports on 1d need ~100 sessions of history.

## Tests

```
python -m pytest -q
```
