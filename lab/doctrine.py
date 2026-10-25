"""KAG doctrine evaluator — the fixed teacher.

indicators -> roles -> relations -> topology -> decision chain (tide -> regime -> breath/launch -> act -> finish)

The evaluator never learns. It is the reference the student is compared against.
"""
from __future__ import annotations

import numpy as np

from . import indicators as ind
from .market import Bars, Market
from .strategy import OFFICIAL_SETS, PRINCIPLES

SIDE_WORD = {1: "long_only", -1: "short_only", 0: "flat"}


# ---------------------------------------------------------------- perception: sensor arrays

def compute_sensor(b: Bars, sn: dict, adx_thr: float) -> dict:
    """Returns dict(value, side, state, extra) arrays over bars of one TF."""
    f, p, s = sn["family"], int(sn["period"]), int(sn.get("shift", 0))
    o, h, l, c, v = b.o, b.h, b.l, b.c, b.v
    n = len(c)
    side = np.zeros(n)
    state = np.array([""] * n, dtype=object)
    extra = {}
    val = np.full(n, np.nan)
    if f == "CCI":
        val = ind.shift_fwd(ind.cci(h, l, c, p), s); side = np.sign(val)
    elif f == "RSI":
        val = ind.shift_fwd(ind.rsi(c, p), s); side = np.sign(val - 50)
    elif f == "Momentum":
        val = ind.shift_fwd(ind.momentum(c, p), s); side = np.sign(val - 100)
    elif f == "Stochastic":
        val = ind.shift_fwd(ind.stochastic(h, l, c, p), s); side = np.sign(val - 50)
    elif f == "WPR":
        val = ind.shift_fwd(ind.wpr(h, l, c, p), s); side = np.sign(val + 50)
    elif f == "BullsPower":
        val = ind.shift_fwd(ind.bulls_power(h, c, p), s); side = np.sign(val)
    elif f == "BearsPower":
        val = ind.shift_fwd(ind.bears_power(l, c, p), s); side = np.sign(val)
    elif f == "MA":
        val = ind.shift_fwd(ind.sma(c, p), s); side = np.sign(c - val)
    elif f == "Envelopes":  # shifted SMA High/Low mass tunnel
        up = ind.shift_fwd(ind.sma(h, p), s); lo = ind.shift_fwd(ind.sma(l, p), s)
        body_lo, body_hi = np.minimum(o, c), np.maximum(o, c)
        side = np.where(body_lo > up, 1.0, np.where(body_hi < lo, -1.0, 0.0))
        side[np.isnan(up)] = 0
        val = (up + lo) / 2
        extra = {"upper": up, "lower": lo}
        state = np.where(side == 0, "inside_tunnel", "outside_tunnel").astype(object)
    elif f == "BB":
        mid = ind.sma(c, p); sd = ind.stddev(c, p)
        val = ind.shift_fwd(mid, s); side = np.sign(c - val)
        up, lo = mid + 2 * sd, mid - 2 * sd
        extra = {"upper": ind.shift_fwd(up, s), "lower": ind.shift_fwd(lo, s)}
        state = np.where((c > up) | (c < lo), "stretched", "").astype(object)
    elif f == "ADX":
        a, pdi, ndi = ind.adx(h, l, c, p)
        val = a; side = np.sign(pdi - ndi)
        state = np.where(a >= adx_thr, "tradable", "chop").astype(object)
    elif f == "StdDev":
        sd = ind.stddev(c, p); base = ind.sma(np.nan_to_num(sd), max(p * 3, 20))
        val = sd
        ratio = sd / np.where(base == 0, 1e-12, base)
        state = np.where(ratio > 2.5, "shock", np.where(ratio > 1.0, "expanding", "contracting")).astype(object)
        extra = {"ratio": ratio}
    elif f == "OBV":
        obv = np.cumsum(np.sign(np.diff(c, prepend=c[0])) * v)
        val = obv; side = np.sign(obv - ind.sma(obv, p))
    elif f == "MFI":
        tp = (h + l + c) / 3; mf = tp * v
        d = np.sign(np.diff(tp, prepend=tp[0]))
        pos = ind.sma(np.where(d > 0, mf, 0), p) * p; neg = ind.sma(np.where(d < 0, mf, 0), p) * p
        val = 100 - 100 / (1 + pos / np.where(neg == 0, 1e-12, neg)); side = np.sign(val - 50)
    elif f == "Volumes":
        val = v; state = np.where(v > ind.sma(v, p), "confirm", "").astype(object)
    else:  # allowed but not implemented -> inert sensor
        state = np.array(["inert"] * n, dtype=object)
    side = np.nan_to_num(side, nan=0.0)
    return {"value": val, "side": side, "state": state, "extra": extra}


