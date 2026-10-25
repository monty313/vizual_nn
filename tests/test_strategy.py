import json
from pathlib import Path

from lab.strategy import OFFICIAL_SETS, assign_role, normalize, parse_strategy_text, validate

SEEDS = Path(__file__).resolve().parent.parent / "seeds" / "strategies"


def test_official_sets_are_immutable_law():
    assert OFFICIAL_SETS[1]["anchor"] == "1m" and OFFICIAL_SETS[1]["supports"] == ["15m", "30m"]
    assert OFFICIAL_SETS[2]["anchor"] == "5m" and OFFICIAL_SETS[2]["supports"] == ["30m", "1h"]
    assert OFFICIAL_SETS[3]["anchor"] == "15m" and OFFICIAL_SETS[3]["supports"] == ["1h", "4h"]
    assert OFFICIAL_SETS[4]["anchor"] == "30m" and OFFICIAL_SETS[4]["supports"] == ["4h", "1d"]


def test_seed_strategies_validate():
    for f in SEEDS.glob("*.json"):
        v = validate(normalize(json.loads(f.read_text())))
        assert v["ok"], (f.name, v["errors"])


def test_lone_indicator_rejected():
    v = validate(normalize({"name": "lone", "sensors": [{"family": "CCI", "period": 30, "slot": "anchor", "role": "velocity"}]}))
    assert not v["ok"]


def test_non_mt5_indicator_rejected():
    v = validate(normalize({"name": "bad", "sensors": [
        {"family": "VWAP", "period": 20, "slot": "supports", "role": "force"},
        {"family": "CCI", "period": 30, "slot": "anchor", "role": "velocity"}]}))
    assert not v["ok"]


def test_novel_sensor_gets_role_zero_shot():
    role, conf, why = assign_role("DeMarker", "supports", 50)
    assert role in ("force", "inertia") and why


def test_offline_parser():
    s = parse_strategy_text("add strategy Test Sling: CCI 100 on supports as force, CCI 30 on anchor as velocity, ADX 14 on anchor as regime_gate")
    assert s and s["name"].lower().startswith("test sling") and len(s["sensors"]) == 3
    assert validate(normalize(s))["ok"]


def test_every_implemented_oscillator_produces_values():
    import numpy as np
    from lab import indicators as ind
    rng = np.random.default_rng(1)
    c = np.cumsum(rng.standard_normal(600)) + 100
    h, l = c + 1, c - 1
    for arr in (ind.stochastic(h, l, c, 14), ind.cci(h, l, c, 30), ind.rsi(c, 14), ind.wpr(h, l, c, 14), ind.sma(c, 20)):
        assert np.isfinite(arr[-50:]).all()
