from app.engines import risk, scoring
from app.engines.technical import analyze_timeframe
from conftest import make_candles, zigzag_downtrend, zigzag_uptrend


def _daily(closes):
    return analyze_timeframe(make_candles(closes), "1d")


# ---------- risk ----------
def test_long_plan_levels_are_ordered_and_rr_consistent():
    d = _daily(zigzag_uptrend())
    p = risk.plan_long(d, d["close"], capital=500000, risk_pct=1, max_position_pct=20)
    assert p["stop_loss"] < p["entry"] < p["target"] < p["target_2"]
    assert abs(p["risk_reward"] - (p["target"] - p["entry"]) / (p["entry"] - p["stop_loss"])) < 0.02
    assert p["risk_reward"] >= 1.5


def test_position_size_respects_risk_and_cap():
    d = _daily(zigzag_uptrend())
    p = risk.plan_long(d, d["close"], capital=1_000_000, risk_pct=1, max_position_pct=20)
    pos = p["position"]
    assert pos["max_loss_at_stop"] <= 1_000_000 * 0.01 + 1e-6
    assert pos["position_value"] <= 1_000_000 * 0.20 + 1e-6


def test_plan_without_atr_returns_nulls_and_warning():
    d = analyze_timeframe(make_candles([100.0] * 5), "1d")
    p = risk.plan_long(d, 100.0, capital=1e5, risk_pct=1, max_position_pct=20)
    assert p["entry"] is None and p["risk_reward"] is None and p["warnings"]


def test_disclaimer_never_promises_returns():
    assert "not predictions or guaranteed" in risk.DISCLAIMER


# ---------- scoring ----------
REF_FULL = {
    "fundamentals": {"roe": 25, "roe_growth": 3, "sales_growth": 20, "profit_growth": 25, "pe": 20, "sector_pe": 30},
    "shareholding": {"fii_change": 0.5, "dii_change": 0.2},
    "news": {"items": [{"headline": "x", "sentiment": 0.6}], "sentiment": 0.6, "catalyst": "x"},
    "fno": {"eligible": True, "oi_change_pct": 5, "pcr": 1.0},
}
REF_EMPTY = {"fundamentals": {}, "shareholding": {}, "news": {"items": []}, "fno": {"eligible": None}}


def test_score_is_traceable_to_factors():
    card = scoring.fundamental_score(REF_FULL)
    assert card["score"] == 100
    assert all({"name", "value", "points", "max"} <= set(f) for f in card["factors"])


def test_missing_data_yields_null_score_not_guess():
    assert scoring.fundamental_score(REF_EMPTY)["score"] is None
    assert scoring.news_score(REF_EMPTY)["score"] is None
    assert scoring.sector_score(None)["score"] is None


def test_fno_not_applicable_when_not_eligible():
    card = scoring.fno_score({"fno": {"eligible": False}}, {"change_pct": 1})
    assert card["score"] is None and card["not_applicable"] is True


def test_fno_buildup_classification():
    assert scoring.fno_buildup(1, 1) == "LONG_BUILDUP"
    assert scoring.fno_buildup(1, -1) == "SHORT_COVERING"
    assert scoring.fno_buildup(-1, 1) == "SHORT_BUILDUP"
    assert scoring.fno_buildup(-1, -1) == "LONG_UNWINDING"
    assert scoring.fno_buildup(None, 1) is None


def test_rr_score_interpolation():
    assert scoring.rr_score({"risk_reward": 3.5})["score"] == 100
    assert scoring.rr_score({"risk_reward": 2.0})["score"] == 75
    assert scoring.rr_score({"risk_reward": 0.4})["score"] == 0
    assert scoring.rr_score({"risk_reward": None})["score"] is None


def _all_scores(daily, ref, quote, plan, sector=None):
    mtf = {}
    return {"price_score": scoring.price_score(daily, quote), "news_score": scoring.news_score(ref),
            "volume_score": scoring.volume_score(daily), "fundamental_score": scoring.fundamental_score(ref),
            "sector_score": scoring.sector_score(sector), "fno_score": scoring.fno_score(ref, quote),
            "rr_score": scoring.rr_score(plan), "trend_score": scoring.trend_score(daily, mtf),
            "entry_score": scoring.entry_score(daily, mtf, plan)}


def test_downtrend_never_gets_buy():
    d = _daily(zigzag_downtrend())
    plan = risk.plan_long(d, d["close"], capital=1e6, risk_pct=1, max_position_pct=20)
    scores = _all_scores(d, REF_FULL, {"change_pct": 1.0}, plan, {"avg_rs20": 1.1, "pct_uptrend": 100})
    dec = scoring.decide(scores, d, plan, data_quality="ok")
    assert dec["signal"] != "BUY"


def test_decision_fields_and_ranges():
    d = _daily(zigzag_uptrend())
    plan = risk.plan_long(d, d["close"], capital=1e6, risk_pct=1, max_position_pct=20)
    dec = scoring.decide(_all_scores(d, REF_FULL, {"change_pct": 1.0}, plan), d, plan, data_quality="ok")
    assert dec["signal"] in ("BUY", "HOLD", "SELL")
    assert dec["rating"] in ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL")
    assert 0 <= dec["confidence"] <= 100
    assert 0 <= dec["total_score"] <= 100
    assert abs(sum(dec["weights_used"].values()) - 1) < 0.01


def test_buy_blocked_by_poor_rr():
    d = _daily(zigzag_uptrend())
    plan = {"risk_reward": 1.0, "stop_pct": 3}
    scores = {"trend_score": {"score": 95, "factors": []}, "price_score": {"score": 95, "factors": []}}
    dec = scoring.decide(scores, d, plan, data_quality="ok")
    assert dec["signal"] == "HOLD"
    assert any("downgraded" in w for w in dec["warnings"])


def test_no_scores_means_hold_with_zero_confidence():
    dec = scoring.decide({"trend_score": {"score": None, "factors": []}}, {}, {}, data_quality="insufficient")
    assert dec["signal"] == "HOLD" and dec["confidence"] == 0 and dec["total_score"] is None


def test_scoring_is_deterministic():
    d = _daily(zigzag_uptrend())
    plan = risk.plan_long(d, d["close"], capital=1e6, risk_pct=1, max_position_pct=20)
    a = scoring.decide(_all_scores(d, REF_FULL, {"change_pct": 1}, plan), d, plan, data_quality="ok")
    b = scoring.decide(_all_scores(d, REF_FULL, {"change_pct": 1}, plan), d, plan, data_quality="ok")
    assert a == b
