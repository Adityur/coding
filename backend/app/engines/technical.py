"""Technical-analysis engine. Values are derived only from supplied candles; missing history -> None."""
from __future__ import annotations

from datetime import date

from ..providers.base import Candle
from . import indicators as ind

MIN_BARS = 30
PIVOT_K = 3
HIGH_ZONE_PCT = 5.0


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def _close_on_or_before(series: dict[date, float], d: date, dates_sorted: list[date]) -> float | None:
    if d in series:
        return series[d]
    prior = [x for x in dates_sorted if x <= d]
    return series[prior[-1]] if prior else None


def relative_strength(candles: list[Candle], benchmark: list[Candle] | None, periods=(20, 60)) -> dict:
    out = {"benchmark": "NIFTY 50", "rs20": None, "rs60": None, "stock_return_20": None, "benchmark_return_20": None,
           "outperforming": None}
    if not benchmark or len(benchmark) < 2:
        out["note"] = "benchmark data unavailable"
        return out
    bmap = {c.ts.date(): c.close for c in benchmark}
    bdates = sorted(bmap)
    for n in periods:
        if len(candles) <= n:
            continue
        s0, s1 = candles[-n - 1], candles[-1]
        b0 = _close_on_or_before(bmap, s0.ts.date(), bdates)
        b1 = _close_on_or_before(bmap, s1.ts.date(), bdates)
        if not b0 or not b1 or not s0.close:
            continue
        sr, br = s1.close / s0.close - 1, b1 / b0 - 1
        out[f"rs{n}"] = round((1 + sr) / (1 + br), 4)
        if n == 20:
            out["stock_return_20"] = round(sr * 100, 2)
            out["benchmark_return_20"] = round(br * 100, 2)
    if out["rs20"] is not None:
        out["outperforming"] = out["rs20"] > 1.0
    return out


