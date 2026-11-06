"""Canonical scoring engine.

Every score is 0-100 = 100 * (points earned / points possible) over the factors that had data.
Factors without data are listed with value=None and excluded from the denominator. A score with no
usable factors is None (unknown), never a guess. All thresholds live in this file.
"""
from __future__ import annotations

import statistics

WEIGHTS = {
    "trend_score": 0.18, "price_score": 0.10, "volume_score": 0.12, "entry_score": 0.12, "rr_score": 0.12,
    "fundamental_score": 0.12, "sector_score": 0.08, "news_score": 0.08, "fno_score": 0.08,
}
BUY_THRESHOLD = 62
STRONG_BUY_THRESHOLD = 75
SELL_THRESHOLD = 40
STRONG_SELL_THRESHOLD = 30
MIN_RR_FOR_BUY = 1.5
MIN_ENTRY_SCORE_FOR_BUY = 35


class _Card:
    def __init__(self):
        self.factors: list[dict] = []

    def add(self, name: str, value, points: float | None, max_points: float, note: str = ""):
        self.factors.append({"name": name, "value": value, "points": None if points is None else round(points, 2),
                             "max": max_points, "note": note})

    def result(self) -> dict:
        used = [f for f in self.factors if f["points"] is not None]
        if not used:
            return {"score": None, "factors": self.factors, "coverage": 0.0}
        earned = sum(f["points"] for f in used)
        possible = sum(f["max"] for f in used)
        total_possible = sum(f["max"] for f in self.factors)
        return {"score": round(100 * earned / possible), "factors": self.factors,
                "coverage": round(possible / total_possible, 2) if total_possible else 0.0}


def _tier(value, tiers: list[tuple[float, float]], default: float) -> float:
    for threshold, pts in tiers:
        if value >= threshold:
            return pts
    return default


def _trend_pts(trend: str | None, full: float) -> float | None:
    if trend is None:
        return None
    return {"UPTREND": full, "SIDEWAYS": full * 0.4, "DOWNTREND": 0.0}.get(trend, 0.0)


def price_score(d: dict, quote: dict) -> dict:
    c = _Card()
    above = d.get("moving_averages", {}).get("price_above", {})
    for ma in ("sma20", "sma50", "sma200"):
        v = above.get(ma)
        c.add(f"price above {ma.upper()}", v, None if v is None else (10 if v else 0), 10)
    hz = d.get("high_zone") or {}
    pct = hz.get("pct_from_high")
    c.add("distance from 52-week high (%)", pct, None if pct is None else (15 if pct <= 5 else 8 if pct <= 15 else 0), 15,
          "within 5% of 52-week high" if pct is not None and pct <= 5 else "")
    roc = d.get("momentum", {}).get("roc10")
    c.add("10-bar rate of change (%)", roc, None if roc is None else _tier(roc, [(5, 10), (0, 6), (-5, 3)], 0), 10)
    chg = quote.get("change_pct")
    c.add("today's change (%)", chg, None if chg is None else (5 if chg > 0 else 0), 5)
    return c.result()


def trend_score(daily: dict, mtf: dict[str, dict]) -> dict:
    c = _Card()
    c.add("daily trend", daily.get("trend"), _trend_pts(daily.get("trend"), 25), 25)
    al = daily.get("ma_alignment")
    c.add("moving-average alignment", al, None if al is None else {"bullish": 15, "mixed": 6}.get(al, 0), 15,
          "price > SMA20 > SMA50 > SMA200" if al == "bullish" else "")
    ang = daily.get("slope", {}).get("sma20_angle_deg")
    c.add("SMA20 slope angle (deg)", ang, None if ang is None else _tier(ang, [(20, 10), (5, 7), (0, 4)], 0), 10)
    st = daily.get("structure", {})
    for key, label in (("higher_high", "daily higher high"), ("higher_low", "daily higher low")):
        v = st.get(key)
        c.add(label, v, None if v is None else (10 if v else 0), 10)
    xo = daily.get("ma_crossover") or {}
    c.add("EMA9 above EMA21", xo.get("state"), None if xo.get("state") is None else (5 if xo["state"] == "above" else 0), 5)
    for tf, mx in (("1h", 10), ("15m", 6), ("5m", 4)):
        t = (mtf.get(tf) or {}).get("trend")
        c.add(f"{tf} trend", t, _trend_pts(t, mx), mx)
    return c.result()


