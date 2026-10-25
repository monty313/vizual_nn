"""Evolution scoreboard: scenario packs, metrics, auto-curriculum, survival harness, promotion gates.

Train pack  -> where auto-curriculum lessons come from.
Held-out    -> unseen seeds (never taught from).
Transfer    -> unseen seeds AND the velocity family swapped (CCI<->RSI) = held_out_transfer.
Retention   -> every lesson in memory replayed; the student must still answer it.
"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import numpy as np

from .doctrine import Doctrine, Perception
from .lessons import make_lesson, rel_to_act
from .market import STORIES, synthetic_market
from .strategy import normalize

DEFAULT_FINISH = {"daily_target": 3.0, "daily_risk": 2.0, "risk_used": 0.0, "pnl_today": 0.0}
SWAP = {"CCI": "RSI", "RSI": "CCI", "Stochastic": "RSI", "Momentum": "CCI", "WPR": "Stochastic", "BullsPower": "CCI", "BearsPower": "CCI"}

GATES = {
    "heldout_topology": ("Held-out topology agreement", 0.85),
    "heldout_wait": ("Held-out wait-subtype agreement", 0.85),
    "heldout_violations": ("Doctrine violations on held-out (must be 0)", 0),
    "transfer_topology": ("Transfer topology (velocity family swapped)", 0.80),
    "retention": ("Old-lesson retention", 0.95),
    "survival": ("100-day survival harness: breach = 0 and 0 doctrine violations", 0),
}


def transfer_strategy(strategy: dict) -> dict:
    s = copy.deepcopy(strategy)
    for sn in s["sensors"]:
        if sn["role"] in ("velocity", "inertia") and sn["family"] in SWAP:
            sn["family"] = SWAP[sn["family"]]
            sn["id"] = f"{sn['family']}{sn['period']}_{sn['slot']}"
    s["id"] = s["id"] + "_transfer"
    return normalize(s)


def build_pack(strategy: dict, kind: str, per_story: int = 8, seeds: list[int] | None = None, set_id: int = 2,
               cache_dir: Path | None = None) -> list[dict]:
    seeds = seeds or ({"train": [101, 102], "heldout": [901], "transfer": [902]}[kind])
    strat = transfer_strategy(strategy) if kind == "transfer" else strategy
    cache = None
    if cache_dir:
        cache = Path(cache_dir) / f"{strategy['id']}@{strategy['version']}_{kind}_{per_story}_{set_id}.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            return json.loads(cache.read_text())
    items = []
    rng = random.Random(hash((kind, strategy["id"])) % 10_000)
    for story in STORIES:
        for seed in seeds:
            m = synthetic_market({"story": story, "seed": seed})
            D = Doctrine(Perception(m, strat))
            a = m.bars[{1: "1m", 2: "5m", 3: "15m", 4: "30m"}[set_id]]
            i0, i1 = a.index_at(m.replay_start), a.index_at(m.replay_end)
            by_topo: dict[str, list] = {}
            for i in range(i0, i1 + 1, 2):
                fin = dict(DEFAULT_FINISH)
                r = D.evaluate_set(set_id, float(a.t_close[i]), fin)
                by_topo.setdefault(r["topology"], []).append((i, r))
            picks = []
            for lst in by_topo.values():  # stratify so rare classes (release) are present
                picks += rng.sample(lst, min(len(lst), max(1, per_story // max(1, len(by_topo)))))
            for i, r in picks[:per_story]:
                items.append(_item(r, story, seed, i))
            # a heat case per scenario: same frame but daily risk spent
            fire = [(i, r) for i, r in picks if r["act"].startswith("fire")]
            if fire:
                i, _ = fire[0]
                r = D.evaluate_set(set_id, float(a.t_close[i]), {**DEFAULT_FINISH, "risk_used": 2.0})
                items.append(_item(r, story, seed, i, tag="heat"))
    if cache:
        cache.write_text(json.dumps(items))
    return items


def _item(r: dict, story: str, seed: int, i: int, tag: str = "") -> dict:
    return {"story": story, "seed": seed, "bar": int(i), "tag": tag,
            "frame_set": {k: r[k] for k in ("set_id", "anchor", "supports", "readings", "features", "relations", "regime")},
            "label": {k: r[k] for k in ("tide", "regime", "topology", "act", "wait_subtype", "principle_ids", "relations")}}


def violation(pred: dict, label: dict) -> str | None:
    act, tide = pred.get("act", ""), label["tide"]
    if act.startswith("fire"):
        if tide == "flat":
            return "fire without tide"
        if (act == "fire_buy") != (tide == "long_only"):
            return "fire against HTF tide"
        if label["topology"] in ("collapse", "chop"):
            return f"fire into {label['topology']}"
        if label.get("wait_subtype") == "heat":
            return "fire with daily risk spent"
    return None


def score(student, pack: list[dict], finish_of=None, strategy=None, limit: int | None = None) -> dict:
    items = pack if not limit else pack[:limit]
    n = len(items) or 1
    agg = {"tide": 0, "regime": 0, "topology": 0, "act": 0, "wait_subtype": 0}
    viol, copying = [], 0
    for it in items:
        fs, lab = it["frame_set"], it["label"]
        if student.kind == "llm":
            fin = {**DEFAULT_FINISH, "risk_used": 2.0} if it["tag"] == "heat" else DEFAULT_FINISH
            try:
                p = student.predict(fs, fin, strategy)
            except Exception as e:  # noqa: BLE001
                p = {"act": "error", "topology": "error", "tide": "error", "regime": "error", "wait_subtype": str(e)[:60]}
        else:
            p = student.predict(fs)
        for k in agg:
            agg[k] += int(p.get(k) == lab.get(k))
        v = violation(p, lab)
        if v:
            viol.append({"story": it["story"], "bar": it["bar"], "why": v})
        if p.get("act") == lab["act"] and p.get("topology") != lab["topology"]:
            copying += 1
    out = {k: round(v / n, 3) for k, v in agg.items()}
    out["violations"] = len(viol)
    out["violation_examples"] = viol[:5]
    out["copy_rate"] = round(copying / n, 3)
    out["n"] = len(items)
    return out


def retention(student, memory: dict, strategy=None, limit: int = 40) -> float | None:
    L = memory["lessons"][-limit:]
    if not L:
        return None
    ok = 0
    for les in L:
        fs = {"set_id": les["set_id"], "anchor": "", "supports": [], "features": les["features"], "relations": les["relations"],
              "readings": [{**s, "slot": "anchor" if s["tf"] in ("1m", "5m", "15m") else "support", "state": "", "hist": []} for s in les["sensors"]]}
        if student.kind == "llm":
            try:
                p = student.predict(fs, DEFAULT_FINISH, strategy)
            except Exception:  # noqa: BLE001
                p = {}
        else:
            p = student.predict(fs)
        ok += int(p.get("topology") == les["topology"] and p.get("act") == rel_to_act(les["act_rel"], p.get("tide", les["tide"])))
    return round(ok / len(L), 3)


def auto_teach(student, pack: list[dict], strategy: dict, memory_obj, k: int = 5) -> list[dict]:
    """Doctrine teacher finds the student's mistakes on the TRAIN pack and emits up to k new lessons."""
    seen, new = set(), []
    for it in pack:
        p = student.predict(it["frame_set"]) if student.kind != "llm" else student.predict(it["frame_set"], DEFAULT_FINISH, strategy)
        lab = it["label"]
        if all(p.get(x) == lab.get(x) for x in ("topology", "act", "wait_subtype", "tide")):
            continue
        key = json.dumps(sorted(it["frame_set"]["features"].items(), key=lambda x: x[0]), default=str)
        if key in seen:
            continue
        seen.add(key)
        L = make_lesson(it["frame_set"], lab, strategy, source="auto_curriculum", student=p, doctrine=lab,
                        note=f"Doctrine teacher: {lab['topology']} -> {lab['act']} ({it['story']})")
        memory_obj.add(L)
        new.append(L)
        if len(new) >= k:
            break
    return new


