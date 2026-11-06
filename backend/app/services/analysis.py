"""Application service: orchestrates providers -> technical/scoring/risk engines -> AI remark."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from ..config import Settings
from ..engines import indicators as ind
from ..engines import risk as risk_engine
from ..engines import scoring
from ..engines.technical import analyze_timeframe, multi_timeframe_summary
from ..providers.base import IST, MarketDataProvider, ProviderError
from ..providers.demo import DemoProvider
from .ai import AIService

log = logging.getLogger("swing.analysis")

SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
INTRADAY = ("1h", "15m", "5m")


def normalize_symbol(raw: str) -> str | None:
    s = (raw or "").strip().upper()
    return s if SYMBOL_RE.match(s) else None


class _TTLCache:
    def __init__(self):
        self._d: dict = {}

    def get(self, key):
        hit = self._d.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        return None

    def set(self, key, value, ttl: float):
        if len(self._d) > 2000:
            now = time.monotonic()
            self._d = {k: v for k, v in self._d.items() if v[0] > now}
        self._d[key] = (time.monotonic() + ttl, value)

    def clear(self):
        self._d.clear()


class AnalysisService:
    def __init__(self, settings: Settings, provider: MarketDataProvider, reference, ai: AIService):
        self.settings = settings
        self.provider = provider
        self.reference = reference
        self.ai = ai
        self._demo_fallback = DemoProvider() if (settings.demo_fallback and provider.is_live) else None
        self._cache = _TTLCache()
        self._universe = self._load_universe()

    # ---------- universe / watchlist symbols ----------
    def _load_universe(self) -> dict:
        try:
            data = json.loads(Path(self.settings.universe_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {"symbols": []}
        return {s["symbol"]: s for s in data.get("symbols", []) if normalize_symbol(s.get("symbol", ""))}

    def instrument(self, symbol: str) -> dict:
        return self._universe.get(symbol) or {"symbol": symbol, "name": symbol, "sector": "Unclassified", "fno": None}

    def universe(self) -> list[dict]:
        return list(self._universe.values())

    def watchlist_symbols(self) -> list[str]:
        p = Path(self.settings.user_watchlist_file)
        if p.exists():
            try:
                syms = [normalize_symbol(s) for s in json.loads(p.read_text(encoding="utf-8")).get("symbols", [])]
                syms = [s for s in syms if s]
                if syms:
                    return syms
            except (OSError, json.JSONDecodeError, AttributeError):
                log.warning("Ignoring unreadable user watchlist file")
        return list(self._universe)

    def save_watchlist_symbols(self, symbols: list[str]) -> list[str]:
        clean = list(dict.fromkeys(s for s in (normalize_symbol(x) for x in symbols) if s))
        p = Path(self.settings.user_watchlist_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"symbols": clean}, indent=2), encoding="utf-8")
        self._cache.clear()
        return clean

    def search(self, q: str) -> list[dict]:
        q = q.strip().upper()
        return [s for s in self._universe.values() if q in s["symbol"] or q in s["name"].upper()][:25]

    # ---------- data access with caching and optional labelled demo fallback ----------
    async def _call(self, fn_name: str, *args):
        try:
            return await getattr(self.provider, fn_name)(*args), self.provider.name, self.provider.is_live
        except ProviderError:
            if self._demo_fallback is None:
                raise
            log.warning("Live provider failed for %s%s; serving labelled DEMO fallback", fn_name, args)
            return await getattr(self._demo_fallback, fn_name)(*args), "DEMO (fallback)", False

    async def candles(self, symbol: str, tf: str):
        key = ("candles", symbol, tf)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        res = await self._call("get_candles", symbol, tf)
        self._cache.set(key, res, max(self.settings.cache_ttl_seconds, 300) if tf == "1d" else self.settings.cache_ttl_seconds)
        return res

    async def benchmark(self, tf: str = "1d"):
        key = ("bench", tf)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        res = await self._call("get_benchmark_candles", tf)
        self._cache.set(key, res, max(self.settings.cache_ttl_seconds, 300))
        return res

    async def quote(self, symbol: str):
        key = ("quote", symbol)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        res = await self._call("get_quote", symbol)
        self._cache.set(key, res, min(15, self.settings.cache_ttl_seconds))
        return res

    async def _daily_technical(self, symbol: str) -> dict:
        key = ("dtech", symbol)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        (candles, _, _), bench = await asyncio.gather(self.candles(symbol, "1d"), self._safe_bench())
        tech = analyze_timeframe(candles, "1d", bench)
        self._cache.set(key, tech, max(self.settings.cache_ttl_seconds, 300))
        return tech

    async def _safe_bench(self):
        try:
            return (await self.benchmark("1d"))[0]
        except ProviderError as exc:
            log.warning("Benchmark unavailable: %s", exc.message)
            return None

    # ---------- analysis ----------
    async def _gather(self, symbol: str, timeframes: tuple[str, ...]) -> dict:
        (quote, q_src, q_live), daily = await asyncio.gather(self.quote(symbol), self._daily_technical(symbol))
        tech = {"1d": daily}
        tf_errors = {}
        intraday = [tf for tf in timeframes if tf in INTRADAY]
        results = await asyncio.gather(*(self.candles(symbol, tf) for tf in intraday), return_exceptions=True)
        for tf, res in zip(intraday, results):
            if isinstance(res, ProviderError):
                tech[tf] = None
                tf_errors[tf] = res.message
            elif isinstance(res, Exception):
                raise res
            else:
                tech[tf] = analyze_timeframe(res[0], tf)
        for tf in INTRADAY:
            if tf not in timeframes:
                tech.setdefault(tf, None)
        return {"symbol": symbol, "quote": quote, "source": q_src, "is_live": q_live, "technical": tech,
                "tf_errors": tf_errors}

    async def _sector_context(self, sector: str, symbols: list[str], known: dict[str, dict] | None = None) -> dict | None:
        peers = [s for s in symbols if self.instrument(s).get("sector") == sector]
        if not peers or sector == "Unclassified":
            return None
        known = known or {}
        techs = []
        for s in peers:
            if s in known:
                techs.append(known[s])
                continue
            try:
                techs.append(await self._daily_technical(s))
            except ProviderError:
                continue
        rs = [t["relative_strength"].get("rs20") for t in techs if t.get("relative_strength", {}).get("rs20") is not None]
        trends = [t.get("trend") for t in techs if t.get("trend")]
        return {"sector": sector, "peers": peers, "peers_evaluated": len(techs),
                "avg_rs20": round(sum(rs) / len(rs), 4) if rs else None,
                "pct_uptrend": round(100 * trends.count("UPTREND") / len(trends)) if trends else None}

    def _score(self, g: dict, sector_ctx: dict | None, capital: float, risk_pct: float) -> dict:
        symbol = g["symbol"]
        inst = self.instrument(symbol)
        quote = g["quote"].to_dict()
        tech = g["technical"]
        daily = tech["1d"]
        mtf = multi_timeframe_summary(tech)
        ref = self.reference.get(symbol, bool(inst.get("fno")))
        price = quote["ltp"]
        plan = risk_engine.plan_long(daily, price, capital=capital, risk_pct=risk_pct,
                                     max_position_pct=self.settings.max_position_pct)
        mtf_rows = mtf["timeframes"]
        scores = {
            "price_score": scoring.price_score(daily, quote),
            "news_score": scoring.news_score(ref),
            "volume_score": scoring.volume_score(daily),
            "fundamental_score": scoring.fundamental_score(ref),
            "sector_score": scoring.sector_score(sector_ctx),
            "fno_score": scoring.fno_score(ref, quote),
            "rr_score": scoring.rr_score(plan),
            "trend_score": scoring.trend_score(daily, mtf_rows),
            "entry_score": scoring.entry_score(daily, mtf_rows, plan),
        }
        dq = daily["data_quality"]["status"]
        if dq == "ok" and (g["tf_errors"] or any(tech.get(tf) is None for tf in self.settings.watchlist_timeframes if tf != "1d")):
            dq = "partial"
        decision = scoring.decide(scores, daily, plan, data_quality=dq)
        warnings = list(decision["warnings"])
        for tf, msg in g["tf_errors"].items():
            warnings.append(f"{tf} data unavailable: {msg}")
        if not g["is_live"]:
            warnings.insert(0, "DEMO data - synthetic prices, not live market data." if g["source"] == "DEMO"
                            else "Live provider failed; showing labelled DEMO fallback data.")
        decision["warnings"] = warnings
        analysis = {
            "symbol": symbol, "name": inst.get("name"), "sector": inst.get("sector"), "fno_eligible": inst.get("fno"),
            "quote": quote, "data_source": g["source"], "is_live": g["is_live"],
            "mode": "LIVE" if g["is_live"] else "DEMO", "timestamp": quote["ts"],
            "generated_at": datetime.now(IST).isoformat(),
            "technical": tech, "multi_timeframe": mtf, "reference": ref, "sector_context": sector_ctx,
            "scores": scores, "decision": decision,
            "risk": plan if decision["signal"] == "BUY" else {**plan, "note": "Hypothetical long plan; signal is not BUY.",
                                                             "exit_levels": risk_engine.exit_levels(daily, price)},
            "data_quality": {"overall": dq, "by_timeframe": {tf: (a or {}).get("data_quality", {}).get("status", "unavailable")
                                                             for tf, a in tech.items()}},
        }
        analysis["ai_remark"] = self.ai.remark(analysis)
        analysis["row"] = self.to_row(analysis)
        return analysis

    async def analyze(self, symbol: str, *, capital: float | None = None, risk_pct: float | None = None) -> dict:
        capital = capital or self.settings.default_capital
        risk_pct = risk_pct or self.settings.default_risk_pct
        key = ("analysis", symbol, capital, risk_pct)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        g = await self._gather(symbol, self.settings.watchlist_timeframes)
        ctx = await self._sector_context(self.instrument(symbol).get("sector"), self.watchlist_symbols() + [symbol],
                                         {symbol: g["technical"]["1d"]})
        result = self._score(g, ctx, capital, risk_pct)
        self._cache.set(key, result, self.settings.cache_ttl_seconds)
        return result

    async def watchlist(self, *, capital: float | None = None, risk_pct: float | None = None) -> dict:
        capital = capital or self.settings.default_capital
        risk_pct = risk_pct or self.settings.default_risk_pct
        symbols = self.watchlist_symbols()
        key = ("watchlist", tuple(symbols), capital, risk_pct)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        gathered = await asyncio.gather(*(self._gather(s, self.settings.watchlist_timeframes) for s in symbols),
                                        return_exceptions=True)
        ok = {g["symbol"]: g for g in gathered if isinstance(g, dict)}
        known = {s: g["technical"]["1d"] for s, g in ok.items()}
        ctx_cache: dict[str, dict | None] = {}
        rows, errors = [], []
        for sym, g in zip(symbols, gathered):
            if not isinstance(g, dict):
                msg = g.message if isinstance(g, ProviderError) else f"internal error ({type(g).__name__})"
                if not isinstance(g, ProviderError):
                    log.exception("Analysis failed for %s", sym, exc_info=g)
                errors.append({"symbol": sym, "error": msg})
                rows.append({"symbol": sym, **{k: self.instrument(sym).get(k) for k in ("name", "sector")},
                             "error": msg, "signal": None, "data_quality": "error"})
                continue
            sector = self.instrument(sym).get("sector")
            if sector not in ctx_cache:
                ctx_cache[sector] = await self._sector_context(sector, symbols, known)
            a = self._score(g, ctx_cache[sector], capital, risk_pct)
            self._cache.set(("analysis", sym, capital, risk_pct), a, self.settings.cache_ttl_seconds)
            rows.append(a["row"])
        ranked = sorted((r for r in rows if r.get("total_score") is not None), key=lambda r: -r["total_score"])
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
        sources = sorted({r["data_source"] for r in rows if r.get("data_source")})
        result = {
            "generated_at": datetime.now(IST).isoformat(), "mode": self.settings.mode,
            "data_source": ", ".join(sources) or self.provider.name,
            "is_live": bool(rows) and all(r.get("is_live") for r in rows if "error" not in r),
            "count": len(rows), "errors": errors, "capital": capital, "risk_pct": risk_pct,
            "summary": {s: sum(1 for r in rows if r.get("signal") == s) for s in ("BUY", "HOLD", "SELL")},
            "timeframes": list(self.settings.watchlist_timeframes),
            "rows": sorted(rows, key=lambda r: r.get("rank") or 10**6),
        }
        self._cache.set(key, result, self.settings.cache_ttl_seconds)
        return result

    @staticmethod
    def to_row(a: dict) -> dict:
        tech = a["technical"]
        d = tech["1d"]
        s = a["scores"]
        ref = a["reference"]
        dec = a["decision"]
        plan = a["risk"]
        mas = d.get("moving_averages", {})

        def hh(tf):
            return ((tech.get(tf) or {}).get("structure") or {}).get("higher_high")

        def hl(tf):
            return ((tech.get(tf) or {}).get("structure") or {}).get("higher_low")

        xo = d.get("ma_crossover") or {}
        return {
            "symbol": a["symbol"], "name": a["name"], "sector": a["sector"],
            "price": a["quote"]["ltp"], "change_pct": a["quote"].get("change_pct"), "rank": None,
            "price_score": s["price_score"]["score"], "news_score": s["news_score"]["score"],
            "volume_score": s["volume_score"]["score"], "fundamental_score": s["fundamental_score"]["score"],
            "sector_score": s["sector_score"]["score"], "fno_score": s["fno_score"]["score"],
            "rr_score": s["rr_score"]["score"], "trend_score": s["trend_score"]["score"],
            "entry_score": s["entry_score"]["score"], "average_score": dec["average_score"],
            "total_score": dec["total_score"], "rating": dec["rating"], "signal": dec["signal"],
            "confidence": dec["confidence"],
            "news_catalyst": ref["news"].get("catalyst"), "news_sentiment": ref["news"].get("sentiment"),
            "roe": ref["fundamentals"].get("roe"), "roe_growth": ref["fundamentals"].get("roe_growth"),
            "sales_growth": ref["fundamentals"].get("sales_growth"), "profit_growth": ref["fundamentals"].get("profit_growth"),
            "pe": ref["fundamentals"].get("pe"), "fii_change": ref["shareholding"].get("fii_change"),
            "dii_change": ref["shareholding"].get("dii_change"),
            "high_zone": (d.get("high_zone") or {}).get("in_high_zone"),
            "pct_from_52w_high": (d.get("high_zone") or {}).get("pct_from_high"),
            "hh_daily": hh("1d"), "hh_hourly": hh("1h"), "hh_15m": hh("15m"), "hh_5m": hh("5m"),
            "higher_low": hl("1d"), "hl_hourly": hl("1h"), "hl_15m": hl("15m"), "hl_5m": hl("5m"),
            "trend": d.get("trend"), "mtf_alignment": a["multi_timeframe"].get("alignment"),
            "ma20": mas.get("sma20"), "ma50": mas.get("sma50"), "ma200": mas.get("sma200"),
            "ma_alignment": d.get("ma_alignment"),
            "ma_crossover": xo.get("signal") if xo.get("signal") != "none" else (f"EMA9 {xo['state']} EMA21" if xo.get("state") else None),
            "ma_slope_angle": (d.get("slope") or {}).get("sma20_angle_deg"),
            "breakout": (d.get("breakout") or {}).get("status"), "pattern": d.get("pattern"),
            "volume": (d.get("volume") or {}).get("last"), "volume_ratio": (d.get("volume") or {}).get("ratio"),
            "relative_strength": (d.get("relative_strength") or {}).get("rs20"),
            "rsi14": (d.get("momentum") or {}).get("rsi14"),
            "oi": ref["fno"].get("oi"), "oi_change_pct": ref["fno"].get("oi_change_pct"),
            "fno_buildup": s["fno_score"].get("buildup"),
            "risk_reward": plan.get("risk_reward"), "entry": plan.get("entry"), "stop_loss": plan.get("stop_loss"),
            "target": plan.get("target"),
            "data_source": a["data_source"], "is_live": a["is_live"], "mode": a["mode"], "timestamp": a["timestamp"],
            "ai_remark": a["ai_remark"], "data_quality": a["data_quality"]["overall"],
            "reasons": dec["reasons"][:3], "warnings": dec["warnings"][:3],
        }

    async def chart(self, symbol: str, tf: str, limit: int) -> dict:
        candles, src, live = await self.candles(symbol, tf)
        closes = [c.close for c in candles]
        sma20, sma50, sma200 = ind.sma(closes, 20), ind.sma(closes, 50), ind.sma(closes, 200)
        candles, sma20, sma50, sma200 = candles[-limit:], sma20[-limit:], sma50[-limit:], sma200[-limit:]
        r2 = lambda xs: [None if x is None else round(x, 2) for x in xs]  # noqa: E731
        return {"symbol": symbol, "timeframe": tf, "data_source": src, "is_live": live,
                "timestamp": candles[-1].ts.isoformat() if candles else None, "count": len(candles),
                "candles": [c.to_dict() for c in candles],
                "overlays": {"sma20": r2(sma20), "sma50": r2(sma50), "sma200": r2(sma200)}}

    async def quotes(self, symbols: list[str]) -> list[dict]:
        out = []
        results = await asyncio.gather(*(self.quote(s) for s in symbols), return_exceptions=True)
        for s, r in zip(symbols, results):
            if isinstance(r, tuple):
                q = r[0].to_dict()
                q["data_source"] = r[1]
                q["is_live"] = r[2]
                out.append(q)
            else:
                out.append({"symbol": s, "error": r.message if isinstance(r, ProviderError) else "unavailable"})
        return out
