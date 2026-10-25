"""Strategy specs, doctrine validator, novel-role inference (assign_role) and versioned registry."""
from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path

OFFICIAL_SETS = {
    1: {"anchor": "1m", "supports": ["15m", "30m"]},
    2: {"anchor": "5m", "supports": ["30m", "1h"]},
    3: {"anchor": "15m", "supports": ["1h", "4h"]},
    4: {"anchor": "30m", "supports": ["4h", "1d"]},
}
ROLES = ["force", "inertia", "velocity", "equilibrium", "regime_gate", "expansion", "volume_confirm"]
SLOTS = ["anchor", "support1", "support2", "supports"]
TOPOLOGIES = ["slingshot_load", "slingshot_release", "launch", "mean_reversion", "reversal", "range_fade", "collapse", "chop"]
ACTIONS = ["fire_buy", "fire_sell", "wait_loaded", "wait_no_trade", "kill", "hold_manage", "size_up", "size_down", "bank"]
REGIMES = ["bull_trend", "bear_trend", "chop", "range", "expansion", "reversal_transition", "undefined", "vol_shock"]

# MT5 allowed universe (project doctrine). implemented=True means the lab can compute it today.
FAMILIES = {
    "CCI": ("oscillator", True), "RSI": ("oscillator", True), "Momentum": ("oscillator", True),
    "Stochastic": ("oscillator", True), "WPR": ("oscillator", True), "BullsPower": ("oscillator", True),
    "BearsPower": ("oscillator", True), "DeMarker": ("oscillator", False), "ForceIndex": ("oscillator", False),
    "RVI": ("oscillator", False), "AC": ("bill_williams", False), "AO": ("bill_williams", False),
    "MA": ("trend", True), "Envelopes": ("trend", True), "BB": ("trend", True), "ADX": ("trend", True),
    "Ichimoku": ("trend", False), "ParabolicSAR": ("trend", False), "Alligator": ("bill_williams", False),
    "Fractals": ("bill_williams", False), "Gator": ("bill_williams", False),
    "StdDev": ("trend", True),  # MT5 Standard Deviation — used by the GrowRich dual-clock scan
    "OBV": ("volume", True), "MFI": ("volume", True), "Volumes": ("volume", True), "AD": ("volume", False),
}
FAMILY_ALIASES = {
    "cci": "CCI", "rsi": "RSI", "momentum": "Momentum", "mom": "Momentum", "stoch": "Stochastic",
    "stochastic": "Stochastic", "wpr": "WPR", "w%r": "WPR", "williams": "WPR", "bulls": "BullsPower",
    "bullspower": "BullsPower", "bulls power": "BullsPower", "bears": "BearsPower", "bearspower": "BearsPower",
    "bears power": "BearsPower", "sma": "MA", "ema": "MA", "ma": "MA", "moving average": "MA",
    "envelope": "Envelopes", "envelopes": "Envelopes", "tunnel": "Envelopes", "shifted sma": "Envelopes",
    "bb": "BB", "bollinger": "BB", "bollinger bands": "BB", "adx": "ADX", "stddev": "StdDev",
    "standard deviation": "StdDev", "std": "StdDev", "obv": "OBV", "mfi": "MFI", "volumes": "Volumes",
    "volume": "Volumes", "demarker": "DeMarker", "force index": "ForceIndex", "rvi": "RVI", "ao": "AO", "ac": "AC",
    "ichimoku": "Ichimoku", "sar": "ParabolicSAR", "parabolic sar": "ParabolicSAR", "alligator": "Alligator",
}

