"""Market sources: controllable synthetic generator and read-only Alpaca market data.

Both sources produce the same structure — {tf: Bars} — so the doctrine evaluator and the
student see one pipeline ("one mind all day"). Higher-timeframe values at a cursor time are
read only from COMPLETED bars (no look-ahead).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
ALL_TFS = list(TF_MIN)


@dataclass
class Bars:
    tf: str
    t_close: np.ndarray  # minutes (synthetic: from 0; alpaca: epoch minutes)
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray

    def __len__(self) -> int:
        return len(self.c)

    def index_at(self, t: float) -> int:
        """Index of the last bar that has closed at or before time t (-1 if none)."""
        return int(np.searchsorted(self.t_close, t, side="right")) - 1


@dataclass
class Market:
    source: str
    symbol: str
    bars: dict[str, Bars]
    replay_start: float  # cursor time where the replay window starts
    replay_end: float
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------- synthetic

STORIES = {
    # segments: (length, drift_multiplier_relative_to_trend, vol_multiplier, mean_revert)
    # length: hours (number) | "pb" = pullback_hours | "rest" = whatever is left of the tail
    "pullback_resume": [("rest", 1.0, 1.0, 0), ("pb", "pull", 1.0, 0), (8, 2.2, 1.0, 0)],
    "pullback_hold": [("rest", 1.0, 1.0, 0), ("pb", "pull", 1.0, 0), (5, 0.0, 0.7, 1)],
    "launch": [("rest", 1.0, 1.0, 0), (14, 3.0, 1.1, 0)],
    "reversal": [(8, 1.0, 1.0, 0), ("rest", -4.5, 1.2, 0)],
    "chop": [("rest", 0.0, 0.8, 1)],
    "vol_shock": [("rest", 1.0, 1.0, 0), (3, -1.0, 4.0, 0), (8, 0.5, 2.0, 0)],
}
STORY_HELP = {
    "pullback_resume": "Bread and butter: HTF trend, LTF pullback (load), then resume with tide (release).",
    "pullback_hold": "Pullback that stalls: load that never releases.",
    "launch": "Trend accelerates: fast and slow co-aligned (launch / ride).",
    "reversal": "HTF force flips: collapse then opposite tide.",
    "chop": "No drift, mean-reverting: no tide, no play.",
    "vol_shock": "Volatility burst against trend: regime stand-down.",
}

DEFAULT_CONDITIONS = {
    "story": "pullback_resume",
    "trend": 0.7,  # -1..1 HTF drift (sign = side, magnitude = strength)
    "pullback_depth": 0.35,  # 0..1
    "noise": 1.0,  # 0.3..3 noise multiplier
    "volatility": 1.0,  # 0.3..3 overall sigma multiplier
    "pullback_hours": 2.5,  # 0.5..12 duration of the LTF pullback
    "tail_hours": 36,  # length of the replay story
    "days": 130,
    "seed": 7,
}


def synthetic_market(cond: dict | None = None) -> Market:
    c = {**DEFAULT_CONDITIONS, **(cond or {})}
    rng = np.random.default_rng(int(c["seed"]))
    days = int(c["days"])
    n = days * 1440
    sigma = 0.0006 * float(c["volatility"])
    mu = sigma * 0.15 * float(c["trend"])  # per-minute drift
    sign = 1.0 if c["trend"] >= 0 else -1.0

    # Background: persistent trend + slow wave so HTF oscillators breathe.
    t = np.arange(n)
    wave = 0.35 * abs(mu) * np.sin(2 * np.pi * t / (1440 * 9.0)) + 0.25 * abs(mu) * np.sin(2 * np.pi * t / (1440 * 2.3))
    drift = mu + wave * sign
    volm = np.ones(n)
    mr = np.zeros(n)

    tail = int(float(c["tail_hours"]) * 60)
    story = STORIES.get(c["story"], STORIES["pullback_resume"])
    if c["story"] == "chop":  # flatten the last week too so HTF tide goes flat
        drift[n - 7 * 1440:] = 0.0
    start = n - tail
    lens = []
    for ln, *_ in story:
        lens.append(None if ln == "rest" else int(60 * (float(c["pullback_hours"]) if ln == "pb" else float(ln))))
    fixed = sum(x for x in lens if x)
    lens = [max(60, tail - fixed) if x is None else x for x in lens]
    pos = start
    for (ln, dm, vm, mrev), seg in zip(story, lens):
        end = min(n, pos + seg)
        mult = -(0.5 + 2.5 * float(c["pullback_depth"])) if dm == "pull" else float(dm)
        base = abs(mu) if abs(mu) > 0 else sigma * 0.04
        drift[pos:end] = sign * base * mult
        volm[pos:end] = vm
        mr[pos:end] = mrev
        pos = end
    drift[pos:] = drift[pos - 1] if pos > 0 else 0

    eps = rng.standard_normal(n) * sigma * float(c["noise"]) * volm
    r = drift + eps
    logp = np.empty(n)
    acc = np.log(100.0)
    anchor_level = None
    for i in range(n):  # cheap loop only matters for mean reversion; vectorize when off
        if mr[i]:
            if anchor_level is None:
                anchor_level = acc
            r_i = r[i] - 0.004 * (acc - anchor_level)
        else:
            anchor_level = None
            r_i = r[i]
        acc += r_i
        logp[i] = acc
    # Rebase so the replay window starts near 100 (multiplicative shift; every indicator used is scale-invariant).
    logp += np.log(100.0) - logp[max(0, n - tail - 1440)]
    close = np.exp(logp)
    open_ = np.concatenate([[close[0]], close[:-1]])
    wick = np.abs(rng.standard_normal(n)) * sigma * 0.6 * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - np.abs(rng.standard_normal(n)) * sigma * 0.6 * close
    vol = (100 + 400 * np.abs(eps) / sigma).round()

    base = Bars("1m", t + 1.0, open_, high, low, close, vol)
    bars = {tf: resample(base, m, tf) for tf, m in TF_MIN.items()}
    return Market("synthetic", "SYNTH", bars, replay_start=float(start), replay_end=float(n), meta={"conditions": c})


def resample(b: Bars, m: int, tf: str | None = None) -> Bars:
    if m == 1:
        return b
    k = len(b.c) // m
    sl = slice(0, k * m)
    o = b.o[sl].reshape(k, m)[:, 0]
    h = b.h[sl].reshape(k, m).max(axis=1)
    l = b.l[sl].reshape(k, m).min(axis=1)
    c = b.c[sl].reshape(k, m)[:, -1]
    v = b.v[sl].reshape(k, m).sum(axis=1)
    tc = b.t_close[sl].reshape(k, m)[:, -1]
    return Bars(tf or f"{m}m", tc, o, h, l, c, v)


# ---------------------------------------------------------------- alpaca (read-only data)

ALPACA_TF = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "4h": "4Hour", "1d": "1Day"}
LOOKBACK_DAYS_STOCK = {"1m": 6, "5m": 20, "15m": 50, "30m": 90, "1h": 150, "4h": 420, "1d": 600}
LOOKBACK_DAYS_CRYPTO = {"1m": 2, "5m": 6, "15m": 14, "30m": 25, "1h": 40, "4h": 120, "1d": 400}


class AlpacaError(RuntimeError):
    pass


def alpaca_configured() -> bool:
    return bool(os.getenv("ALPACA_API_KEY_ID") and os.getenv("ALPACA_API_SECRET_KEY"))


def alpaca_market(symbol: str, replay_bars: int = 300, anchor_tf: str = "5m", client=None) -> Market:
    """Fetch bars for every official timeframe from Alpaca Market Data (read-only).

    This module never imports or calls any order endpoint.
    """
    import httpx

    if not alpaca_configured():
        raise AlpacaError("Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in .env (paper keys work for data).")
    headers = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET_KEY"]}
    crypto = "/" in symbol
    base = os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets")
    url = f"{base}/v1beta3/crypto/us/bars" if crypto else f"{base}/v2/stocks/bars"
    feed = os.getenv("ALPACA_FEED", "iex")
    lookback = LOOKBACK_DAYS_CRYPTO if crypto else LOOKBACK_DAYS_STOCK
    now = datetime.now(timezone.utc)
    own = client is None
    client = client or httpx.Client(timeout=30)
    bars: dict[str, Bars] = {}
    try:
        for tf, atf in ALPACA_TF.items():
            params = {"symbols": symbol, "timeframe": atf, "limit": 10000,
                      "start": (now - timedelta(days=lookback[tf])).strftime("%Y-%m-%dT%H:%M:%SZ"), "sort": "asc"}
            if not crypto:
                params["feed"] = feed
                params["adjustment"] = "raw"
            rows: list[dict] = []
            token = None
            for _ in range(20):
                if token:
                    params["page_token"] = token
                r = client.get(url, params=params, headers=headers)
                if r.status_code != 200:
                    raise AlpacaError(f"Alpaca {r.status_code}: {r.text[:200]}")
                js = r.json()
                rows += (js.get("bars") or {}).get(symbol, [])
                token = js.get("next_page_token")
                if not token:
                    break
            if len(rows) < 5:
                raise AlpacaError(f"Not enough {tf} bars for {symbol}")
            to = np.array([datetime.fromisoformat(x["t"].replace("Z", "+00:00")).timestamp() / 60 for x in rows])
            bars[tf] = Bars(tf, to + TF_MIN[tf], *(np.array([x[k] for x in rows], float) for k in "ohlcv"))
    finally:
        if own:
            client.close()
    a = bars[anchor_tf]
    start_idx = max(0, len(a) - replay_bars)
    return Market("alpaca", symbol, bars, replay_start=float(a.t_close[start_idx]), replay_end=float(a.t_close[-1]),
                  meta={"feed": feed, "fetched_at": now.isoformat()})
