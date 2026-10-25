"""FastAPI backend for the Strategy Evolution Lab. Runs 100% locally: `python run.py`."""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:  # load .env before anything reads os.environ
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

from . import evaluator as ev
from . import llm
from .doctrine import Doctrine, Perception
from .lessons import Memory, make_lesson
from .market import ALL_TFS, DEFAULT_CONDITIONS, STORIES, STORY_HELP, AlpacaError, alpaca_configured, alpaca_market, synthetic_market
from .strategy import ACTIONS, OFFICIAL_SETS, REGIMES, ROLES, SLOTS, TOPOLOGIES, Registry, normalize, parse_strategy_text, validate
from .student import LLMStudent, OfflineStudent, llm_chat, principles_absorbed

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEB = ROOT / "web"
SEEDS = ROOT / "seeds" / "strategies"


class Lab:
    def __init__(self):
        DATA.mkdir(exist_ok=True)
        self.registry = Registry(DATA / "strategies")
        if not list((DATA / "strategies").glob("*.json")):
            for f in sorted(SEEDS.glob("*.json")):
                self.registry.save(json.loads(f.read_text()), bump=False)
        self.memory = Memory(DATA / "memory")
        self.cp_path = DATA / "checkpoints.json"
        self.checkpoints = json.loads(self.cp_path.read_text()) if self.cp_path.exists() else []
        self.chat_history: list[dict] = []
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        lst = self.registry.list()
        act = next((s for s in lst if s["status"] == "active"), lst[0] if lst else None)
        self.strategy = self.registry.get(act["id"]) if act else None
        self.market = None
        self.market_req = {"source": "synthetic", "conditions": dict(DEFAULT_CONDITIONS)}
        self.build_market()
        self.last_llm: dict | None = None

    def build_market(self, req: dict | None = None):
        req = req or self.market_req
        if req.get("source") == "alpaca":
            m = alpaca_market(req.get("symbol", "SPY"), anchor_tf=OFFICIAL_SETS[int(req.get("set_id", 2))]["anchor"])
        else:
            m = synthetic_market(req.get("conditions"))
        with self.lock:
            self.market, self.market_req = m, req
            self.perception = Perception(m, self.strategy)
            self.doctrine = Doctrine(self.perception)
            self.marker_cache: dict = {}

    def set_strategy(self, sid: str, version: str | None = None):
        with self.lock:
            self.strategy = self.registry.get(sid, version)
            self.perception = Perception(self.market, self.strategy)
            self.doctrine = Doctrine(self.perception)
            self.marker_cache = {}

    def save_cps(self):
        self.cp_path.write_text(json.dumps(_clean(self.checkpoints), indent=1))


LAB: Lab | None = None


def lab() -> Lab:
    global LAB
    if LAB is None:
        LAB = Lab()
    return LAB


app = FastAPI(title="Vizual NN — Strategy Evolution Lab")


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# ---------------------------------------------------------------- models

class FrameReq(BaseModel):
    t: float | None = None
    step: int | None = None
    set_id: int = 2
    finish: dict = {}
    overrides: dict | None = None
    window: int = 120


class MarketReq(BaseModel):
    source: str = "synthetic"
    conditions: dict | None = None
    symbol: str | None = None
    set_id: int = 2


class LessonReq(BaseModel):
    t: float
    set_id: int = 2
    finish: dict = {}
    overrides: dict | None = None
    labels: dict | None = None  # override doctrine labels with Mark's correction
    note: str = ""
    student: dict | None = None


class ChatReq(BaseModel):
    message: str
    t: float | None = None
    set_id: int = 2
    finish: dict = {}
    use_llm: bool = True


class AskReq(BaseModel):
    t: float
    set_id: int = 2
    finish: dict = {}
    overrides: dict | None = None
    probe: bool = False


class SpecReq(BaseModel):
    spec: dict


# ---------------------------------------------------------------- helpers

def _finish(d: dict) -> dict:
    return {**ev.DEFAULT_FINISH, **{k: float(v) for k, v in (d or {}).items() if v is not None and v != ""}}


def _anchor_times(L: Lab, set_id: int) -> np.ndarray:
    a = L.market.bars[OFFICIAL_SETS[set_id]["anchor"]]
    i0, i1 = a.index_at(L.market.replay_start), a.index_at(L.market.replay_end)
    return a.t_close[max(0, i0):i1 + 1]


