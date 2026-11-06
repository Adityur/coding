from datetime import timedelta

from app.engines.technical import analyze_timeframe, multi_timeframe_summary, relative_strength
from conftest import make_candles, zigzag_downtrend, zigzag_uptrend


def test_uptrend_detected_with_hh_hl():
    a = analyze_timeframe(make_candles(zigzag_uptrend()), "1d")
    assert a["trend"] == "UPTREND"
    assert a["structure"]["higher_high"] is True
    assert a["structure"]["higher_low"] is True
    assert a["ma_alignment"] == "bullish"
    assert a["slope"]["sma20_angle_deg"] > 0
    assert a["data_quality"]["status"] == "ok"


def test_downtrend_detected():
    a = analyze_timeframe(make_candles(zigzag_downtrend()), "1d")
    assert a["trend"] == "DOWNTREND"
    assert a["structure"]["lower_low"] is True
    assert a["ma_alignment"] == "bearish"


def test_insufficient_data_returns_unknowns_not_fake_values():
    a = analyze_timeframe(make_candles([100 + i for i in range(10)]), "1h")
    assert a["data_quality"]["status"] == "insufficient"
    assert a["trend"] is None
    assert a["structure"]["higher_high"] is None
    assert a["atr14"] is None


def test_partial_history_marks_missing_ma200():
    a = analyze_timeframe(make_candles(zigzag_uptrend(120)), "1d")
    assert a["moving_averages"]["sma200"] is None
    assert "sma200" in a["data_quality"]["missing"]
    assert a["moving_averages"]["sma50"] is not None


def test_breakout_and_volume_confirmation():
    closes = [100.0] * 40 + [100.5] * 20 + [108.0]
    vols = [1_000_000] * 60 + [3_000_000]
    a = analyze_timeframe(make_candles(closes, spread=0.001, volumes=vols), "1d")
    assert a["breakout"]["status"] == "BREAKOUT"
    assert a["volume"]["confirmation"] is True
    assert a["pattern"] == "Breakout with volume"


def test_high_zone_only_on_daily():
    c = make_candles(zigzag_uptrend())
    assert analyze_timeframe(c, "1d")["high_zone"]["in_high_zone"] in (True, False)
    assert analyze_timeframe(c, "1h")["high_zone"] is None


def test_relative_strength_vs_benchmark():
    stock = make_candles([100 * 1.01 ** i for i in range(80)])
    bench = make_candles([100.0] * 80)
    rs = relative_strength(stock, bench)
    assert rs["rs20"] > 1 and rs["outperforming"] is True


def test_relative_strength_without_benchmark_is_null():
    rs = relative_strength(make_candles([100.0] * 80), None)
    assert rs["rs20"] is None and rs["outperforming"] is None


def test_support_below_and_resistance_above_price():
    a = analyze_timeframe(make_candles(zigzag_uptrend()), "1d")
    assert all(s < a["close"] for s in a["support"])
    assert all(r > a["close"] for r in a["resistance"])


def test_multi_timeframe_alignment():
    up = analyze_timeframe(make_candles(zigzag_uptrend()), "1d")
    up_h = analyze_timeframe(make_candles(zigzag_uptrend(), step=timedelta(hours=1)), "1h")
    s = multi_timeframe_summary({"1d": up, "1h": up_h, "15m": None})
    assert s["alignment"] == "ALIGNED_UP"
    assert "15m" not in s["timeframes"]
