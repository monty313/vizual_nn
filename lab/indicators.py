"""MT5-style indicator math (numpy only). All functions return arrays aligned to input bars.

Forward shift follows MT5 semantics: a line with shift s is drawn s bars to the right,
so value_displayed[i] = value[i - s].
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

NAN = np.nan


def _pad(x: np.ndarray, n: int, out_len: int) -> np.ndarray:
    out = np.full(out_len, NAN)
    out[n:] = x
    return out


def sma(x: np.ndarray, p: int) -> np.ndarray:
    if len(x) < p:
        return np.full(len(x), NAN)
    x = x.astype(float)
    ok = ~np.isnan(x)  # windows that touch a NaN stay NaN; the rest are unaffected
    c = np.cumsum(np.insert(np.where(ok, x, 0.0), 0, 0.0))
    k = np.cumsum(np.insert(ok.astype(float), 0, 0.0))
    v = (c[p:] - c[:-p]) / p
    v[(k[p:] - k[:-p]) < p] = np.nan
    return _pad(v, p - 1, len(x))


def ema(x: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(x), NAN)
    if len(x) < p:
        return out
    a = 2.0 / (p + 1)
    out[p - 1] = x[:p].mean()
    for i in range(p, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def wilder(x: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(x), NAN)
    if len(x) < p:
        return out
    out[p - 1] = np.nanmean(x[:p])
    for i in range(p, len(x)):
        out[i] = (out[i - 1] * (p - 1) + x[i]) / p
    return out


def shift_fwd(x: np.ndarray, s: int) -> np.ndarray:
    if s <= 0:
        return x
    out = np.full(len(x), NAN)
    out[s:] = x[:-s]
    return out


def stddev(c: np.ndarray, p: int) -> np.ndarray:
    if len(c) < p:
        return np.full(len(c), NAN)
    w = sliding_window_view(c.astype(float), p)
    return _pad(w.std(axis=1), p - 1, len(c))


def cci(h, l, c, p: int) -> np.ndarray:
    tp = (h + l + c) / 3.0
    if len(tp) < p:
        return np.full(len(tp), NAN)
    w = sliding_window_view(tp, p)
    m = w.mean(axis=1)
    md = np.abs(w - m[:, None]).mean(axis=1)
    md[md == 0] = 1e-12
    v = (tp[p - 1:] - m) / (0.015 * md)
    return _pad(v, p - 1, len(tp))


def rsi(c, p: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = wilder(np.clip(d, 0, None), p)
    dn = wilder(np.clip(-d, 0, None), p)
    rs = up / np.where(dn == 0, 1e-12, dn)
    return 100 - 100 / (1 + rs)


def momentum(c, p: int) -> np.ndarray:
    out = np.full(len(c), NAN)
    out[p:] = c[p:] / c[:-p] * 100.0
    return out


def stochastic(h, l, c, p: int, slowing: int = 3) -> np.ndarray:
    if len(c) < p:
        return np.full(len(c), NAN)
    hh = _pad(sliding_window_view(h, p).max(axis=1), p - 1, len(c))
    ll = _pad(sliding_window_view(l, p).min(axis=1), p - 1, len(c))
    num = sma(c - ll, slowing)
    den = sma(hh - ll, slowing)
    return 100 * num / np.where(den == 0, 1e-12, den)


def wpr(h, l, c, p: int) -> np.ndarray:
    if len(c) < p:
        return np.full(len(c), NAN)
    hh = _pad(sliding_window_view(h, p).max(axis=1), p - 1, len(c))
    ll = _pad(sliding_window_view(l, p).min(axis=1), p - 1, len(c))
    return -100 * (hh - c) / np.where(hh - ll == 0, 1e-12, hh - ll)


def bulls_power(h, c, p: int) -> np.ndarray:
    return h - ema(c, p)


def bears_power(l, c, p: int) -> np.ndarray:
    return l - ema(c, p)


def adx(h, l, c, p: int):
    """Returns (adx, +DI, -DI)."""
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = wilder(tr, p)
    atr = np.where(atr == 0, 1e-12, atr)
    pdi = 100 * wilder(pdm, p) / atr
    ndi = 100 * wilder(ndm, p) / atr
    dx = 100 * np.abs(pdi - ndi) / np.where(pdi + ndi == 0, 1e-12, pdi + ndi)
    dx = np.nan_to_num(dx, nan=0.0)
    return wilder(dx, p), pdi, ndi
