"""Pure-Python indicator primitives. Each returns None where history is insufficient."""
from __future__ import annotations

import math


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, len(values)):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's ATR."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    trs = [highs[0] - lows[0]] + [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, n)
    ]
    prev = sum(trs[1:period + 1]) / period
    out[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [f - s if f is not None and s is not None else None for f, s in zip(ef, es)]
    valid = [v for v in line if v is not None]
    sig_valid = ema(valid, signal)
    sig: list[float | None] = [None] * (len(line) - len(valid)) + sig_valid
    hist = [l - s if l is not None and s is not None else None for l, s in zip(line, sig)]
    return line, sig, hist


def linreg_slope(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den if den else None


def slope_angle(series: list[float | None], lookback: int = 10) -> tuple[float | None, float | None]:
    """Slope of the last `lookback` values as % of the latest value per bar, and its angle in degrees.

    Convention: 1% per bar == 45 degrees (angle = atan(pct_per_bar)). Chart-independent and documented.
    """
    tail = [v for v in series[-lookback:] if v is not None]
    if len(tail) < lookback or not tail[-1]:
        return None, None
    slope = linreg_slope(tail)
    if slope is None:
        return None, None
    pct = slope / tail[-1] * 100
    return round(pct, 4), round(math.degrees(math.atan(pct)), 2)


def pivots(highs: list[float], lows: list[float], k: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Swing highs/lows: bar i is a pivot if it is the extreme of the window [i-k, i+k]."""
    ph, pl = [], []
    for i in range(k, len(highs) - k):
        window_h = highs[i - k:i + k + 1]
        window_l = lows[i - k:i + k + 1]
        # On a tied plateau only the first bar qualifies (index() returns the leftmost match).
        if window_h.index(max(window_h)) == k:
            ph.append((i, highs[i]))
        if window_l.index(min(window_l)) == k:
            pl.append((i, lows[i]))
    return ph, pl


def last(series: list[float | None]) -> float | None:
    return series[-1] if series else None