class Perception:
    """Caches every sensor instance on every official set for one (market, strategy) pair."""

    def __init__(self, market: Market, strategy: dict):
        self.market, self.strategy = market, strategy
        self.cache: dict[tuple[str, str], dict] = {}
        self.instances: dict[int, list[dict]] = {}
        thr = float(strategy.get("adx_threshold", 20))
        for set_id, st in OFFICIAL_SETS.items():
            tf_of = {"anchor": [st["anchor"]], "support1": [st["supports"][0]], "support2": [st["supports"][1]], "supports": st["supports"]}
            lst = []
            for sn in strategy["sensors"]:
                for tf in tf_of[sn["slot"]]:
                    key = (sn["id"], tf)
                    if key not in self.cache:
                        self.cache[key] = compute_sensor(market.bars[tf], sn, thr)
                    lst.append({"iid": f"{sn['id']}@{tf}", "sensor_id": sn["id"], "family": sn["family"], "period": sn["period"],
                                "shift": sn.get("shift", 0), "tf": tf, "slot": "anchor" if tf == st["anchor"] else "support",
                                "role": sn["role"]})
            self.instances[set_id] = lst

    def read(self, set_id: int, t: float, lookback: int = 0) -> list[dict]:
        """Instance readings at cursor time t from completed bars only. lookback>0 adds side history on anchor."""
        out = []
        for inst in self.instances[set_id]:
            b = self.market.bars[inst["tf"]]
            i = b.index_at(t)
            arr = self.cache[(inst["sensor_id"], inst["tf"])]
            r = dict(inst)
            if i < 0:
                r.update(value=None, side=0, state="no_data", hist=[])
            else:
                val = arr["value"][i]
                r.update(value=None if np.isnan(val) else round(float(val), 4), side=int(arr["side"][i]), state=str(arr["state"][i]))
                if lookback:
                    lo = max(0, i - lookback)
                    r["hist"] = [int(x) for x in arr["side"][lo:i + 1]]
            out.append(r)
        return out


# ---------------------------------------------------------------- relations & decision chain

def _agg(readings: list[dict], role: str, slot: str | None = None, mask: set | None = None) -> tuple[int, list[str]]:
    rs = [r for r in readings if r["role"] == role and (slot is None or r["slot"] == slot) and not (mask and r["sensor_id"] in mask)
          and r["state"] not in ("inert", "no_data")]
    if not rs:
        return 0, []
    sides = {r["side"] for r in rs}
    side = sides.pop() if len(sides) == 1 else 0
    return int(side), [r["iid"] for r in rs]


def _rel(side: int, tide: int) -> str:
    if tide == 0:
        return "n/a"
    if side == 0:
        return "flat"
    return "with" if side == tide else "against"