def volume_score(daily: dict) -> dict:
    c = _Card()
    v = daily.get("volume") or {}
    ratio = v.get("ratio")
    distribution = ratio is not None and ratio >= 1.5 and not v.get("confirmation")
    pts = None if ratio is None else (0 if distribution else _tier(ratio, [(2, 15), (1.5, 12), (1, 8), (0.7, 4)], 0))
    c.add("last-bar volume vs 20-bar average", ratio, pts, 15,
          "high volume on a down bar (distribution)" if distribution else "")
    ud = v.get("up_down_ratio20")
    c.add("20-bar up/down volume ratio", ud, None if ud is None else _tier(ud, [(1.5, 15), (1.1, 10), (0.9, 6)], 2), 15,
          "accumulation" if ud and ud >= 1.5 else "")
    conf = v.get("confirmation")
    c.add("volume-confirmed up bar", conf, None if conf is None else (10 if conf else 0), 10)
    return c.result()


def fundamental_score(ref: dict) -> dict:
    c = _Card()
    f = ref.get("fundamentals", {})
    s = ref.get("shareholding", {})
    roe = f.get("roe")
    c.add("ROE (%)", roe, None if roe is None else _tier(roe, [(20, 20), (15, 15), (10, 8)], 2), 20)
    rg = f.get("roe_growth")
    c.add("ROE growth (pp)", rg, None if rg is None else _tier(rg, [(2, 10), (0.0001, 7), (-2, 4)], 0), 10)
    sg = f.get("sales_growth")
    c.add("sales growth (%)", sg, None if sg is None else _tier(sg, [(15, 15), (8, 11), (0, 6)], 0), 15)
    pg = f.get("profit_growth")
    c.add("profit growth (%)", pg, None if pg is None else _tier(pg, [(20, 20), (10, 14), (0, 7)], 0), 20)
    pe, spe = f.get("pe"), f.get("sector_pe")
    if pe is None:
        pe_pts = None
    elif pe <= 0:
        pe_pts = 0
    elif spe:
        pe_pts = 10 if pe <= spe else 6 if pe <= 1.5 * spe else 2
    else:
        pe_pts = 8 if pe < 25 else 5 if pe < 45 else 2
    c.add("PE vs sector PE", {"pe": pe, "sector_pe": spe}, pe_pts, 10)
    fii, dii = s.get("fii_change"), s.get("dii_change")
    c.add("FII holding change (pp)", fii, None if fii is None else (5 if fii > 0 else 0), 5)
    c.add("DII holding change (pp)", dii, None if dii is None else (5 if dii > 0 else 0), 5)
    return c.result()


def news_score(ref: dict) -> dict:
    c = _Card()
    n = ref.get("news", {})
    sent = n.get("sentiment") if n.get("items") else None
    c.add("news sentiment (-1..1)", sent, None if sent is None else (sent + 1) / 2 * 20, 20)
    if n.get("items"):
        cat = n.get("catalyst")
        pts = 5 if not cat else (10 if (sent or 0) > 0 else 0)
        c.add("catalyst", cat, pts, 10)
    else:
        c.add("catalyst", None, None, 10)
    return c.result()


def sector_score(ctx: dict | None) -> dict:
    c = _Card()
    ctx = ctx or {}
    rs = ctx.get("avg_rs20")
    c.add("sector avg relative strength (20d)", rs, None if rs is None else _tier(rs, [(1.03, 20), (1.0, 14), (0.97, 7)], 2), 20)
    up = ctx.get("pct_uptrend")
    c.add("sector peers in uptrend (%)", up, None if up is None else _tier(up, [(60, 15), (40, 9)], 3), 15)
    return c.result()