def _cursor(L: Lab, req) -> float:
    ts = _anchor_times(L, req.set_id)
    if req.step is not None:
        return float(ts[max(0, min(len(ts) - 1, req.step))])
    return float(req.t if req.t is not None else ts[-1])


def _chart(L: Lab, set_id: int, t: float, window: int, fin: dict) -> dict:
    tf = OFFICIAL_SETS[set_id]["anchor"]
    a = L.market.bars[tf]
    i = a.index_at(t)
    lo = max(0, i - window + 1)
    sl = slice(lo, i + 1)
    out = {"tf": tf, "t": a.t_close[sl].tolist(), "o": a.o[sl].tolist(), "h": a.h[sl].tolist(), "l": a.l[sl].tolist(), "c": a.c[sl].tolist(),
           "overlays": [], "oscillators": [], "markers": []}
    for sn in L.strategy["sensors"]:
        key = (sn["id"], tf)
        if key not in L.perception.cache:
            continue
        arr = L.perception.cache[key]
        if sn["family"] in ("Envelopes", "BB") and arr["extra"]:
            out["overlays"].append({"id": sn["id"], "kind": "band", "upper": arr["extra"]["upper"][sl].tolist(), "lower": arr["extra"]["lower"][sl].tolist()})
        elif sn["family"] == "MA":
            out["overlays"].append({"id": sn["id"], "kind": "line", "v": arr["value"][sl].tolist()})
        elif sn["role"] in ("velocity", "inertia", "force") and sn["family"] not in ("Envelopes", "MA", "BB"):
            out["oscillators"].append({"id": sn["id"], "role": sn["role"], "family": sn["family"], "v": arr["value"][sl].tolist()})
    # doctrine act markers over the visible window (cached)
    ck = (L.strategy["id"], L.strategy["version"], set_id, json.dumps(fin, sort_keys=True))
    cache = L.marker_cache.setdefault(ck, {})
    for j in range(lo, i + 1):
        if j not in cache:
            r = L.doctrine.evaluate_set(set_id, float(a.t_close[j]), fin)
            cache[j] = (r["topology"], r["act"])
        topo, act = cache[j]
        if act.startswith("fire") or act in ("kill", "wait_loaded"):
            out["markers"].append({"k": j - lo, "act": act, "topology": topo})
    return out


def _predict_offline(memory: dict | None, fs: dict) -> dict | None:
    if memory is None:
        return None
    return OfflineStudent(memory).predict(fs)


# ---------------------------------------------------------------- routes

@app.get("/api/state")
def state():
    L = lab()
    cfg = llm.config()
    ts = _anchor_times(L, 2)
    return _clean({
        "strategies": L.registry.list(), "strategy": L.strategy,
        "market": {"source": L.market.source, "symbol": L.market.symbol, "request": L.market_req, "replay_len": len(ts)},
        "conditions": DEFAULT_CONDITIONS, "stories": STORY_HELP, "sets": OFFICIAL_SETS,
        "vocab": {"roles": ROLES, "slots": SLOTS, "topologies": TOPOLOGIES, "actions": ACTIONS, "regimes": REGIMES, "tfs": ALL_TFS},
        "llm": {"provider": cfg["provider"], "model": cfg["model"], "ready": cfg["ready"]},
        "alpaca": {"configured": alpaca_configured()},
        "memory": {"candidate_lessons": len(L.memory.candidate["lessons"]), "candidate_version": L.memory.candidate["version"],
                   "approved_lessons": None if L.memory.approved is None else len(L.memory.approved["lessons"]),
                   "weights": L.memory.candidate["weights"], "principles": principles_absorbed(L.memory.candidate)},
        "checkpoints": L.checkpoints, "gates": ev.GATES,
    })


@app.post("/api/market")
def set_market(req: MarketReq):
    L = lab()
    try:
        if req.source == "alpaca":
            L.build_market({"source": "alpaca", "symbol": (req.symbol or "SPY").upper(), "set_id": req.set_id})
        else:
            L.build_market({"source": "synthetic", "conditions": {**DEFAULT_CONDITIONS, **(req.conditions or {})}})
    except AlpacaError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "source": L.market.source, "symbol": L.market.symbol, "replay_len": len(_anchor_times(L, req.set_id))}


