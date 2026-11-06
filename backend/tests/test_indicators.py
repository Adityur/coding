import math

from app.engines import indicators as ind


def test_sma_known_values():
    assert ind.sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_insufficient_history_is_none():
    assert ind.sma([1, 2], 5) == [None, None]


def test_ema_seeds_with_sma_then_smooths():
    out = ind.ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == 2.0
    assert math.isclose(out[3], 4 * 0.5 + 2.0 * 0.5)


def test_rsi_extremes():
    assert ind.rsi(list(range(1, 30)), 14)[-1] == 100.0
    falling = ind.rsi(list(range(30, 1, -1)), 14)[-1]
    assert falling < 1


def test_atr_constant_range():
    highs, lows, closes = [11.0] * 30, [9.0] * 30, [10.0] * 30
    assert math.isclose(ind.atr(highs, lows, closes, 14)[-1], 2.0)


def test_slope_angle_convention_1pct_per_bar_is_45deg():
    series = [100 * (1 + 0.01 * i) for i in range(10)]
    pct, ang = ind.slope_angle(series, 10)
    assert 0.9 < pct < 1.0  # slope relative to latest value
    assert 40 < ang < 45


def test_slope_angle_insufficient():
    assert ind.slope_angle([None, 1, 2], 10) == (None, None)


def test_pivots_detect_swing_points():
    highs = [1, 2, 5, 2, 1, 2, 7, 2, 1]
    lows = [h - 0.5 for h in highs]
    ph, pl = ind.pivots(highs, lows, 2)
    assert (2, 5) in ph and (6, 7) in ph
    assert any(i == 4 for i, _ in pl)


def test_macd_lengths_align():
    closes = [100 + i for i in range(60)]
    line, sig, hist = ind.macd(closes)
    assert len(line) == len(sig) == len(hist) == 60
    assert hist[-1] is not None