def features_from(readings: list[dict], strategy: dict, finish: dict, mask: set | None = None) -> dict:
    """Relational observation (sensor-agnostic). This is what both doctrine and student interpret."""
    mask = mask or set()
    force, f_ev = _agg(readings, "force", "support", mask)
    f_sides = [r["side"] for r in readings if r["role"] == "force" and r["slot"] == "support" and r["sensor_id"] not in mask]
    support_force = "missing" if not f_sides else ("agree" if len(set(f_sides)) == 1 and f_sides[0] != 0 else "conflict")
    tide = force if support_force == "agree" else 0
    # tunnel G (Envelopes force on supports also act as mass)
    g_rs = [r for r in readings if r["family"] == "Envelopes" and r["slot"] == "support" and r["sensor_id"] not in mask]
    if not g_rs:
        G = "none"
    else:
        gs = {r["side"] for r in g_rs}
        g = gs.pop() if len(gs) == 1 else 0
        G = "inside" if g == 0 else _rel(g, tide) if tide else ("inside" if g == 0 else "against")
    gate_rs = [r for r in readings if r["role"] == "regime_gate" and r["family"] == "ADX" and r["sensor_id"] not in mask]
    gate = "none" if not gate_rs else ("tradable" if all(r["state"] == "tradable" for r in gate_rs) else "chop")
    exp_rs = [r for r in readings if r["role"] == "expansion" and r["sensor_id"] not in mask]
    exp = "none"
    if exp_rs:
        st = [r["state"] for r in exp_rs]
        exp = "shock" if "shock" in st else ("expanding" if "expanding" in st else "contracting")
    inertia, i_ev = _agg(readings, "inertia", "anchor", mask)
    velocity, v_ev = _agg(readings, "velocity", "anchor", mask)
    v_hist = [r.get("hist", []) for r in readings if r["role"] == "velocity" and r["slot"] == "anchor" and r["sensor_id"] not in mask]
    i_hist = [r.get("hist", []) for r in readings if r["role"] == "inertia" and r["slot"] == "anchor" and r["sensor_id"] not in mask]
    win, hold = int(strategy.get("release_window", 3)), int(strategy.get("launch_hold", 6))

    def combined(hists):
        if not hists or not hists[0]:
            return []
        L = min(len(x) for x in hists)
        return [(lambda s: s.pop() if len(s) == 1 else 0)({h[-L + k] for h in hists}) for k in range(L)]
    vh, ih = combined(v_hist), combined(i_hist)
    recent_load = False
    velocity_hold = False
    if tide and vh:
        prev = vh[-(win + 1):-1]
        prev_i = ih[-(win + 1):-1] if ih else [tide] * len(prev)
        recent_load = any(v == -tide and (i == tide) for v, i in zip(prev, prev_i))
        velocity_hold = len(vh) >= hold and all(v == tide for v in vh[-hold:])
    heat = "blocked" if float(finish.get("risk_used", 0)) >= float(finish.get("daily_risk", 1e9)) else "ok"
    goal = "reached" if float(finish.get("pnl_today", 0)) >= float(finish.get("daily_target", 1e9)) else "open"
    vol_conf = [r for r in readings if r["role"] == "volume_confirm" and r["sensor_id"] not in mask]
    return {
        "tide": SIDE_WORD[tide], "support_force": support_force, "G": G, "regime_gate": gate, "expansion": exp,
        "inertia": _rel(inertia, tide) if tide else ("up" if inertia > 0 else "down" if inertia < 0 else "flat"),
        "velocity": _rel(velocity, tide) if tide else ("up" if velocity > 0 else "down" if velocity < 0 else "flat"),
        "velocity_raw": "up" if velocity > 0 else "down" if velocity < 0 else "flat",
        "recent_load": recent_load, "velocity_hold": velocity_hold, "heat": heat, "goal": goal,
        "volume": "none" if not vol_conf else ("confirm" if any(r["side"] == tide or r["state"] == "confirm" for r in vol_conf) else "quiet"),
        "_evidence": {"force": f_ev, "inertia": i_ev, "velocity": v_ev,
                      "gate": [r["iid"] for r in gate_rs], "G": [r["iid"] for r in g_rs], "expansion": [r["iid"] for r in exp_rs]},
    }