def survival(policy: str, strategy: dict, memory: dict | None, days: int = 100, spread: float = 0.02, seed0: int = 5000,
             daily_risk: float = 2.0, daily_target: float = 3.0, progress=None) -> dict:
    """Synthetic-day harness (R units). Doctrine-gated execution of the chosen policy. NOT evidence of live edge."""
    from .student import OfflineStudent
    stud = OfflineStudent(memory) if policy == "candidate" and memory is not None else None
    rng = random.Random(seed0)
    stories = list(STORIES)
    days_out, breaches, viol = [], 0, 0
    for d in range(days):
        story = rng.choice(stories)
        m = synthetic_market({"story": story, "seed": seed0 + d, "days": 8, "trend": rng.choice([-1, 1]) * rng.uniform(0.4, 1.0),
                              "tail_hours": 24})
        D = Doctrine(Perception(m, strategy))
        a = m.bars["5m"]
        i0, i1 = a.index_at(m.replay_start), a.index_at(m.replay_end)
        rng_atr = np.nanmean(np.abs(np.diff(a.c[i0 - 50:i0]))) * 6
        pnl, pos, entry, stop, trades = 0.0, 0, 0.0, 0.0, 0
        for i in range(i0, i1):
            fin = {"daily_target": daily_target, "daily_risk": daily_risk, "risk_used": max(0.0, -pnl), "pnl_today": pnl}
            r = D.evaluate_set(2, float(a.t_close[i]), fin)
            act = r["act"] if stud is None else stud.predict(r)["act"]
            if act.startswith("fire") and violation({"act": act}, r):
                viol += 1
            if pos:
                hit = (a.l[i + 1] <= stop) if pos > 0 else (a.h[i + 1] >= stop)
                open_r = pos * (a.c[i] - entry) / rng_atr
                bank = pnl + open_r - spread >= daily_target
                if hit or bank or act in ("kill",) or r["topology"] == "collapse":
                    # stops fill at the stop unless the next bar gaps through it
                    gap = (a.o[i + 1] < stop) if pos > 0 else (a.o[i + 1] > stop)
                    px = (a.o[i + 1] if gap else stop) if hit else a.o[i + 1]
                    pnl += pos * (px - entry) / rng_atr - spread
                    pos = 0
                continue
            budget_ok = (-pnl) + 1.0 + spread <= daily_risk + 1e-9  # never risk more than what is left of the daily floor
            if act in ("fire_buy", "fire_sell") and budget_ok and pnl < daily_target and trades < int(strategy.get("risk", {}).get("max_trades_per_day", 4)):
                pos = 1 if act == "fire_buy" else -1
                entry = a.o[i + 1]
                stop = entry - pos * rng_atr
                trades += 1
        if pos:
            pnl += pos * (a.c[i1] - entry) / rng_atr - spread
        pnl = float(pnl)
        breach = bool(pnl < -daily_risk - 1e-9)
        breaches += int(breach)
        days_out.append({"day": d + 1, "story": story, "pnl_R": round(pnl, 3), "trades": trades, "breach": breach})
        if progress:
            progress((d + 1) / days)
    pn = [x["pnl_R"] for x in days_out]
    return {"policy": policy, "days": days, "breaches": breaches, "raw_violations": viol, "total_R": round(sum(pn), 2),
            "win_days": sum(1 for x in pn if x > 0), "target_days": sum(1 for x in pn if x >= daily_target),
            "worst_day_R": round(min(pn), 2), "daily": days_out,
            "note": "Synthetic stories, R units, spread per trade, gap-through stops possible. Harness, not proof of live edge."}


def gates(cp: dict) -> list[dict]:
    out = []
    for gid, (label, thr) in GATES.items():
        if gid == "heldout_violations":
            v = cp.get("heldout", {}).get("violations")
            ok = v is not None and v == 0
        elif gid == "survival":
            s = cp.get("survival")
            v = None if not s else s["breaches"] + s.get("raw_violations", 0)
            ok = s is not None and s["breaches"] == 0 and s.get("raw_violations", 0) == 0 and s["days"] >= 100
        elif gid == "retention":
            v = cp.get("retention")
            ok = v is not None and v >= thr
        else:
            grp, met = gid.split("_")
            met = {"wait": "wait_subtype"}.get(met, met)
            v = cp.get(grp, {}).get(met)
            ok = v is not None and v >= thr
        out.append({"gate": gid, "label": label, "value": v, "threshold": thr, "ok": bool(ok)})
    return out
