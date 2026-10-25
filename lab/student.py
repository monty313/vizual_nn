"""Students that learn the doctrine from lessons.

OfflineStudent — lesson-memory learner (no network). Starts as a naive 'lone indicator follower'
                 and improves only through principle_application lessons. Fully transparent.
LLMStudent     — the LLM itself is the student. Frozen weights; learns in context from retrieved
                 lessons. Shows its step-by-step reasoning, self-reported attention and, on demand,
                 MEASURED attention via counterfactual sensor masking.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import llm
from .lessons import KEY_FEATURES, relational_key, rel_to_act
from .strategy import PRINCIPLES

FEATURE_SOURCES = {  # which role's sensors produce each relational feature (for attention -> sensor mapping)
    "tide_state": ["force"], "support_force": ["force"], "G": ["force"], "regime_gate": ["regime_gate"],
    "expansion": ["expansion"], "inertia": ["inertia"], "velocity": ["velocity"], "recent_load": ["velocity", "inertia"],
    "velocity_hold": ["velocity"], "heat": [], "goal": [],
}


def similarity(key: dict, other: dict, weights: dict) -> tuple[float, dict]:
    tot = sum(weights.get(f, 1.0) for f in KEY_FEATURES)
    contrib = {}
    s = 0.0
    for f in KEY_FEATURES:
        w = weights.get(f, 1.0)
        m = 1.0 if key.get(f) == other.get(f) else 0.0
        contrib[f] = w * m / tot
        s += w * m
    return s / tot, contrib


def retrieve(fx: dict, memory: dict, k: int = 6) -> list[tuple[float, dict]]:
    key = relational_key(fx)
    scored = [(similarity(key, L["key"], memory["weights"])[0], L) for L in memory["lessons"]]
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def principles_absorbed(memory: dict) -> dict:
    out: dict[str, int] = {}
    for L in memory["lessons"]:
        for p in L["principle_ids"]:
            out[p] = out.get(p, 0) + 1
    return out


def _sensor_attention(feature_att: dict, readings: list[dict]) -> dict:
    att: dict[str, float] = {}
    for f, a in feature_att.items():
        roles = FEATURE_SOURCES.get(f, [])
        ids = sorted({r["sensor_id"] for r in readings if r["role"] in roles})
        for sid in ids:
            att[sid] = att.get(sid, 0.0) + a / max(1, len(ids))
    tot = sum(att.values()) or 1.0
    return {k: round(v / tot, 3) for k, v in att.items()}


class OfflineStudent:
    kind = "offline"

    def __init__(self, memory: dict):
        self.memory = memory

    def predict(self, frame_set: dict) -> dict:
        fx = frame_set["features"]
        readings = frame_set["readings"]
        absorbed = principles_absorbed(self.memory)
        thinking = []
        # TIDE — until it learns "LTF never votes side", it follows anchor velocity like a lone-indicator copier.
        if absorbed.get("ltf_never_votes_side") or absorbed.get("dominant_trends") or absorbed.get("no_play_without_tide"):
            tide = fx["tide"]
            thinking.append({"step": "tide", "thought": f"HTF support force says {tide} (principle ltf_never_votes_side, "
                                                        f"{absorbed.get('ltf_never_votes_side', 0) + absorbed.get('dominant_trends', 0)} lessons)."})
        else:
            vr = fx["velocity_raw"]
            tide = "long_only" if vr == "up" else "short_only" if vr == "down" else "flat"
            thinking.append({"step": "tide", "thought": f"No lesson yet on permission. I follow the anchor's fast oscillator ({vr}) -> {tide}. [naive]"})
        best, contrib, sim = None, {}, 0.0
        if self.memory["lessons"]:
            key = relational_key(fx)
            for L in self.memory["lessons"]:
                s, c = similarity(key, L["key"], self.memory["weights"])
                if s > sim:
                    sim, best, contrib = s, L, c
        mode = "recall" if best and sim >= 0.999 else "generalize" if best and sim >= 0.8 else "naive"
        if mode == "naive":
            topo = "launch" if fx["velocity_raw"] != "flat" else "chop"
            act = ("fire_buy" if fx["velocity_raw"] == "up" else "fire_sell") if topo == "launch" else "wait_no_trade"
            regime = "bull_trend" if tide == "long_only" else "bear_trend" if tide == "short_only" else "undefined"
            wait = "no_trade" if act == "wait_no_trade" else None
            feat_att = {"velocity": 1.0}
            thinking.append({"step": "breath_launch", "thought": f"No lesson close to this relation pattern (best match {sim:.0%}). "
                                                                 f"Velocity moves -> I call it {topo}. [naive]"})
            used = []
        else:
            topo = best["topology"]
            regime = best["regime"] if best["regime"] not in ("bull_trend", "bear_trend") else ("bull_trend" if tide == "long_only" else "bear_trend" if tide == "short_only" else "undefined")
            act = rel_to_act(best["act_rel"], tide)
            wait = best.get("wait_subtype")
            feat_att = contrib
            matched = [f for f in KEY_FEATURES if contrib.get(f, 0) > 0]
            missed = [f for f in KEY_FEATURES if contrib.get(f, 0) == 0]
            thinking.append({"step": "regime", "thought": f"Gate={fx['regime_gate']}, G={fx['G']}, expansion={fx['expansion']} -> {regime}."})
            thinking.append({"step": "breath_launch", "thought": f"{'Same' if mode == 'recall' else 'Similar'} relation pattern as lesson {best['lesson_id']} "
                                                                 f"({sim:.0%} match; matched {', '.join(matched[:5])}{'; differs on ' + ', '.join(missed) if missed else ''}) -> {topo}."})
            used = [best["lesson_id"]]
            if not (absorbed.get("capital_preservation") or absorbed.get("floor_is_sacred")) and act == "wait_no_trade" and best.get("wait_subtype") == "heat":
                pass
        # FINISH — heat/goal only respected once taught
        knows_heat = bool(absorbed.get("floor_is_sacred") or absorbed.get("finish_line_judgment"))
        if knows_heat and fx["heat"] == "blocked" and act.startswith("fire"):
            act, wait = "wait_no_trade", "heat"
        if knows_heat and fx["goal"] == "reached" and act.startswith("fire"):
            act, wait = "bank", None
        thinking.append({"step": "act", "thought": f"Act {act}{' (' + wait + ')' if wait else ''}."})
        thinking.append({"step": "finish", "thought": "Heat/goal respected." if knows_heat else "I have not been taught heat/goal yet; I ignore the finish line. [naive]"})
        return {"student": "offline", "tide": tide, "regime": regime, "topology": topo, "act": act, "wait_subtype": wait,
                "mode": mode, "match": round(sim, 3), "lessons_used": used, "thinking": thinking,
                "attention": _sensor_attention(feat_att, readings), "attention_kind": "lesson-match weights",
                "feature_attention": {k: round(v, 3) for k, v in feat_att.items()}, "confidence": round(sim if mode != "naive" else 0.3, 2)}


# ---------------------------------------------------------------- LLM student

DOCTRINE_DIR = Path(__file__).resolve().parent.parent / "doctrine"

CORE_DOCTRINE = """You are FABLE 5.1, the student mind of Mark's Momentum Conservation trading doctrine (KAG, not RAG).
You reason ONLY through: indicators -> roles -> relations -> topology -> decision chain. Never lone-indicator recipes.
Official sets (immutable): 1: 1m|15m,30m  2: 5m|30m,1h  3: 15m|1h,4h  4: 30m|4h,1d. First = LTF anchor, others = HTF supports.
Roles: force | inertia | velocity | equilibrium | regime_gate | expansion | volume_confirm.
Decision chain (fixed order): 1 TIDE (allowed side from BOTH HTF support forces; LTF never votes side) ->
2 REGIME (bull_trend/bear_trend/chop/range/undefined/reversal_transition/vol_shock; no play unless trend) ->
3 BREATH vs LAUNCH (inertia with tide + velocity against = slingshot_load; velocity resumes with tide right after a load = slingshot_release;
fast and slow co-aligned = launch; inertia or macro G against tide = collapse; no tide/no play = chop) ->
4 ACT (load->wait_loaded, release->fire with tide, launch->hold_manage unless launch entries allowed, collapse->kill, chop->wait_no_trade) ->
5 FINISH (daily risk spent -> no new entries (wait subtype heat); daily target reached -> bank).
Wait = loaded-not-yet (skill), never freeze. Pullback is not reversal. Momentum and volatility are separate.
Five laws: dominant trends; breath vs launch; regime survival; capital preservation; speed vs weight."""


def doctrine_context(max_chars: int = 9000) -> str:
    """Core doctrine plus any files the user drops into ./doctrine (e.g. kag_mark_doctrine/*)."""
    txt = CORE_DOCTRINE
    if DOCTRINE_DIR.exists():
        extra = []
        for p in sorted(DOCTRINE_DIR.glob("**/*")):
            if p.suffix.lower() in (".md", ".yaml", ".yml", ".txt") and p.name.lower() != "readme.md":
                extra.append(f"\n--- {p.name} ---\n{p.read_text(errors='ignore')}")
        blob = "".join(extra)
        if blob:
            txt += "\n\nPROJECT DOCTRINE FILES (ground truth):" + blob[:max_chars]
    return txt


PREDICT_FORMAT = """Return ONLY JSON:
{"thinking":[{"step":"tide","thought":"..."},{"step":"regime","thought":"..."},{"step":"breath_launch","thought":"..."},{"step":"act","thought":"..."},{"step":"finish","thought":"..."}],
 "tide":"long_only|short_only|flat","regime":"...","topology":"slingshot_load|slingshot_release|launch|mean_reversion|reversal|range_fade|collapse|chop",
 "act":"fire_buy|fire_sell|wait_loaded|wait_no_trade|kill|hold_manage|bank","wait_subtype":"loaded|no_trade|heat|null",
 "attention":{"<sensor_id>":0.0},"lessons_used":["L-..."],"confidence":0.0}
attention = how much each sensor_id drove your decision (sums to 1). Cite lesson ids you applied."""


def observation_text(frame_set: dict, finish: dict, strategy: dict) -> str:
    rows = [f"- {r['sensor_id']} | {r['family']}({r['period']}{', shift ' + str(r['shift']) if r['shift'] else ''}) on {r['tf']} [{r['slot']}] "
            f"role={r['role']} value={r['value']} side={r['side']:+d} state={r['state'] or '-'}" for r in frame_set["readings"]]
    hist = [f"  {r['sensor_id']}@{r['tf']} recent sides: {r.get('hist')}" for r in frame_set["readings"] if r["slot"] == "anchor" and r.get("hist")]
    return (f"Strategy: {strategy['name']} v{strategy['version']} (release_window={strategy.get('release_window')}, "
            f"launch_hold={strategy.get('launch_hold')}, allow_launch_entry={strategy.get('allow_launch_entry')})\n"
            f"Set {frame_set['set_id']}: anchor {frame_set['anchor']}, supports {', '.join(frame_set['supports'])}\n"
            f"Sensor readings (completed bars only):\n" + "\n".join(rows) + "\nAnchor side history (oldest->newest):\n" + "\n".join(hist) +
            f"\nFinish line: daily_target={finish.get('daily_target')} daily_risk={finish.get('daily_risk')} "
            f"risk_used={finish.get('risk_used')} pnl_today={finish.get('pnl_today')}")


def lessons_text(retrieved: list[tuple[float, dict]]) -> str:
    if not retrieved:
        return "No lessons yet. You have only the doctrine."
    out = []
    for s, L in retrieved:
        out.append(json.dumps({"lesson_id": L["lesson_id"], "match": round(s, 2), "relations": L["relations"], "topology": L["topology"],
                               "act_rel": L["act_rel"], "wait_subtype": L.get("wait_subtype"), "principle_ids": L["principle_ids"],
                               "note": L.get("note", "")}))
    return "Lessons from Mark (principle applications, retrieved by relation similarity):\n" + "\n".join(out)


class LLMStudent:
    kind = "llm"

    def __init__(self, memory: dict):
        self.memory = memory

    def predict(self, frame_set: dict, finish: dict, strategy: dict, mask: set | None = None) -> dict:
        fs = frame_set
        if mask:
            fs = dict(frame_set)
            fs["readings"] = [r for r in frame_set["readings"] if r["sensor_id"] not in mask]
        retrieved = retrieve(frame_set["features"], self.memory)
        user = observation_text(fs, finish, strategy) + "\n\n" + lessons_text(retrieved) + "\n\n" + PREDICT_FORMAT
        text, meta = llm.chat(doctrine_context(), [{"role": "user", "content": user}], max_tokens=1200, temperature=0.0)
        js = llm.parse_json(text)
        att = js.get("attention") or {}
        tot = sum(float(v) for v in att.values() if isinstance(v, (int, float))) or 1.0
        js["attention"] = {k: round(float(v) / tot, 3) for k, v in att.items() if isinstance(v, (int, float))}
        js.update(student="llm", attention_kind="self-reported", meta=meta, retrieved=[L["lesson_id"] for _, L in retrieved],
                  prompt_chars=len(user))
        if js.get("wait_subtype") in ("null", "", None):
            js["wait_subtype"] = None
        return js

    def probe(self, frame_set: dict, finish: dict, strategy: dict, base: dict) -> dict:
        """Measured attention: mask each sensor and see whether the LLM changes its mind."""
        res = {}
        for sid in sorted({r["sensor_id"] for r in frame_set["readings"]}):
            alt = self.predict(frame_set, finish, strategy, mask={sid})
            changed = [f"{k}: {base.get(k)} -> {alt.get(k)}" for k in ("act", "topology", "tide") if alt.get(k) != base.get(k)]
            score = 1.0 if alt.get("act") != base.get("act") else 0.6 if alt.get("topology") != base.get("topology") else 0.4 if changed else 0.0
            res[sid] = {"score": score, "changed": changed}
        return res


CHAT_FORMAT = """Reply with ONLY JSON:
{"reply":"plain-language answer to Mark (ENTJ, simple, no fluff)",
 "thinking":["short reasoning steps you actually used"],
 "intent":"chat|add_strategy|correction|explain",
 "strategy_spec": null or {"name":"...","explanation":"...","primary_set":2,"allow_launch_entry":false,"release_window":3,"launch_hold":6,"adx_threshold":20,
   "sensors":[{"family":"CCI|RSI|Momentum|Stochastic|WPR|BullsPower|BearsPower|MA|Envelopes|BB|ADX|StdDev|OBV|MFI|Volumes","period":14,"shift":0,
   "slot":"anchor|support1|support2|supports","role":"force|inertia|velocity|equilibrium|regime_gate|expansion|volume_confirm"}],"principle_ids":["..."]},
 "correction": null or {"layer":"tide|regime|topology|act|wait_subtype","tide":"...","topology":"...","act":"...","wait_subtype":"...","note":"why, in Mark's words"}}
Rules: a strategy must have >=1 force sensor on support slots and >=1 velocity sensor on the anchor. Use only the listed families.
Only fill "correction" when Mark is telling you that your reading of the CURRENT market frame is wrong."""


def llm_chat(message: str, history: list[dict], frame_summary: str, strategies: list[dict], memory: dict) -> dict:
    sys = doctrine_context() + "\n\nYou are talking live with Mark, your teacher. Explain HOW you think, step by step, in his language."
    ctx = (f"Strategy library: {json.dumps(strategies)[:2500]}\n\nCurrent frame you are looking at:\n{frame_summary}\n\n"
           f"Lessons in memory: {len(memory['lessons'])}; principles absorbed: {principles_absorbed(memory)}\n\n{CHAT_FORMAT}")
    msgs = [*history[-8:], {"role": "user", "content": f"{ctx}\n\nMark says: {message}"}]
    text, meta = llm.chat(sys, msgs, max_tokens=1600, temperature=0.3)
    try:
        js = llm.parse_json(text)
    except llm.LLMError:
        js = {"reply": text, "intent": "chat", "thinking": []}
    js["meta"] = meta
    return js


__all__ = ["OfflineStudent", "LLMStudent", "llm_chat", "retrieve", "principles_absorbed", "PRINCIPLES"]