def fno_buildup(price_change_pct: float | None, oi_change_pct: float | None) -> str | None:
    if price_change_pct is None or oi_change_pct is None:
        return None
    if price_change_pct >= 0:
        return "LONG_BUILDUP" if oi_change_pct >= 0 else "SHORT_COVERING"
    return "SHORT_BUILDUP" if oi_change_pct >= 0 else "LONG_UNWINDING"


def fno_score(ref: dict, quote: dict) -> dict:
    c = _Card()
    f = ref.get("fno", {})
    if f.get("eligible") is False:
        out = c.result()
        out["not_applicable"] = True
        return out
    b = fno_buildup(quote.get("change_pct"), f.get("oi_change_pct"))
    c.add("price/OI buildup", b, None if b is None else
          {"LONG_BUILDUP": 25, "SHORT_COVERING": 18, "LONG_UNWINDING": 9, "SHORT_BUILDUP": 3}[b], 25)
    pcr = f.get("pcr")
    c.add("put-call ratio", pcr, None if pcr is None else (10 if 0.8 <= pcr <= 1.3 else 7 if pcr > 1.3 else 3), 10)
    out = c.result()
    out["buildup"] = b
    return out


def rr_score(plan: dict) -> dict:
    c = _Card()
    rr = plan.get("risk_reward")
    if rr is None:
        pts = None
    else:
        knots = [(0.5, 0), (1.0, 30), (1.5, 55), (2.0, 75), (3.0, 100)]
        if rr <= knots[0][0]:
            pts = 0
        elif rr >= knots[-1][0]:
            pts = 100
        else:
            pts = next(p0 + (p1 - p0) * (rr - r0) / (r1 - r0) for (r0, p0), (r1, p1) in zip(knots, knots[1:]) if r0 <= rr <= r1)
    c.add("risk:reward", rr, pts, 100)
    return c.result()


def entry_score(daily: dict, mtf: dict[str, dict], plan: dict) -> dict:
    c = _Card()
    close, sma20, atr = daily.get("close"), daily.get("moving_averages", {}).get("sma20"), daily.get("atr14")
    ext = (close - sma20) / atr if close and sma20 and atr else None
    if ext is None:
        pts = None
    elif ext < -0.5:
        pts = 5
    elif ext <= 1:
        pts = 25
    elif ext <= 2:
        pts = 15
    elif ext <= 3:
        pts = 7
    else:
        pts = 0
    c.add("extension above SMA20 (ATR multiples)", None if ext is None else round(ext, 2), pts, 25,
          "over-extended; wait for pullback" if ext is not None and ext > 3 else "")
    r = daily.get("momentum", {}).get("rsi14")
    if r is None:
        rp = None
    elif 50 <= r <= 65:
        rp = 20
    elif 65 < r <= 72:
        rp = 12
    elif 40 <= r < 50:
        rp = 10
    else:
        rp = 3
    c.add("daily RSI14", r, rp, 20)
    for tf, mx in (("15m", 10), ("5m", 5)):
        t = (mtf.get(tf) or {}).get("trend")
        c.add(f"{tf} trend at entry", t, _trend_pts(t, mx), mx)
    b = (daily.get("breakout") or {}).get("status")
    conf = (daily.get("volume") or {}).get("confirmation")
    bp = None if b is None else {"BREAKOUT": 15 if conf else 8, "NEAR_HIGH": 12, "TIGHT_RANGE": 12, "NONE": 5,
                                 "BREAKDOWN": 0}.get(b, 5)
    c.add("breakout / base status", b, bp, 15)
    sp = plan.get("stop_pct")
    c.add("stop distance (%)", sp, None if sp is None else (10 if sp <= 4 else 7 if sp <= 6 else 4 if sp <= 8 else 0), 10)
    return c.result()


