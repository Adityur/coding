import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import DATA_DIR, Settings  # noqa: E402
from app.providers.base import IST, Candle  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings(demo_mode=True, universe_file=str(DATA_DIR / "universe.json"),
                    user_watchlist_file=str(tmp_path / "user_watchlist.json"),
                    reference_data_file=str(tmp_path / "reference.json"), anthropic_api_key_present=False)


def make_candles(closes, start=None, step=timedelta(days=1), spread=0.01, volumes=None):
    start = start or datetime(2025, 1, 1, 15, 30, tzinfo=IST)
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(Candle(start + step * i, o, max(o, c) * (1 + spread), min(o, c) * (1 - spread), c,
                          (volumes[i] if volumes else 1_000_000)))
        prev = c
    return out


def zigzag_uptrend(n=260, base=100.0):
    """Rising price with regular pullbacks so swing highs/lows form a higher-high/higher-low staircase."""
    closes, p = [], base
    for i in range(n):
        p *= 1.012 if (i % 10) < 7 else 0.985
        closes.append(round(p, 2))
    return closes


def zigzag_downtrend(n=260, base=300.0):
    closes, p = [], base
    for i in range(n):
        p *= 0.988 if (i % 10) < 7 else 1.015
        closes.append(round(p, 2))
    return closes
