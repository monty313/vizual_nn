import json
from pathlib import Path

from lab import evaluator as ev
from lab.doctrine import Doctrine, Perception
from lab.lessons import Memory, make_lesson
from lab.market import DEFAULT_CONDITIONS, synthetic_market
from lab.strategy import normalize
from lab.student import OfflineStudent

SEED = Path(__file__).resolve().parent.parent / "seeds" / "strategies" / "dual_cci_slingshot.json"
FIN = ev.DEFAULT_FINISH


def _doctrine(story="pullback_resume"):
    strat = normalize(json.loads(SEED.read_text()))
    m = synthetic_market({**DEFAULT_CONDITIONS, "story": story})
    return strat, m, Doctrine(Perception(m, strat))


def _times(m, tf="5m"):
    a = m.bars[tf]
    i0, i1 = a.index_at(m.replay_start), a.index_at(m.replay_end)
    return a.t_close[i0:i1 + 1]


def test_chain_order_and_no_trade_against_tide():
    strat, m, d = _doctrine()
    seen = set()
    for t in _times(m)[::3]:
        r = d.evaluate_set(2, float(t), FIN)
        assert [c["step"] for c in r["chain"]] == ["tide", "regime", "breath_launch", "act", "finish"]
        if r["act"] == "fire_buy":
            assert r["tide"] == "long_only"
        if r["act"] == "fire_sell":
            assert r["tide"] == "short_only"
        seen.add(r["topology"])
    assert "slingshot_load" in seen  # pullback is recognized as load, not reversal


def test_reversal_story_produces_collapse():
    strat, m, d = _doctrine("reversal")
    topos = {d.evaluate_set(2, float(t), FIN)["topology"] for t in _times(m)[::2]}
    assert "collapse" in topos or "chop" in topos


def test_lesson_is_principle_application(tmp_path):
    strat, m, d = _doctrine()
    t = float(_times(m)[len(_times(m)) // 2])
    r = d.evaluate_set(2, t, FIN)
    L = make_lesson(r, {k: r[k] for k in ("tide", "regime", "topology", "act", "wait_subtype")}, strat, source="test")
    assert L["lesson_type"] == "principle_application" and L["not"] == "copy_answer" and L["principle_ids"]
    mem = Memory(tmp_path)
    mem.add(L)
    p = OfflineStudent(mem.candidate).predict(r)
    assert p["mode"] in ("recall", "generalize") and p["topology"] == r["topology"]


def test_auto_teach_improves_heldout(tmp_path):
    strat = normalize(json.loads(SEED.read_text()))
    train = ev.build_pack(strat, "train", cache_dir=tmp_path)
    held = ev.build_pack(strat, "heldout", cache_dir=tmp_path)
    mem = Memory(tmp_path / "mem")
    base = ev.score(OfflineStudent(mem.candidate), held, strategy=strat)["topology"]
    for _ in range(2):
        ev.auto_teach(OfflineStudent(mem.candidate), train, strat, mem, k=4)
    after = ev.score(OfflineStudent(mem.candidate), held, strategy=strat)["topology"]
    assert after > base
