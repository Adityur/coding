import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from app.providers.base import ProviderError, ProviderNotConfigured
from app.providers.demo import DemoProvider
from app.providers.factory import UnavailableProvider, build_provider
from app.providers.reference import DemoReference, FileReference
from app.providers.samco import SamcoProvider, parse_candles

SECRET_PW = "s3cr3t-Passw0rd"


def run(coro):
    return asyncio.run(coro)


# ---------- demo ----------
def test_demo_is_deterministic_and_labelled():
    a, b = DemoProvider(), DemoProvider()
    qa, qb = run(a.get_quote("INFY")), run(b.get_quote("INFY"))
    assert qa.ltp == qb.ltp and qa.data_source == "DEMO" and qa.is_live is False


def test_demo_intraday_consistent_with_daily():
    p = DemoProvider()
    daily = run(p.get_candles("TCS", "1d"))
    m5 = run(p.get_candles("TCS", "5m"))
    assert daily[-1].close == m5[-1].close
    assert len(daily) >= 250
    for tf in ("1h", "15m"):
        bars = run(p.get_candles("TCS", tf))
        assert all(c.low <= min(c.open, c.close) and c.high >= max(c.open, c.close) for c in bars)


def test_demo_rejects_bad_timeframe():
    with pytest.raises(ProviderError):
        run(DemoProvider().get_candles("TCS", "2h"))


# ---------- factory ----------
def test_live_mode_without_credentials_never_falls_back_silently(settings):
    p = build_provider(replace(settings, demo_mode=False))
    assert isinstance(p, UnavailableProvider) and p.is_live
    with pytest.raises(ProviderNotConfigured):
        run(p.get_quote("INFY"))


# ---------- SAMCO (mocked HTTP) ----------
def samco_settings(settings):
    return replace(settings, demo_mode=False, samco_user_id="AB1234", samco_password=SECRET_PW, samco_yob="1990",
                   samco_timeout_seconds=2)


class FakeSamco:
    def __init__(self, expire_first=False, timeout_paths=(), fail_login=False):
        self.logins = 0
        self.expire_first = expire_first
        self.timeout_paths = set(timeout_paths)
        self.fail_login = fail_login
        self.seen_tokens = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/login":
            body = json.loads(request.content)
            assert body == {"userId": "AB1234", "password": SECRET_PW, "yob": "1990"}
            if self.fail_login:
                return httpx.Response(200, json={"status": "Failure", "statusMessage": f"Invalid password {SECRET_PW}"})
            self.logins += 1
            return httpx.Response(200, json={"status": "Success", "sessionToken": f"tok{self.logins}"})
        if path in self.timeout_paths:
            raise httpx.ReadTimeout("timeout", request=request)
        token = request.headers.get("x-session-token")
        self.seen_tokens.append(token)
        if self.expire_first and token == "tok1":
            return httpx.Response(401, json={"status": "Failure", "statusMessage": "Session expired"})
        if path == "/quote/getQuote":
            return httpx.Response(200, json={"status": "Success", "quoteDetails": {
                "symbolName": request.url.params["symbolName"], "lastTradedPrice": "1,512.40", "previousClose": "1500.00",
                "openValue": "1501", "highValue": "1520", "lowValue": "1495", "totalTradedVolume": "1234567",
                "lastTradedTime": "06/11/2026 15:29:59"}})
        if path == "/history/candleData":
            rows = [{"date": f"2026-01-{d:02d}", "open": "100", "high": "105", "low": "99", "close": str(100 + d), "volume": "1000"}
                    for d in range(1, 29)]
            return httpx.Response(200, json={"status": "Success", "historicalCandleData": rows})
        if path == "/intraday/candleData":
            assert request.url.params["interval"] in ("5", "15", "60")
            rows = [{"dateTime": f"2026-01-05 10:{m:02d}:00.0", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "10"}
                    for m in range(0, 30, 5)]
            return httpx.Response(200, json={"status": "Success", "intradayCandleData": rows})
        if path == "/history/indexCandleData":
            return httpx.Response(200, json={"status": "Success", "indexCandleData": [
                {"date": "2026-01-02", "open": "1", "high": "2", "low": "1", "close": "2", "volume": "0"}]})
        return httpx.Response(404, json={"status": "Failure", "statusMessage": "not found"})


