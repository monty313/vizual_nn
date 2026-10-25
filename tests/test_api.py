from fastapi.testclient import TestClient

from lab.server import app

c = TestClient(app)


def test_state_and_frame():
    st = c.get("/api/state").json()
    assert set(st["sets"]) == {"1", "2", "3", "4"}
    fr = c.post("/api/frame", json={"step": 50, "set_id": 2}).json()
    assert fr["doctrine"]["chain"][0]["step"] == "tide"
    assert fr["chart"]["c"] and "influence" in fr["doctrine"]


def test_chat_offline_add_strategy_and_validate():
    r = c.post("/api/chat", json={"message": "add strategy Api Test: CCI 100 on supports as force, CCI 30 on anchor as velocity", "use_llm": False}).json()
    assert r["intent"] == "add_strategy" and r["strategy_spec"]["validation"]["ok"]


def test_lesson_roundtrip():
    fr = c.post("/api/frame", json={"step": 80, "set_id": 2}).json()
    r = c.post("/api/lesson", json={"t": fr["t"], "set_id": 2, "note": "test"}).json()
    lid = r["lesson"]["lesson_id"]
    assert c.delete(f"/api/lessons/{lid}").json()["ok"]


def test_index_served():
    assert "VIZUAL NN" in c.get("/").text