def _rating(signal: str, total: float) -> str:
    if signal == "BUY":
        return "STRONG BUY" if total >= STRONG_BUY_THRESHOLD else "BUY"
    if signal == "SELL":
        return "STRONG SELL" if total < STRONG_SELL_THRESHOLD else "SELL"
    return "HOLD"


def decide(scores: dict[str, dict], daily: dict, plan: dict, *, data_quality: str) -> dict:
    values = {k: v["score"] for k, v in scores.items() if v.get("score") is not None}
    reasons: list[str] = []
    warnings: list[str] = []
    if not values:
        return {"total_score": None, "average_score": None, "signal": "HOLD", "rating": "HOLD", "confidence": 0,
                "reasons": [], "warnings": ["No scores could be computed - insufficient data."], "weights_used": {}}

    wsum = sum(WEIGHTS[k] for k in values)
    total = round(sum(values[k] * WEIGHTS[k] for k in values) / wsum, 1)
    average = round(sum(values.values()) / len(values), 1)

    trend = daily.get("trend")
    rr = plan.get("risk_reward")
    signal = "HOLD"
    if total >= BUY_THRESHOLD:
        blockers = []
        if trend == "DOWNTREND":
            blockers.append("daily trend is DOWN")
        if rr is None or rr < MIN_RR_FOR_BUY:
            blockers.append(f"risk:reward {rr} below {MIN_RR_FOR_BUY}")
        if data_quality == "insufficient":
            blockers.append("insufficient data quality")
        es = values.get("entry_score")
        if es is not None and es < MIN_ENTRY_SCORE_FOR_BUY:
            blockers.append(f"entry score {es} below {MIN_ENTRY_SCORE_FOR_BUY} (extended - wait for a better entry)")
        if blockers:
            warnings.append("BUY downgraded to HOLD: " + "; ".join(blockers) + ".")
        else:
            signal = "BUY"
    elif total < SELL_THRESHOLD or (trend == "DOWNTREND" and daily.get("ma_alignment") == "bearish" and total < 50):
        signal = "SELL"

    for key, card in sorted(scores.items(), key=lambda kv: -WEIGHTS.get(kv[0], 0)):
        for f in card.get("factors", []):
            if f["points"] is None:
                continue
            ratio = f["points"] / f["max"] if f["max"] else 0
            label = key.replace("_score", "")
            if ratio >= 0.8:
                reasons.append(f"{label}: {f['name']} = {_fmt(f['value'])}" + (f" ({f['note']})" if f["note"] else ""))
            elif ratio == 0 and key in ("trend_score", "entry_score", "volume_score", "rr_score"):
                warnings.append(f"{label}: {f['name']} = {_fmt(f['value'])}" + (f" ({f['note']})" if f["note"] else ""))

    missing = [k for k, v in scores.items() if v.get("score") is None and not v.get("not_applicable")]
    if missing:
        warnings.append("Not scored (no data): " + ", ".join(m.replace("_score", "") for m in missing) + ".")

    coverage = wsum / sum(WEIGHTS[k] for k in scores if not scores[k].get("not_applicable"))
    spread = statistics.pstdev(values.values()) if len(values) > 1 else 0.0
    agreement = max(0.0, 1 - spread / 35)
    conviction = min(1.0, abs(total - 50) / 30)
    dq = {"ok": 1.0, "partial": 0.8, "insufficient": 0.5}.get(data_quality, 0.7)
    confidence = round(100 * dq * (0.4 * min(1.0, coverage) + 0.3 * agreement + 0.3 * conviction))

    return {"total_score": total, "average_score": average, "signal": signal, "rating": _rating(signal, total),
            "confidence": confidence, "reasons": reasons[:8], "warnings": warnings,
            "weights_used": {k: round(WEIGHTS[k] / wsum, 3) for k in values},
            "confidence_inputs": {"coverage": round(coverage, 2), "agreement": round(agreement, 2),
                                  "conviction": round(conviction, 2), "data_quality_factor": dq}}


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, dict):
        return ", ".join(f"{k}={_fmt(x)}" for k, x in v.items())
    return str(v)
