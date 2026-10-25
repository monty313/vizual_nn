"""principle_application lessons and the student's lesson memory (candidate vs frozen approved)."""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path

from .strategy import PRINCIPLES

KEY_FEATURES = ["tide_state", "support_force", "G", "regime_gate", "expansion", "inertia", "velocity",
                "recent_load", "velocity_hold", "heat", "goal"]


def relational_key(fx: dict) -> dict:
    """Mirror-invariant relational key: long and short cases share one principle."""
    flat = fx["tide"] == "flat"
    return {
        "tide_state": "flat" if flat else "set",
        "support_force": fx["support_force"], "G": fx["G"], "regime_gate": fx["regime_gate"], "expansion": fx["expansion"],
        "inertia": "n/a" if flat else fx["inertia"], "velocity": "n/a" if flat else fx["velocity"],
        "recent_load": bool(fx["recent_load"]) and not flat, "velocity_hold": bool(fx["velocity_hold"]) and not flat,
        "heat": fx["heat"], "goal": fx["goal"],
    }


def act_to_rel(act: str, tide: str) -> str:
    if act in ("fire_buy", "fire_sell"):
        want = "fire_buy" if tide == "long_only" else "fire_sell" if tide == "short_only" else None
        return "fire_with_tide" if act == want else "fire_against_tide"
    return act


def rel_to_act(rel: str, tide: str) -> str:
    if rel == "fire_with_tide":
        return "fire_buy" if tide == "long_only" else "fire_sell" if tide == "short_only" else "wait_no_trade"
    if rel == "fire_against_tide":
        return "fire_sell" if tide == "long_only" else "fire_buy" if tide == "short_only" else "wait_no_trade"
    return rel


def make_lesson(frame_set: dict, labels: dict, strategy: dict, source: str, note: str = "", student: dict | None = None,
                doctrine: dict | None = None) -> dict:
    fx = frame_set["features"]
    topo = labels["topology"]
    act = labels["act"]
    key = "heat" if labels.get("wait_subtype") == "heat" else "goal" if act == "bank" else topo
    pids = labels.get("principle_ids") or PRINCIPLES.get(key, [])
    L = {
        "lesson_id": f"L-{int(time.time()) % 1_000_000:06d}{uuid.uuid4().hex[:4]}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "lesson_type": "principle_application", "not": "copy_answer", "source": source,
        "strategy": f"{strategy['id']}@{strategy['version']}", "set_id": frame_set["set_id"],
        "sensors": [{k: r[k] for k in ("sensor_id", "family", "period", "shift", "tf", "role", "side", "value")} for r in frame_set["readings"]],
        "features": {k: v for k, v in fx.items()}, "key": relational_key(fx),
        "relations": labels.get("relations") or frame_set.get("relations", []),
        "tide": labels.get("tide", fx["tide"]), "regime": labels.get("regime", frame_set.get("regime")),
        "topology": topo, "act": act, "act_rel": act_to_rel(act, labels.get("tide", fx["tide"])),
        "wait_subtype": labels.get("wait_subtype"), "principle_ids": pids,
        "goal_link": labels.get("goal_link") or {
            "slingshot_load": "Preserve risk capacity until velocity resumes with tide.",
            "slingshot_release": "Spend risk only when velocity resumes inside force.",
            "launch": "Ride what is working; do not chase a fresh entry.",
            "collapse": "Protect the floor: force left, so the idea is dead.",
            "chop": "No tide, no edge: keep dry powder for the finish line."}.get(topo, "Protect the floor and the finish line."),
        "forward_note": labels.get("forward_note") or "Test the same relation with another allowed velocity family (CCI<->RSI<->Stoch).",
        "note": note,
    }
    if student:
        L["correction"] = {"student_said": {k: student.get(k) for k in ("tide", "regime", "topology", "act", "wait_subtype")}}
    if doctrine:
        diff = [k for k in ("tide", "topology", "act", "wait_subtype") if doctrine.get(k) != L.get(k)]
        L["conflicts_with_doctrine"] = diff
    ok, why = lesson_valid(L)
    if not ok:
        raise ValueError(why)
    return L


def lesson_valid(L: dict) -> tuple[bool, str]:
    if L.get("lesson_type") != "principle_application":
        return False, "learn_not_copy: lesson_type must be principle_application"
    for k in ("topology", "relations", "principle_ids", "act"):
        if not L.get(k):
            return False, f"lesson missing {k} (act-only lessons are copying)"
    return True, ""


class Memory:
    """Lesson memory. candidate learns; approved is a frozen snapshot that only changes on promotion."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cand_path = self.root / "candidate_memory.json"
        self.appr_path = self.root / "approved_memory.json"
        self.candidate = self._load(self.cand_path)
        self.approved = self._load(self.appr_path) if self.appr_path.exists() else None

    @staticmethod
    def _load(p: Path) -> dict:
        if p.exists():
            return json.loads(p.read_text())
        return {"lessons": [], "weights": {f: 1.0 for f in KEY_FEATURES}, "version": 0}

    def save(self):
        self.cand_path.write_text(json.dumps(self.candidate, indent=1))
        if self.approved is not None:
            self.appr_path.write_text(json.dumps(self.approved, indent=1))

    def add(self, L: dict) -> dict:
        mem = self.candidate
        # learn feature weights: features that separate this lesson from a differently-labelled neighbour matter more
        for other in mem["lessons"]:
            if (other["topology"], other["act_rel"]) == (L["topology"], L["act_rel"]):
                continue
            diff = [f for f in KEY_FEATURES if other["key"].get(f) != L["key"].get(f)]
            if 0 < len(diff) <= 2:
                for f in diff:
                    mem["weights"][f] = round(mem["weights"].get(f, 1.0) + 1.0 / len(diff), 3)
        # replace an identical-key lesson (newest teaching wins) to keep memory coherent
        mem["lessons"] = [x for x in mem["lessons"] if x["key"] != L["key"]] + [L]
        mem["version"] += 1
        self.save()
        return L

    def remove(self, lesson_id: str):
        self.candidate["lessons"] = [x for x in self.candidate["lessons"] if x["lesson_id"] != lesson_id]
        self.candidate["version"] += 1
        self.save()

    def reset(self):
        self.candidate = {"lessons": [], "weights": {f: 1.0 for f in KEY_FEATURES}, "version": 0}
        self.save()

    def promote(self):
        self.approved = copy.deepcopy(self.candidate)
        self.save()