PRINCIPLES = {
    "slingshot_load": ["dual_period_tension", "ltf_never_votes_side", "wait_is_skill"],
    "slingshot_release": ["velocity_resumes_inside_force", "fire_with_tide", "dominant_trends"],
    "launch": ["breath_vs_launch", "ride_launch_dont_chase", "speed_vs_weight"],
    "collapse": ["force_flip_kills", "velocity_invalid_without_force", "capital_preservation"],
    "chop": ["regime_survival", "no_play_without_tide", "wait_is_skill"],
    "heat": ["capital_preservation", "floor_is_sacred", "finish_line_judgment"],
    "goal": ["finish_line_judgment", "enough_is_enough"],
}


def assign_role(family: str, slot: str, period: int, siblings: list[dict] | None = None) -> tuple[str, str, str]:
    """Zero-shot role inference (novel_indicator_protocol): TF slot + shape + period relativity.

    Returns (role, confidence, why).
    """
    kind = FAMILIES.get(family, ("unknown", False))[0]
    sib = [s for s in (siblings or []) if s.get("family") == family and s.get("slot") == slot and s.get("period") != period]
    if family == "ADX":
        return "regime_gate", "high", "ADX measures trend efficiency, not side -> regime gate"
    if family == "StdDev":
        return "expansion", "high", "StdDev is a volatility clock -> expansion"
    if family in ("OBV", "MFI", "Volumes", "AD"):
        return "volume_confirm", "medium", "volume family confirms participation; never sets tide"
    if family == "Envelopes":
        return ("force" if slot != "anchor" else "velocity"), "high", "shifted High/Low tunnel: HTF = mass (G), LTF = micro phase"
    if slot in ("support1", "support2", "supports"):
        if kind in ("oscillator", "trend", "bill_williams"):
            return "force", "high" if family in ("CCI", "RSI", "MA", "BullsPower", "BearsPower") else "medium", "HTF support slot -> force/permission"
    if slot == "anchor":
        if family in ("BB", "MA") and not sib:
            return "equilibrium", "medium", "price line on anchor -> equilibrium reference"
        if sib:
            other = max(s["period"] for s in sib)
            if period < other:
                return "velocity", "high", f"faster than sibling {family} {other} on anchor -> velocity"
            return "inertia", "high", f"slower than sibling {family} on anchor -> inertia"
        return "velocity", "medium", "single anchor oscillator -> velocity/timing"
    return "velocity", "low", "could not infer; treat as untrusted velocity (masked for tide)"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def normalize(spec: dict) -> dict:
    s = copy.deepcopy(spec)
    s.setdefault("version", "1.0")
    s.setdefault("status", "draft")
    s.setdefault("sets", [1, 2, 3, 4])
    s.setdefault("primary_set", 2)
    s.setdefault("release_window", 3)
    s.setdefault("launch_hold", 6)
    s.setdefault("allow_launch_entry", False)
    s.setdefault("adx_threshold", 20)
    s.setdefault("risk", {"stop": "opposite_tunnel_rail_or_swing", "risk_per_trade_pct": 0.5, "max_trades_per_day": 4})
    s.setdefault("principle_ids", [])
    s.setdefault("explanation", "")
    s.setdefault("evidence", [])
    if not s.get("id"):
        s["id"] = re.sub(r"[^a-z0-9]+", "_", s.get("name", "strategy").lower()).strip("_") or f"strategy_{int(time.time())}"
    sensors = s.get("sensors", [])
    for i, sn in enumerate(sensors):
        fam = FAMILY_ALIASES.get(str(sn.get("family", "")).lower(), sn.get("family"))
        sn["family"] = fam
        sn["period"] = int(sn.get("period") or 14)
        sn["shift"] = int(sn.get("shift") or 0)
        sn.setdefault("slot", "anchor")
        sn.setdefault("id", f"{fam}{sn['period']}{'+' + str(sn['shift']) if sn['shift'] else ''}_{sn['slot']}")
    ids = set()
    for sn in sensors:  # ensure unique ids
        base, k = sn["id"], 2
        while sn["id"] in ids:
            sn["id"] = f"{base}_{k}"; k += 1
        ids.add(sn["id"])
    for sn in sensors:
        if not sn.get("role"):
            role, conf, why = assign_role(sn["family"], sn["slot"], sn["period"], sensors)
            sn["role"], sn["role_confidence"], sn["role_why"] = role, conf, why
        else:
            sn.setdefault("role_confidence", "declared")
    return s