@app.post("/api/frame")
def frame(req: FrameReq):
    L = lab()
    with L.lock:
        t = _cursor(L, req)
        fin = _finish(req.finish)
        d = L.doctrine.evaluate(t, fin, req.set_id, overrides=req.overrides)
        prim = d["sets"][req.set_id]
        cand = _predict_offline(L.memory.candidate, prim)
        appr = _predict_offline(L.memory.approved, prim)
        set_rows = {}
        for sid, s in d["sets"].items():
            st = _predict_offline(L.memory.candidate, s)
            set_rows[sid] = {"tide": s["tide"], "regime": s["regime"], "topology": s["topology"], "act": s["act"], "wait_subtype": s["wait_subtype"],
                             "anchor": s["anchor"], "supports": s["supports"], "student_act": st["act"], "student_topology": st["topology"],
                             "force": [{"iid": r["iid"], "side": r["side"], "value": r["value"]} for r in s["readings"] if r["role"] == "force"]}
        ts = _anchor_times(L, req.set_id)
        return _clean({
            "t": t, "step": int(np.searchsorted(ts, t)), "replay_len": len(ts),
            "doctrine": {**{k: prim[k] for k in ("tide", "regime", "topology", "act", "wait_subtype", "chain", "relations", "principle_ids",
                                                 "composition_valid", "features", "readings", "set_id", "anchor", "supports")},
                         "influence": d["influence"], "consensus": d["consensus"], "conviction": d["conviction"], "size_feel": d["size_feel"]},
            "student": cand, "approved": appr, "sets": set_rows, "chart": _chart(L, req.set_id, t, req.window, fin), "finish": fin,
            "strategy": {"id": L.strategy["id"], "version": L.strategy["version"], "name": L.strategy["name"]},
        })


@app.post("/api/student/ask")
def ask(req: AskReq):
    """Ask the LLM student to read the current frame (one model call; probe = one extra call per sensor)."""
    L = lab()
    t = req.t
    fin = _finish(req.finish)
    prim = L.doctrine.evaluate_set(req.set_id, t, fin, overrides=req.overrides)
    if not llm.config()["ready"]:
        p = OfflineStudent(L.memory.candidate).predict(prim)
        p["note"] = "LLM not configured; this is the offline lesson-memory student."
        return _clean(p)
    stud = LLMStudent(L.memory.candidate)
    try:
        p = stud.predict(prim, fin, L.strategy)
        if req.probe:
            p["measured_attention"] = stud.probe(prim, fin, L.strategy, p)
    except llm.LLMError as e:
        raise HTTPException(502, str(e)) from e
    p["t"] = t
    L.last_llm = p
    return _clean(p)


@app.post("/api/lesson")
def add_lesson(req: LessonReq):
    L = lab()
    fin = _finish(req.finish)
    prim = L.doctrine.evaluate_set(req.set_id, req.t, fin, overrides=req.overrides)
    labels = {k: prim[k] for k in ("tide", "regime", "topology", "act", "wait_subtype", "principle_ids", "relations")}
    doctrine_labels = dict(labels)
    if req.labels:
        labels.update({k: v for k, v in req.labels.items() if v not in (None, "")})
        if "topology" in req.labels or "act" in req.labels:
            labels.pop("principle_ids", None) if req.labels.get("topology") != doctrine_labels["topology"] else None
    try:
        les = make_lesson(prim, labels, L.strategy, source="mark_correction" if req.labels else "mark_confirm", note=req.note,
                          student=req.student, doctrine=doctrine_labels)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    L.memory.add(les)
    return _clean({"lesson": les, "lessons": len(L.memory.candidate["lessons"]), "principles": principles_absorbed(L.memory.candidate)})


@app.get("/api/lessons")
def lessons():
    L = lab()
    return _clean({"candidate": L.memory.candidate["lessons"][::-1], "weights": L.memory.candidate["weights"],
                   "approved_count": None if L.memory.approved is None else len(L.memory.approved["lessons"])})


@app.delete("/api/lessons/{lesson_id}")
def del_lesson(lesson_id: str):
    lab().memory.remove(lesson_id)
    return {"ok": True}


@app.post("/api/lessons/reset")
def reset_lessons():
    lab().memory.reset()
    return {"ok": True}


def _frame_summary(L: Lab, t: float | None, set_id: int, fin: dict) -> tuple[str, dict | None]:
    if t is None:
        return "(no frame)", None
    from .student import observation_text
    prim = L.doctrine.evaluate_set(set_id, t, fin)
    return observation_text(prim, fin, L.strategy) + f"\nDoctrine teacher reads: tide={prim['tide']} regime={prim['regime']} topology={prim['topology']} act={prim['act']}", prim