def analyze_timeframe(candles: list[Candle], timeframe: str, benchmark: list[Candle] | None = None) -> dict:
    n = len(candles)
    base = {"timeframe": timeframe, "bars": n, "last_ts": candles[-1].ts.isoformat() if candles else None,
            "close": candles[-1].close if candles else None}
    if n < MIN_BARS:
        return {**base, "data_quality": {"status": "insufficient", "bars": n, "required": MIN_BARS,
                                         "missing": ["all indicators"]},
                "trend": None, "structure": {"higher_high": None, "higher_low": None, "lower_high": None, "lower_low": None},
                "moving_averages": {}, "ma_crossover": None, "slope": {}, "momentum": {}, "breakout": None,
                "pattern": None, "volume": {}, "relative_strength": {}, "support": [], "resistance": [],
                "atr14": None, "atr_pct": None, "high_zone": None, "ma_alignment": None}

    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    vols = [c.volume for c in candles]
    close = closes[-1]
    missing: list[str] = []

    sma20, sma50, sma200 = ind.sma(closes, 20), ind.sma(closes, 50), ind.sma(closes, 200)
    ema9, ema21 = ind.ema(closes, 9), ind.ema(closes, 21)
    mas = {"sma20": _r(ind.last(sma20)), "sma50": _r(ind.last(sma50)), "sma200": _r(ind.last(sma200)),
           "ema9": _r(ind.last(ema9)), "ema21": _r(ind.last(ema21))}
    for k, v in mas.items():
        if v is None:
            missing.append(k)
    mas["price_above"] = {k: (close > v) for k, v in list(mas.items()) if isinstance(v, (int, float))}

    chain = [v for v in (close, mas["sma20"], mas["sma50"], mas["sma200"]) if v is not None]
    if len(chain) >= 3:
        if all(a > b for a, b in zip(chain, chain[1:])):
            alignment = "bullish"
        elif all(a < b for a, b in zip(chain, chain[1:])):
            alignment = "bearish"
        else:
            alignment = "mixed"
    else:
        alignment = None

    crossover = {"pair": "EMA9/EMA21", "signal": "none", "bars_ago": None, "state": None,
                 "golden_cross": None, "death_cross": None}
    if ema9[-1] is not None and ema21[-1] is not None:
        crossover["state"] = "above" if ema9[-1] > ema21[-1] else "below"
        for back in range(1, min(6, n - 21)):
            a1, b1, a0, b0 = ema9[-back], ema21[-back], ema9[-back - 1], ema21[-back - 1]
            if None in (a1, b1, a0, b0):
                break
            if a0 <= b0 and a1 > b1:
                crossover.update(signal="bullish_cross", bars_ago=back - 1)
                break
            if a0 >= b0 and a1 < b1:
                crossover.update(signal="bearish_cross", bars_ago=back - 1)
                break
    if sma50[-1] is not None and sma200[-1] is not None:
        recent = [(sma50[i], sma200[i]) for i in range(max(0, n - 11), n) if sma50[i] is not None and sma200[i] is not None]
        crossover["golden_cross"] = any(a0 <= b0 and a1 > b1 for (a0, b0), (a1, b1) in zip(recent, recent[1:]))
        crossover["death_cross"] = any(a0 >= b0 and a1 < b1 for (a0, b0), (a1, b1) in zip(recent, recent[1:]))

    s20_pct, s20_ang = ind.slope_angle(sma20, 10)
    s50_pct, s50_ang = ind.slope_angle(sma50, 10)
    slope = {"sma20_pct_per_bar": s20_pct, "sma20_angle_deg": s20_ang,
             "sma50_pct_per_bar": s50_pct, "sma50_angle_deg": s50_ang,
             "convention": "angle = atan(% change per bar); 1%/bar = 45 deg"}

    ph, pl = ind.pivots(highs, lows, PIVOT_K)
    structure = {"higher_high": None, "higher_low": None, "lower_high": None, "lower_low": None,
                 "last_swing_high": None, "prev_swing_high": None, "last_swing_low": None, "prev_swing_low": None}
    if len(ph) >= 2:
        structure.update(last_swing_high=ph[-1][1], prev_swing_high=ph[-2][1],
                         higher_high=ph[-1][1] > ph[-2][1], lower_high=ph[-1][1] < ph[-2][1])
    if len(pl) >= 2:
        structure.update(last_swing_low=pl[-1][1], prev_swing_low=pl[-2][1],
                         higher_low=pl[-1][1] > pl[-2][1], lower_low=pl[-1][1] < pl[-2][1])
    if ph and close > ph[-1][1]:
        structure["higher_high"] = True
        structure["lower_high"] = False
    if structure["higher_high"] is None:
        missing.append("swing structure (highs)")
    if structure["higher_low"] is None:
        missing.append("swing structure (lows)")

    trend_ma = mas["sma50"] if mas["sma50"] is not None else mas["sma20"]
    trend = None
    if structure["higher_high"] is not None and structure["higher_low"] is not None and trend_ma is not None:
        if structure["higher_high"] and structure["higher_low"] and close > trend_ma:
            trend = "UPTREND"
        elif structure["lower_high"] and structure["lower_low"] and close < trend_ma:
            trend = "DOWNTREND"
        else:
            trend = "SIDEWAYS"

    r = ind.rsi(closes, 14)
    m_line, m_sig, m_hist = ind.macd(closes)
    roc10 = (close / closes[-11] - 1) * 100 if n > 11 and closes[-11] else None
    momentum = {"rsi14": _r(ind.last(r)), "macd": _r(ind.last(m_line), 3), "macd_signal": _r(ind.last(m_sig), 3),
                "macd_hist": _r(ind.last(m_hist), 3), "roc10": _r(roc10)}

    atr_series = ind.atr(highs, lows, closes, 14)
    atr14 = ind.last(atr_series)
    prior_high = max(highs[-21:-1])
    prior_low = min(lows[-21:-1])
    range10 = max(highs[-10:]) - min(lows[-10:])
    if close > prior_high:
        b_status, level = "BREAKOUT", prior_high
    elif close < prior_low:
        b_status, level = "BREAKDOWN", prior_low
    elif atr14 and range10 < 2.5 * atr14:
        b_status, level = "TIGHT_RANGE", prior_high
    elif (prior_high - close) / close * 100 <= 2.0:
        b_status, level = "NEAR_HIGH", prior_high
    else:
        b_status, level = "NONE", prior_high
    breakout = {"status": b_status, "level": _r(level), "lookback": 20}

    volume: dict = {"last": None, "avg20": None, "ratio": None, "confirmation": None, "up_down_ratio20": None}
    if any(vols):
        avg20 = sum(vols[-21:-1]) / 20
        ratio = vols[-1] / avg20 if avg20 else None
        up = sum(v for c, v, pc in zip(closes[-20:], vols[-20:], closes[-21:-1]) if c > pc)
        down = sum(v for c, v, pc in zip(closes[-20:], vols[-20:], closes[-21:-1]) if c < pc)
        volume = {"last": vols[-1], "avg20": round(avg20), "ratio": _r(ratio),
                  "confirmation": bool(ratio and ratio >= 1.5 and candles[-1].close > candles[-1].open),
                  "up_down_ratio20": _r(up / down) if down else None}
    else:
        missing.append("volume")

    pattern = None
    if b_status == "BREAKOUT":
        pattern = "Breakout with volume" if volume.get("confirmation") else "Breakout (volume not confirmed)"
    elif b_status == "BREAKDOWN":
        pattern = "Breakdown below 20-bar low"
    elif trend == "UPTREND" and atr14 and mas["sma20"] and abs(close - mas["sma20"]) <= atr14 and close > (mas["sma50"] or 0):
        pattern = "Pullback to 20 SMA in uptrend"
    elif b_status == "TIGHT_RANGE":
        pattern = "Tight consolidation"
    elif b_status == "NEAR_HIGH":
        pattern = "Near 20-bar high"
    elif trend == "DOWNTREND" and alignment == "bearish":
        pattern = "Below key averages in downtrend"

    window = 120
    off = max(0, n - window)
    supports = sorted({round(p, 2) for i, p in pl if i >= off and p < close}, reverse=True)[:3]
    resistances = sorted({round(p, 2) for i, p in ph if i >= off and p > close})[:3]
    if not supports and prior_low < close:
        supports = [round(prior_low, 2)]
    if not resistances and prior_high > close:
        resistances = [round(prior_high, 2)]

    high_zone = None
    if timeframe == "1d":
        look = highs[-252:]
        h52 = max(look)
        pct = (h52 - close) / h52 * 100
        high_zone = {"high_52w": _r(h52), "low_52w": _r(min(lows[-252:])), "pct_from_high": _r(pct),
                     "in_high_zone": pct <= HIGH_ZONE_PCT, "bars_used": len(look),
                     "complete": len(look) >= 250}

    rs = relative_strength(candles, benchmark) if timeframe == "1d" else {}

    status = "ok" if not missing else ("partial" if len(missing) <= 3 else "insufficient")
    return {
        **base,
        "data_quality": {"status": status, "bars": n, "missing": missing},
        "moving_averages": mas, "ma_alignment": alignment, "ma_crossover": crossover, "slope": slope,
        "structure": structure, "trend": trend, "momentum": momentum, "breakout": breakout, "pattern": pattern,
        "volume": volume, "relative_strength": rs, "support": supports, "resistance": resistances,
        "atr14": _r(atr14), "atr_pct": _r(atr14 / close * 100) if atr14 else None, "high_zone": high_zone,
    }


def multi_timeframe_summary(by_tf: dict[str, dict]) -> dict:
    rows = {}
    for tf, a in by_tf.items():
        if a is None:
            continue
        rows[tf] = {"trend": a.get("trend"), "higher_high": a.get("structure", {}).get("higher_high"),
                    "higher_low": a.get("structure", {}).get("higher_low"), "ma_alignment": a.get("ma_alignment"),
                    "rsi14": a.get("momentum", {}).get("rsi14"), "data_quality": a.get("data_quality", {}).get("status")}
    trends = [r["trend"] for r in rows.values() if r["trend"]]
    up, down = trends.count("UPTREND"), trends.count("DOWNTREND")
    if not trends:
        alignment = None
    elif up == len(trends):
        alignment = "ALIGNED_UP"
    elif down == len(trends):
        alignment = "ALIGNED_DOWN"
    elif up > down:
        alignment = "MOSTLY_UP"
    elif down > up:
        alignment = "MOSTLY_DOWN"
    else:
        alignment = "MIXED"
    return {"timeframes": rows, "alignment": alignment, "uptrend_count": up, "downtrend_count": down,
            "evaluated": len(trends)}