def relations_from(fx: dict) -> list[str]:
    rel = []
    t = fx["tide"]
    side = "long" if t == "long_only" else "short" if t == "short_only" else None
    if fx["support_force"] == "agree" and side:
        rel.append(f"both_support_forces_{side}")
    elif fx["support_force"] == "conflict":
        rel.append("support_forces_conflict")
    if side:
        rel.append(f"inertia_{fx['inertia']}_tide" if fx["inertia"] in ("with", "against") else "inertia_flat")
        rel.append(f"velocity_{fx['velocity']}" if fx["velocity"] in ("with", "against") else "velocity_flat")
    if fx["G"] == "with":
        rel.append("G_fixed")
    elif fx["G"] == "against":
        rel.append("G_flipped")
    elif fx["G"] == "inside":
        rel.append("G_inside_tunnel")
    if fx["regime_gate"] == "chop":
        rel.append("efficiency_masks_ltf")
    if fx["recent_load"]:
        rel.append("load_within_release_window")
    if fx["velocity_hold"]:
        rel.append("velocity_held_with_tide")
    if fx["expansion"] == "shock":
        rel.append("vol_shock")
    if fx["heat"] == "blocked":
        rel.append("daily_risk_spent")
    if fx["goal"] == "reached":
        rel.append("daily_target_reached")
    return rel


def decide(fx: dict, strategy: dict) -> dict:
    """Fixed-order decision chain. Returns tide, regime, topology, act, wait_subtype and the chain trace."""
    chain = []
    ev = fx["_evidence"]
    t = fx["tide"]
    side = 1 if t == "long_only" else -1 if t == "short_only" else 0

    # 1 TIDE
    chain.append({"step": "tide", "form": "tide(set)", "result": t, "passed": side != 0, "evidence": ev["force"],
                  "why": {"agree": "both HTF supports agree", "conflict": "HTF supports disagree", "missing": "no HTF force sensor"}[fx["support_force"]]})
    # 2 REGIME
    if side == 0:
        regime = "range" if fx["support_force"] == "conflict" else "undefined"
        why = "no tide -> no play (m=0)"
    elif fx["G"] == "against":
        regime = "reversal_transition"; why = "macro tunnel G flipped against tide"
    elif fx["expansion"] == "shock":
        regime = "vol_shock"; why = "volatility clock in shock -> stand down"
    elif fx["regime_gate"] == "chop":
        regime = "chop"; why = "efficiency gate below threshold -> LTF fires masked"
    elif fx["G"] == "inside":
        regime = "undefined"; why = "macro tunnel inside/mixed -> permission revoked (G=0)"
    else:
        regime = "bull_trend" if side > 0 else "bear_trend"; why = "tide + gates allow play"
    tradable = regime in ("bull_trend", "bear_trend")
    chain.append({"step": "regime", "form": "regime_rewrite / efficiency_allows", "result": regime, "passed": tradable,
                  "evidence": ev["gate"] + ev["G"] + ev["expansion"], "why": why})
    # 3 BREATH vs LAUNCH
    if side == 0:
        topo, why = "chop", "no permission"
    elif fx["G"] == "against" or fx["inertia"] == "against":
        topo, why = "collapse", "inertia or macro G broke against tide"
    elif not tradable:
        topo, why = "chop", f"regime {regime} is no-play"
    elif fx["inertia"] in ("with", "n/a", "flat") and fx["velocity"] == "against":
        topo, why = "slingshot_load", "inertia with tide, velocity against = max tension"
    elif fx["velocity"] == "with" and fx["recent_load"]:
        topo, why = "slingshot_release", "velocity resumed with tide right after a load"
    elif fx["velocity"] == "with":
        topo, why = "launch", "fast and slow co-aligned with tide"
    else:
        topo, why = "chop", "velocity flat/mixed"
    chain.append({"step": "breath_launch", "form": "is_max_tension / is_launch / is_collapse", "result": topo,
                  "passed": topo in ("slingshot_load", "slingshot_release", "launch"), "evidence": ev["inertia"] + ev["velocity"], "why": why})
    # 4 ACT
    fire = "fire_buy" if side > 0 else "fire_sell"
    comp_ok = bool(ev["force"]) and bool(ev["velocity"])
    act_map = {"slingshot_load": "wait_loaded", "slingshot_release": fire, "launch": fire if strategy.get("allow_launch_entry") else "hold_manage",
               "collapse": "kill", "chop": "wait_no_trade"}
    act = act_map[topo]
    if act.startswith("fire") and not comp_ok:
        act, why = "wait_no_trade", "composition_valid failed (need force + velocity)"
    else:
        why = {"wait_loaded": "loaded-not-yet: wait for velocity to resume with tide", "wait_no_trade": "nothing to play",
               "kill": "velocity_valid_given_force = false -> kill/flatten", "hold_manage": "ride existing position; no chase entry"}.get(act, "fire with tide")
    chain.append({"step": "act", "form": "next_act / why_wait", "result": act, "passed": act.startswith("fire"), "evidence": [], "why": why})
    # 5 FINISH
    wait_sub = {"wait_loaded": "loaded", "wait_no_trade": "no_trade"}.get(act)
    fin_why = "plan still true at close"
    if act.startswith("fire") and fx["heat"] == "blocked":
        act, wait_sub, fin_why = "wait_no_trade", "heat", "daily risk spent -> heat blocks entry"
    elif act.startswith("fire") and fx["goal"] == "reached":
        act, wait_sub, fin_why = "bank", None, "daily target reached -> bank, no new risk"
    chain.append({"step": "finish", "form": "still_mark_at_close", "result": act, "passed": True, "evidence": [], "why": fin_why})

    key = "heat" if wait_sub == "heat" else "goal" if act == "bank" else topo
    return {"tide": t, "regime": regime, "topology": topo, "act": act, "wait_subtype": wait_sub, "chain": chain,
            "composition_valid": comp_ok, "principle_ids": PRINCIPLES.get(key, []), "relations": relations_from(fx)}