@app.post("/api/chat")
def chat(req: ChatReq):
    L = lab()
    fin = _finish(req.finish)
    summary, prim = _frame_summary(L, req.t, req.set_id, fin)
    out: dict = {"student": "offline", "intent": "chat"}
    cfg = llm.config()
    if req.use_llm and cfg["ready"]:
        try:
            js = llm_chat(req.message, L.chat_history, summary, L.registry.list(), L.memory.candidate)
        except llm.LLMError as e:
            raise HTTPException(502, str(e)) from e
        out.update(js)
        out["student"] = "llm"
        L.chat_history += [{"role": "user", "content": req.message}, {"role": "assistant", "content": js.get("reply", "")}]
    else:
        spec = parse_strategy_text(req.message)
        if spec:
            out.update(intent="add_strategy", strategy_spec=spec,
                       reply=f"Parsed '{spec['name']}' with {len(spec['sensors'])} sensors. Review the validator result, then activate it.",
                       thinking=[f"{s['family']}{s['period']} on {s['slot']} -> {s['role']} ({s.get('role_confidence')}: {s.get('role_why', 'declared')})" for s in spec["sensors"]])
        else:
            msg = req.message.lower()
            corr = None
            for word, topo in (("load", "slingshot_load"), ("pullback", "slingshot_load"), ("release", "slingshot_release"),
                               ("launch", "launch"), ("collapse", "collapse"), ("reversal", "collapse"), ("chop", "chop")):
                if word in msg and any(x in msg for x in ("this is", "it's", "its", "should be", "not a", "wrong")):
                    corr = {"layer": "topology", "topology": topo}
                    break
            if "heat" in msg and corr is None:
                corr = {"layer": "wait_subtype", "act": "wait_no_trade", "wait_subtype": "heat"}
            if corr:
                corr["note"] = req.message
                out.update(intent="correction", correction=corr, reply="Understood. Press 'Save lesson' to teach me this correction on the current frame.")
            elif prim is not None:
                st = OfflineStudent(L.memory.candidate).predict(prim)
                out.update(intent="explain", reply=" ".join(x["thought"] for x in st["thinking"]), thinking=[x["thought"] for x in st["thinking"]],
                           note="Offline student. Configure an LLM in .env to talk to a real language model.")
            else:
                out.update(reply="Offline mode: say 'add strategy NAME: CCI 100 on supports as force, CCI 30 on anchor as velocity'.")
    spec = out.get("strategy_spec")
    if isinstance(spec, dict) and spec.get("sensors"):
        spec = normalize({**spec, "source": spec.get("source", "chat_llm" if out["student"] == "llm" else "chat_offline_parser")})
        spec["validation"] = validate(spec)
        out["strategy_spec"] = spec
    return _clean(out)


@app.get("/api/strategies")
def strategies():
    return lab().registry.list()


@app.get("/api/strategies/{sid}")
def get_strategy(sid: str, version: str | None = None):
    try:
        return lab().registry.get(sid, version)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/api/strategies/validate")
def validate_spec(req: SpecReq):
    s = normalize(req.spec)
    return {"spec": s, "validation": validate(s)}


@app.post("/api/strategies")
def save_strategy(req: SpecReq):
    L = lab()
    s = L.registry.save(req.spec)
    return s


@app.post("/api/strategies/{sid}/{action}")
def strategy_action(sid: str, action: str, name: str | None = None):
    L = lab()
    try:
        if action == "select":
            L.set_strategy(sid)
            return {"ok": True, "strategy": L.strategy}
        if action == "activate":
            s = L.registry.set_status(sid, "active")
            L.set_strategy(sid)
            return {"ok": True, "strategy": s}
        if action == "archive":
            return {"ok": True, "strategy": L.registry.set_status(sid, "archived")}
        if action == "fork":
            return {"ok": True, "strategy": L.registry.fork(sid, name or f"{sid} fork")}
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    raise HTTPException(404, "unknown action")


# ---------------------------------------------------------------- evolution jobs

def _job(fn, *a):
    jid = uuid.uuid4().hex[:8]
    L = lab()
    L.jobs[jid] = {"id": jid, "status": "running", "progress": 0.0, "result": None, "error": None, "started": time.time()}

    def prog(p):
        L.jobs[jid]["progress"] = round(p, 3)

    def run():
        try:
            L.jobs[jid]["result"] = _clean(fn(prog, *a))
            L.jobs[jid]["status"] = "done"
        except Exception as e:  # noqa: BLE001
            L.jobs[jid].update(status="error", error=f"{e}\n{traceback.format_exc()[-800:]}")
    threading.Thread(target=run, daemon=True).start()
    return {"job": jid}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = lab().jobs.get(jid)
    if not j:
        raise HTTPException(404, "no job")
    return j