def validate(spec: dict) -> dict:
    """Run the doctrine logical forms that can be checked statically."""
    errors, warnings, checks = [], [], []
    sensors = spec.get("sensors", [])

    def check(name, ok, msg, hard=True):
        checks.append({"form": name, "ok": bool(ok), "msg": msg})
        if not ok:
            (errors if hard else warnings).append(f"{name}: {msg}")

    check("sets_immutable", all(int(x) in OFFICIAL_SETS for x in spec.get("sets", [])) and spec.get("primary_set") in OFFICIAL_SETS,
          "only official sets 1-4 are allowed")
    for sn in sensors:
        fam = sn.get("family")
        known = fam in FAMILIES
        check(f"allowed_universe[{sn['id']}]", known, f"{fam} is not in the MT5 allowed list")
        if known and not FAMILIES[fam][1]:
            warnings.append(f"{sn['id']}: {fam} is allowed but not computed by the lab yet (sensor will be inert)")
        check(f"assign_role[{sn['id']}]", sn.get("role") in ROLES, f"role {sn.get('role')} -> must be one of {ROLES}")
        check(f"slot[{sn['id']}]", sn.get("slot") in SLOTS, f"slot must be one of {SLOTS}")
        if sn.get("role") == "force" and sn.get("slot") == "anchor":
            check(f"ltf_never_votes_side[{sn['id']}]", False, "force must live on HTF support slots, not the LTF anchor")
        if sn.get("role") == "force" and sn.get("role_confidence") == "low":
            check(f"novel_never_defines_tide[{sn['id']}]", False, "low-confidence novel sensor cannot be force")
    roles = {sn.get("role") for sn in sensors}
    check("composition_valid", "force" in roles and "velocity" in roles, "needs >=1 force (HTF) and >=1 velocity (LTF) role")
    check("dual_period_tension", "inertia" in roles, "no anchor inertia sensor -> load vs collapse is judged by force only", hard=False)
    check("regime_gate_present", "regime_gate" in roles or any(s.get("family") == "Envelopes" for s in sensors),
          "no regime gate (ADX/tunnel) -> chop detection relies on tide only", hard=False)
    fam_slots = {}
    for sn in sensors:
        if sn.get("slot") == "anchor" and sn.get("role") in ("inertia", "velocity"):
            fam_slots.setdefault(sn["family"], {})[sn["role"]] = sn["period"]
    for fam, d in fam_slots.items():
        if "inertia" in d and "velocity" in d:
            check(f"speed_vs_weight[{fam}]", d["velocity"] < d["inertia"], "velocity period must be faster than inertia period")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "checks": checks, "checked_at": _now()}


# ---------------------------------------------------------------- natural-language parser (offline)

_TF_TO_SLOT_SET2 = {"5m": "anchor", "30m": "support1", "1h": "support2"}


