"""LLM student path with a stubbed model (no network)."""
import json

from fastapi.testclient import TestClient

from lab import llm
from lab.server import app


def _fake_chat(system, messages, **kw):
    user = messages[-1]["content"]
    if "intent" in user or "add_strategy" in system + user:
        return json.dumps({"reply": "Added.", "intent": "add_strategy", "thinking": ["map roles"],
                           "strategy_spec": {"name": "LLM Stoch", "sensors": [
                               {"family": "Stochastic", "period": 50, "slot": "supports", "role": "force"},
                               {"family": "Stochastic", "period": 14, "slot": "anchor", "role": "velocity"}]}}), {"model": "stub", "provider": "stub", "latency_s": 0}
    return json.dumps({"thinking": [{"step": "tide", "thought": "HTF force up"}], "tide": "long_only", "regime": "bull_trend",
                       "topology": "slingshot_load", "act": "wait_loaded", "wait_subtype": "loaded",
                       "attention": {"cci100_supports": 2, "cci30_anchor": 1}, "confidence": 0.7}), {"model": "stub", "provider": "stub", "latency_s": 0}


def test_llm_student_and_chat(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(llm, "chat", _fake_chat)
    import lab.student as st
    monkeypatch.setattr(st.llm, "chat", _fake_chat)
    c = TestClient(app)
    fr = c.post("/api/frame", json={"step": 100, "set_id": 2}).json()
    r = c.post("/api/student/ask", json={"t": fr["t"], "set_id": 2, "probe": True}).json()
    assert r["student"] == "llm" and abs(sum(r["attention"].values()) - 1) < 0.01
    assert "measured_attention" in r
    ch = c.post("/api/chat", json={"message": "add a stochastic slingshot", "t": fr["t"]}).json()
    assert ch["student"] == "llm"
