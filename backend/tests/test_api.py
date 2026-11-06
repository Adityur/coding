from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REQUIRED_ROW_FIELDS = [
    "symbol", "price", "rank", "price_score", "news_score", "volume_score", "fundamental_score", "sector_score",
    "fno_score", "rr_score", "trend_score", "entry_score", "average_score", "rating", "news_catalyst", "roe",
    "roe_growth", "sales_growth", "profit_growth", "pe", "fii_change", "dii_change", "high_zone", "hh_daily",
    "hh_hourly", "hh_15m", "hh_5m", "higher_low", "ma20", "ma50", "ma200", "ma_crossover", "ma_slope_angle",
    "breakout", "pattern", "volume", "relative_strength", "oi", "risk_reward", "entry", "stop_loss", "target",
    "signal", "confidence", "data_source", "timestamp", "ai_remark",
]


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["mode"] == "DEMO" and r["provider"]["is_live"] is False
    assert "disabled" in r["execution"]


def test_config_exposes_no_secrets(settings):
    s = replace(settings, samco_user_id="AB1234", samco_password="pw-should-not-appear", samco_yob="1990")
    c = TestClient(create_app(s))
    body = c.get("/api/config").text + c.get("/health").text
    assert "pw-should-not-appear" not in body and "AB1234" not in body
    assert c.get("/api/config").json()["execution_enabled"] is False


def test_watchlist_has_all_required_fields(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "DEMO" and d["is_live"] is False and d["data_source"] == "DEMO"
    assert d["count"] == 22 and not d["errors"]
    for row in d["rows"]:
        missing = [f for f in REQUIRED_ROW_FIELDS if f not in row]
        assert not missing, (row["symbol"], missing)
        assert row["signal"] in ("BUY", "HOLD", "SELL")
    ranks = [r["rank"] for r in d["rows"]]
    assert ranks == sorted(ranks) and ranks[0] == 1
    scores = [r["total_score"] for r in d["rows"]]
    assert scores == sorted(scores, reverse=True)


def test_watchlist_filters_and_validation(client):
    buys = client.get("/api/watchlist", params={"signal": "BUY"}).json()["rows"]
    assert all(r["signal"] == "BUY" for r in buys)
    it = client.get("/api/watchlist", params={"sector": "IT"}).json()["rows"]
    assert it and all(r["sector"] == "IT" for r in it)
    assert client.get("/api/watchlist", params={"signal": "MAYBE"}).status_code == 422
    bad = client.get("/api/watchlist", params={"sort": "nope"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_sort"
    assert client.get("/api/watchlist", params={"risk_pct": 50}).json()["error"]["code"] == "validation_error"


def test_stock_full_analysis(client):
    a = client.get("/api/stock/infy").json()
    assert a["symbol"] == "INFY" and a["data_source"] == "DEMO" and a["is_live"] is False
    assert set(a["technical"]) == {"1d", "1h", "15m", "5m"}
    assert set(a["scores"]) == {"price_score", "news_score", "volume_score", "fundamental_score", "sector_score",
                                "fno_score", "rr_score", "trend_score", "entry_score"}
    assert a["decision"]["signal"] in ("BUY", "HOLD", "SELL")
    assert a["timestamp"] and a["generated_at"]


@pytest.mark.parametrize("path", ["technical", "mtf", "fundamentals", "news", "fno", "score", "risk", "signal", "ai", "chart"])
def test_stock_sub_endpoints(client, path):
    r = client.get(f"/api/stock/TCS/{path}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "TCS"
    assert "data_source" in body or "live_data" in body


def test_technical_timeframe_param(client):
    t = client.get("/api/stock/TCS/technical", params={"timeframe": "15m"}).json()["technical"]
    assert list(t) == ["15m"]
    assert client.get("/api/stock/TCS/technical", params={"timeframe": "2h"}).status_code == 422


def test_risk_endpoint_respects_capital(client):
    r = client.get("/api/stock/TCS/risk", params={"capital": 100000, "risk_pct": 0.5}).json()["risk"]
    assert r["position"]["capital"] == 100000 and r["position"]["max_loss_at_stop"] <= 500.01


def test_chart_payload(client):
    c = client.get("/api/stock/TCS/chart", params={"timeframe": "1h", "limit": 50}).json()
    assert c["count"] == 50 and len(c["overlays"]["sma20"]) == 50
    assert {"ts", "open", "high", "low", "close", "volume"} <= set(c["candles"][0])


def test_invalid_symbol(client):
    r = client.get("/api/stock/BAD$SYM")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_symbol"


def test_symbol_outside_universe_is_analysed(client):
    a = client.get("/api/stock/ZOMATO").json()
    assert a["sector"] == "Unclassified" and a["scores"]["sector_score"]["score"] is None


def test_live_mode_without_credentials_returns_503_not_fake_data(settings):
    c = TestClient(create_app(replace(settings, demo_mode=False)))
    r = c.get("/api/stock/INFY")
    assert r.status_code == 503 and r.json()["error"]["code"] == "provider_not_configured"
    wl = c.get("/api/watchlist").json()
    assert all(row.get("error") for row in wl["rows"]) and wl["summary"]["BUY"] == 0
    assert c.get("/health").json()["provider"]["connected"] is False


def test_demo_fallback_is_labelled(settings):
    c = TestClient(create_app(replace(settings, demo_mode=False, demo_fallback=True)))
    a = c.get("/api/stock/INFY").json()
    assert a["data_source"] == "DEMO (fallback)" and a["is_live"] is False
    assert any("fallback" in w for w in a["decision"]["warnings"])


def test_custom_watchlist_roundtrip(client):
    r = client.put("/api/watchlist/symbols", json={"symbols": ["infy", "TCS", "infy"]})
    assert r.json()["symbols"] == ["INFY", "TCS"]
    assert client.get("/api/watchlist").json()["count"] == 2
    assert client.put("/api/watchlist/symbols", json={"symbols": ["bad sym!"]}).status_code == 400


def test_no_order_endpoints(client):
    for path in ("/api/orders", "/api/order", "/api/positions", "/api/trade"):
        assert client.post(path, json={}).status_code in (404, 405)


def test_websocket_quotes(client):
    with client.websocket_connect("/ws/quotes?symbols=INFY,TCS&interval=2") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "quotes"
    assert {q["symbol"] for q in msg["quotes"]} == {"INFY", "TCS"}
    assert all(q["data_source"] == "DEMO" for q in msg["quotes"])


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Swing Watchlist" in r.text


def test_unknown_api_path_uses_error_format(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_blank_env_values_fall_back_to_defaults(monkeypatch):
    from app.config import load_settings
    for k in ("UNIVERSE_FILE", "USER_WATCHLIST_FILE", "REFERENCE_DATA_FILE", "AI_MODEL", "SAMCO_BASE_URL"):
        monkeypatch.setenv(k, "")
    s = load_settings()
    assert s.universe_file.endswith("universe.json") and s.user_watchlist_file.endswith("user_watchlist.json")
    assert s.ai_model == "claude-opus-5-5" and s.samco_base_url == "https://api.stocknote.com"