def parse_strategy_text(text: str) -> dict | None:
    """Offline parser: 'add strategy NAME: CCI 100 on supports as force, CCI 30 on anchor as velocity, ADX 14 on anchor'."""
    m = re.search(r"(?:add|create|new)\s+(?:a\s+)?strategy\s*(?:called|named)?\s*([^:\n]*)[:\-]?\s*(.*)", text, re.I | re.S)
    if not m:
        return None
    name = m.group(1).strip().strip('"\'') or "Chat strategy"
    body = m.group(2)
    fam_pat = "|".join(sorted((re.escape(k) for k in FAMILY_ALIASES), key=len, reverse=True))
    pat = re.compile(rf"\b({fam_pat})\b\s*\(?\s*(\d+)?\s*\)?(?:\s*(?:shift|shifted|\+)\s*\+?(\d+))?"
                     rf"(?:\s*(?:on|@)\s*(?:the\s+)?(anchor|supports?|support\s*1|support\s*2|htf|ltf|1m|5m|15m|30m|1h|4h|1d))?"
                     rf"(?:\s*(?:as|=|->)\s*(?:the\s+)?({'|'.join(ROLES)}|gate|regime gate|volume))?", re.I)
    sensors = []
    for g in pat.finditer(body):
        fam = FAMILY_ALIASES[g.group(1).lower()]
        slot_raw = (g.group(4) or "anchor").lower().replace(" ", "")
        slot = {"anchor": "anchor", "ltf": "anchor", "support": "supports", "supports": "supports", "htf": "supports",
                "support1": "support1", "support2": "support2"}.get(slot_raw) or _TF_TO_SLOT_SET2.get(slot_raw, "anchor")
        role = (g.group(5) or "").lower().replace(" ", "_") or None
        role = {"gate": "regime_gate", "volume": "volume_confirm"}.get(role, role)
        sensors.append({"family": fam, "period": int(g.group(2) or 14), "shift": int(g.group(3) or 0), "slot": slot, "role": role})
    if not sensors:
        return None
    spec = {"name": name[:60], "sensors": sensors, "explanation": text.strip()[:500], "source": "chat_offline_parser"}
    if re.search(r"launch entr", text, re.I):
        spec["allow_launch_entry"] = True
    return normalize(spec)


# ---------------------------------------------------------------- registry

class Registry:
    """Versioned strategy store. Every save writes a new immutable version file."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _versions(self, sid: str) -> list[Path]:
        return sorted(self.root.glob(f"{sid}@*.json"), key=lambda p: [int(x) for x in p.stem.split("@")[1].split(".")])

    def list(self) -> list[dict]:
        ids = sorted({p.stem.split("@")[0] for p in self.root.glob("*@*.json")})
        out = []
        for sid in ids:
            latest = self.get(sid)
            out.append({"id": sid, "name": latest["name"], "version": latest["version"], "status": latest["status"],
                        "valid": latest.get("validation", {}).get("ok"), "versions": [p.stem.split("@")[1] for p in self._versions(sid)],
                        "parent": latest.get("parent")})
        return out

    def get(self, sid: str, version: str | None = None) -> dict:
        files = self._versions(sid)
        if not files:
            raise KeyError(sid)
        f = next((p for p in files if p.stem.split("@")[1] == version), None) if version else files[-1]
        if f is None:
            raise KeyError(f"{sid}@{version}")
        return json.loads(f.read_text())

    def save(self, spec: dict, bump: bool = True) -> dict:
        s = normalize(spec)
        files = self._versions(s["id"])
        if files and bump:
            major, minor = (int(x) for x in files[-1].stem.split("@")[1].split("."))
            s["version"] = f"{major}.{minor + 1}"
        s["validation"] = validate(s)
        if not s["validation"]["ok"] and s.get("status") == "active":
            s["status"] = "draft"
        s["saved_at"] = _now()
        (self.root / f"{s['id']}@{s['version']}.json").write_text(json.dumps(s, indent=2))
        return s

    def set_status(self, sid: str, status: str) -> dict:
        s = self.get(sid)
        if status == "active" and not s.get("validation", {}).get("ok"):
            raise ValueError("Strategy failed doctrine validation; fix it before activating.")
        s["status"] = status
        return self.save(s)

    def fork(self, sid: str, new_name: str) -> dict:
        s = self.get(sid)
        s = copy.deepcopy(s)
        s["parent"] = f"{sid}@{s['version']}"
        s["name"] = new_name
        s["id"] = re.sub(r"[^a-z0-9]+", "_", new_name.lower()).strip("_")
        s["version"] = "1.0"
        s["status"] = "draft"
        return self.save(s, bump=False)