def test_samco_requires_credentials(settings):
    with pytest.raises(ProviderNotConfigured):
        SamcoProvider(replace(settings, demo_mode=False))


def test_samco_quote_parsing_and_session(settings):
    fake = FakeSamco()
    p = SamcoProvider(samco_settings(settings), transport=httpx.MockTransport(fake))
    q = run(p.get_quote("INFY"))
    assert q.ltp == 1512.40 and q.prev_close == 1500 and q.change_pct == pytest.approx(0.83, abs=0.01)
    assert q.data_source == "SAMCO" and q.is_live is True
    assert q.ts.hour == 15 and q.ts.minute == 29
    assert fake.seen_tokens == ["tok1"]


def test_samco_candles_daily_intraday_and_index(settings):
    p = SamcoProvider(samco_settings(settings), transport=httpx.MockTransport(FakeSamco()))
    daily = run(p.get_candles("INFY", "1d"))
    assert len(daily) == 28 and daily[0].ts < daily[-1].ts and daily[-1].close == 128
    assert len(run(p.get_candles("INFY", "15m"))) == 6
    assert len(run(p.get_benchmark_candles("1d"))) == 1


def test_samco_relogin_on_expired_session(settings):
    fake = FakeSamco(expire_first=True)
    p = SamcoProvider(samco_settings(settings), transport=httpx.MockTransport(fake))
    q = run(p.get_quote("INFY"))
    assert q.ltp == 1512.40 and fake.logins == 2 and fake.seen_tokens == ["tok1", "tok2"]


def test_samco_timeout_becomes_provider_error(settings):
    p = SamcoProvider(samco_settings(settings), transport=httpx.MockTransport(FakeSamco(timeout_paths={"/quote/getQuote"})))
    with pytest.raises(ProviderError) as ei:
        run(p.get_quote("INFY"))
    assert ei.value.code == "provider_timeout" and ei.value.status == 504


def test_samco_errors_never_leak_password(settings):
    p = SamcoProvider(samco_settings(settings), transport=httpx.MockTransport(FakeSamco(fail_login=True)))
    with pytest.raises(ProviderError) as ei:
        run(p.get_quote("INFY"))
    assert SECRET_PW not in ei.value.message and "***" in ei.value.message
    assert SECRET_PW not in repr(samco_settings(settings))


def test_parse_candles_skips_bad_rows():
    rows = {"historicalCandleData": [{"date": "2026-01-01", "open": "1", "high": "2", "low": "0.5", "close": "1.5"},
                                     {"date": "garbage", "open": "1", "high": "2", "low": "0.5", "close": "1.5"},
                                     {"date": "2026-01-02", "open": None, "high": "2", "low": "0.5", "close": "1.5"}]}
    assert len(parse_candles(rows, ("historicalCandleData",))) == 1


# ---------- reference data ----------
def test_demo_reference_labelled():
    r = DemoReference().get("INFY", True)
    assert r["fundamentals"]["source"] == "DEMO" and r["news"]["items"][0]["headline"].startswith("[DEMO]")


def test_file_reference_missing_file_is_unavailable(tmp_path):
    r = FileReference(str(tmp_path / "nope.json")).get("INFY", True)
    assert r["fundamentals"]["roe"] is None and r["fundamentals"]["source"] == "UNAVAILABLE"


def test_file_reference_loads_and_reloads(tmp_path):
    f = tmp_path / "ref.json"
    f.write_text(json.dumps({"as_of": "2026-11-01", "source": "Manual", "symbols": {"INFY": {
        "fundamentals": {"roe": 30, "pe": 25}, "news": [{"headline": "Deal win", "sentiment": 0.5, "catalyst": True}],
        "fno": {"oi": 100, "oi_change_pct": 2, "pcr": 1.1}}}}))
    ref = FileReference(str(f))
    r = ref.get("INFY", True)
    assert r["fundamentals"]["roe"] == 30 and r["fundamentals"]["source"] == "Manual"
    assert r["news"]["catalyst"] == "Deal win" and r["news"]["sentiment"] == 0.5
    assert r["shareholding"]["fii_change"] is None
    import os
    import time
    f.write_text(json.dumps({"symbols": {"INFY": {"fundamentals": {"roe": 12}}}}))
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert ref.get("INFY", True)["fundamentals"]["roe"] == 12