def consensus(tides: list[str]) -> str:
    s = set(tides)
    if s == {"long_only"}:
        return "agree_long"
    if s == {"short_only"}:
        return "agree_short"
    if "long_only" in s and "short_only" in s:
        return "conflict"
    return "incomplete"


class Doctrine:
    """Evaluate all four sets at a cursor time, with optional sensor masks for ablation influence."""

    def __init__(self, perception: Perception):
        self.p = perception
        self.strategy = perception.strategy

    def evaluate_set(self, set_id: int, t: float, finish: dict, mask: set | None = None, overrides: dict | None = None) -> dict:
        lb = max(int(self.strategy.get("launch_hold", 6)), int(self.strategy.get("release_window", 3))) + 2
        readings = self.p.read(set_id, t, lookback=lb)
        fx = features_from(readings, self.strategy, finish, mask)
        if overrides:
            fx.update({k: v for k, v in overrides.items() if k in fx})
        out = decide(fx, self.strategy)
        out.update(set_id=set_id, anchor=OFFICIAL_SETS[set_id]["anchor"], supports=OFFICIAL_SETS[set_id]["supports"],
                   readings=readings, features={k: v for k, v in fx.items() if not k.startswith("_")})
        return out

    def influence(self, set_id: int, t: float, finish: dict, base: dict, overrides: dict | None = None) -> dict:
        """Ablation: mask each sensor, see what changes. This is measured dependence, not a guess."""
        res = {}
        for sn in self.strategy["sensors"]:
            alt = self.evaluate_set(set_id, t, finish, mask={sn["id"]}, overrides=overrides)
            score = 0.0
            changed = []
            for k, w in (("act", 1.0), ("topology", 0.6), ("regime", 0.4), ("tide", 0.4)):
                if alt[k] != base[k]:
                    score = max(score, w); changed.append(f"{k}: {base[k]} -> {alt[k]}")
            res[sn["id"]] = {"score": score, "changed": changed}
        return res

    def evaluate(self, t: float, finish: dict, primary: int, overrides: dict | None = None, with_influence: bool = True) -> dict:
        sets = {sid: self.evaluate_set(sid, t, finish, overrides=overrides if sid == primary else None) for sid in OFFICIAL_SETS}
        cons = consensus([sets[s]["tide"] for s in sets])
        conviction = {"agree_long": "high", "agree_short": "high", "incomplete": "med", "conflict": "low"}[cons]
        size_feel = {"high": "normal", "med": "size_down", "low": "hold_dry_powder"}[conviction]
        out = {"sets": sets, "primary": primary, "consensus": cons, "conviction": conviction, "size_feel": size_feel,
               "global_act": sets[primary]["act"]}
        if with_influence:
            out["influence"] = self.influence(primary, t, finish, sets[primary], overrides)
        return out