def _student(kind: str, memory: dict):
    return LLMStudent(memory) if kind == "llm" else OfflineStudent(memory)


def _checkpoint(prog, kind: str, llm_limit: int, survival_days: int, note: str = ""):
    L = lab()
    strat = L.strategy
    packs = {}
    for i, k in enumerate(("train", "heldout", "transfer")):
        packs[k] = ev.build_pack(strat, k, cache_dir=DATA / "packs")
        prog(0.1 + 0.15 * i)
    mem = json.loads(json.dumps(L.memory.candidate))
    stud = _student(kind, mem)
    limit = llm_limit if kind == "llm" else None
    cp = {"id": f"cp{len(L.checkpoints) + 1:03d}", "created": time.strftime("%Y-%m-%d %H:%M:%S"), "student": kind,
          "model": llm.config()["model"] if kind == "llm" else "offline-lesson-memory",
          "strategy": f"{strat['id']}@{strat['version']}", "lessons": len(mem["lessons"]), "memory_version": mem["version"], "note": note}
    cp["train"] = ev.score(stud, packs["train"], strategy=strat, limit=limit); prog(0.6)
    cp["heldout"] = ev.score(stud, packs["heldout"], strategy=strat, limit=limit); prog(0.7)
    cp["transfer"] = ev.score(stud, packs["transfer"], strategy=ev.transfer_strategy(strat), limit=limit); prog(0.8)
    cp["retention"] = ev.retention(stud, mem, strategy=strat, limit=llm_limit if kind == "llm" else 40)
    if survival_days and kind != "llm":
        cp["survival"] = ev.survival("candidate", strat, mem, days=survival_days, progress=lambda p: prog(0.8 + 0.2 * p))
        cp["survival"].pop("daily", None) if survival_days > 150 else None
    cp["gates"] = ev.gates(cp)
    cp["promotable"] = all(g["ok"] for g in cp["gates"])
    cp["memory_snapshot"] = mem
    L.checkpoints.append(cp)
    L.save_cps()
    prog(1.0)
    return {k: v for k, v in cp.items() if k != "memory_snapshot"}


class CheckpointReq(BaseModel):
    student: str = "offline"
    llm_limit: int = 12
    survival_days: int = 100
    note: str = ""


@app.post("/api/evolve/checkpoint")
def checkpoint(req: CheckpointReq):
    if req.student == "llm" and not llm.config()["ready"]:
        raise HTTPException(400, "LLM not configured")
    return _job(_checkpoint, req.student, req.llm_limit, req.survival_days, req.note)


class TeachReq(BaseModel):
    k: int = 5
    student: str = "offline"
    then_checkpoint: bool = True


@app.post("/api/evolve/auto_teach")
def auto_teach(req: TeachReq):
    def run(prog):
        L = lab()
        pack = ev.build_pack(L.strategy, "train", cache_dir=DATA / "packs")
        prog(0.2)
        stud = _student(req.student, L.memory.candidate)
        new = ev.auto_teach(stud, pack, L.strategy, L.memory, k=req.k)
        prog(0.4)
        cp = _checkpoint(lambda p: prog(0.4 + 0.6 * p), "offline", 12, 100, note=f"auto-teach +{len(new)}") if req.then_checkpoint else None
        return {"new_lessons": new, "checkpoint": cp}
    return _job(run)


@app.post("/api/evolve/promote/{cp_id}")
def promote(cp_id: str):
    L = lab()
    cp = next((c for c in L.checkpoints if c["id"] == cp_id), None)
    if not cp:
        raise HTTPException(404, "no checkpoint")
    if not cp.get("promotable"):
        raise HTTPException(400, "Checkpoint did not pass every promotion gate. The approved student stays frozen.")
    L.memory.approved = json.loads(json.dumps(cp["memory_snapshot"]))
    L.memory.save()
    for c in L.checkpoints:
        c["approved"] = c["id"] == cp_id
    L.save_cps()
    return {"ok": True, "approved": cp_id}


@app.get("/api/evolve/checkpoints")
def checkpoints():
    return [{k: v for k, v in c.items() if k != "memory_snapshot"} for c in lab().checkpoints]


# ---------------------------------------------------------------- static UI

app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
