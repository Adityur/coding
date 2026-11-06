"""REST + WebSocket API. Decision support only: there are no order/execution endpoints by design."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..engines import risk as risk_engine
from ..providers.base import IST, ProviderError
from ..services.analysis import AnalysisService, normalize_symbol

router = APIRouter()
Timeframe = Literal["1d", "1h", "15m", "5m"]
SORTABLE = {"rank", "total_score", "average_score", "confidence", "price", "change_pct", "trend_score", "entry_score",
            "rr_score", "volume_score", "price_score", "fundamental_score", "news_score", "sector_score", "fno_score",
            "risk_reward", "relative_strength", "symbol"}


def svc(request: Request) -> AnalysisService:
    return request.app.state.analysis


def _sym(symbol: str) -> str:
    s = normalize_symbol(symbol)
    if not s:
        raise HTTPException(status_code=400, detail={"code": "invalid_symbol",
                                                     "message": "Symbol must be 1-20 chars: A-Z, 0-9, & or -."})
    return s


def _meta(a: dict) -> dict:
    return {"symbol": a["symbol"], "name": a["name"], "sector": a["sector"], "data_source": a["data_source"],
            "is_live": a["is_live"], "mode": a["mode"], "timestamp": a["timestamp"], "generated_at": a["generated_at"]}


@router.get("/health")
async def health(request: Request):
    s = request.app.state.settings
    return {"status": "ok", "time": datetime.now(IST).isoformat(), "mode": s.mode, "demo_mode": s.demo_mode,
            "provider": await request.app.state.provider.status(), "ai": request.app.state.ai.status(),
            "execution": "disabled (decision-support app; no order placement)"}


@router.get("/api/config")
async def config(request: Request):
    s = request.app.state.settings
    return {"mode": s.mode, "demo_mode": s.demo_mode, "demo_fallback": s.demo_fallback, "provider": s.provider.upper(),
            "samco_credentials_configured": s.samco_configured, "ai": request.app.state.ai.status(),
            "default_capital": s.default_capital, "default_risk_pct": s.default_risk_pct,
            "max_position_pct": s.max_position_pct, "timeframes": list(s.watchlist_timeframes),
            "cache_ttl_seconds": s.cache_ttl_seconds, "execution_enabled": False}


@router.get("/api/universe")
async def universe(request: Request):
    return {"symbols": svc(request).universe(), "watchlist": svc(request).watchlist_symbols()}


@router.get("/api/search")
async def search(request: Request, q: str = Query(..., min_length=1, max_length=30)):
    return {"query": q, "results": svc(request).search(q)}


class WatchlistSymbols(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=100)


@router.get("/api/watchlist/symbols")
async def get_watchlist_symbols(request: Request):
    return {"symbols": svc(request).watchlist_symbols()}


@router.put("/api/watchlist/symbols")
async def put_watchlist_symbols(request: Request, body: WatchlistSymbols):
    invalid = [s for s in body.symbols if not normalize_symbol(s)]
    if invalid:
        raise HTTPException(status_code=400, detail={"code": "invalid_symbol", "message": f"Invalid symbols: {invalid[:10]}"})
    return {"symbols": svc(request).save_watchlist_symbols(body.symbols)}


@router.get("/api/watchlist")
async def watchlist(request: Request,
                    signal: Literal["BUY", "HOLD", "SELL"] | None = None,
                    sector: str | None = Query(None, max_length=40),
                    min_score: float | None = Query(None, ge=0, le=100),
                    sort: str = Query("rank"),
                    order: Literal["asc", "desc"] = "asc",
                    limit: int = Query(100, ge=1, le=500),
                    capital: float | None = Query(None, gt=0, le=1e11),
                    risk_pct: float | None = Query(None, ge=0.1, le=5)):
    if sort not in SORTABLE:
        raise HTTPException(status_code=400, detail={"code": "invalid_sort", "message": f"sort must be one of {sorted(SORTABLE)}"})
    data = await svc(request).watchlist(capital=capital, risk_pct=risk_pct)
    rows = data["rows"]
    if signal:
        rows = [r for r in rows if r.get("signal") == signal]
    if sector:
        rows = [r for r in rows if (r.get("sector") or "").lower() == sector.lower()]
    if min_score is not None:
        rows = [r for r in rows if (r.get("total_score") or -1) >= min_score]
    present = [r for r in rows if r.get(sort) is not None]
    absent = [r for r in rows if r.get(sort) is None]
    present.sort(key=lambda r: r[sort], reverse=(order == "desc"))
    return {**data, "rows": (present + absent)[:limit], "filtered_count": len(rows)}


@router.get("/api/quote/{symbol}")
async def quote(request: Request, symbol: str):
    q, src, live = await svc(request).quote(_sym(symbol))
    return {**q.to_dict(), "data_source": src, "is_live": live}


@router.get("/api/stock/{symbol}")
async def stock(request: Request, symbol: str, capital: float | None = Query(None, gt=0, le=1e11),
                risk_pct: float | None = Query(None, ge=0.1, le=5)):
    a = await svc(request).analyze(_sym(symbol), capital=capital, risk_pct=risk_pct)
    return {k: v for k, v in a.items()}


@router.get("/api/stock/{symbol}/technical")
async def technical(request: Request, symbol: str, timeframe: Timeframe | None = None):
    a = await svc(request).analyze(_sym(symbol))
    tech = a["technical"] if timeframe is None else {timeframe: a["technical"].get(timeframe)}
    return {**_meta(a), "technical": tech}


@router.get("/api/stock/{symbol}/mtf")
async def mtf(request: Request, symbol: str):
    a = await svc(request).analyze(_sym(symbol))
    return {**_meta(a), "multi_timeframe": a["multi_timeframe"]}


@router.get("/api/stock/{symbol}/fundamentals")
async def fundamentals(request: Request, symbol: str):
    a = await svc(request).analyze(_sym(symbol))
    return {**_meta(a), "fundamentals": a["reference"]["fundamentals"], "shareholding": a["reference"]["shareholding"],
            "score": a["scores"]["fundamental_score"]}


@router.get("/api/stock/{symbol}/news")
async def news(request: Request, symbol: str):
    a = await svc(request).analyze(_sym(symbol))
    return {**_meta(a), "news": a["reference"]["news"], "score": a["scores"]["news_score"]}


@router.get("/api/stock/{symbol}/fno")
async def fno(request: Request, symbol: str):
    a = await svc(request).analyze(_sym(symbol))
    return {**_meta(a), "fno": a["reference"]["fno"], "score": a["scores"]["fno_score"]}


@router.get("/api/stock/{symbol}/score")
async def score(request: Request, symbol: str):
    a = await svc(request).analyze(_sym(symbol))
    return {**_meta(a), "scores": a["scores"], "decision": a["decision"], "sector_context": a["sector_context"]}


@router.get("/api/stock/{symbol}/risk")
async def risk(request: Request, symbol: str, capital: float | None = Query(None, gt=0, le=1e11),
               risk_pct: float | None = Query(None, ge=0.1, le=5)):
    s = request.app.state.settings
    a = await svc(request).analyze(_sym(symbol))
    plan = risk_engine.plan_long(a["technical"]["1d"], a["quote"]["ltp"], capital=capital or s.default_capital,
                                 risk_pct=risk_pct or s.default_risk_pct, max_position_pct=s.max_position_pct)
    return {**_meta(a), "signal": a["decision"]["signal"], "risk": plan}


@router.get("/api/stock/{symbol}/signal")
async def signal(request: Request, symbol: str):
    a = await svc(request).analyze(_sym(symbol))
    d = a["decision"]
    return {**_meta(a), "signal": d["signal"], "rating": d["rating"], "confidence": d["confidence"],
            "total_score": d["total_score"], "reasons": d["reasons"], "warnings": d["warnings"], "ai_remark": a["ai_remark"]}


@router.get("/api/stock/{symbol}/ai")
async def ai(request: Request, symbol: str, llm: bool = True):
    a = await svc(request).analyze(_sym(symbol))
    return await request.app.state.ai.analyze(a, use_llm=llm)


@router.get("/api/stock/{symbol}/chart")
async def chart(request: Request, symbol: str, timeframe: Timeframe = "1d", limit: int = Query(200, ge=20, le=1000)):
    return await svc(request).chart(_sym(symbol), timeframe, limit)


@router.websocket("/ws/quotes")
async def ws_quotes(websocket: WebSocket):
    await websocket.accept()
    raw = websocket.query_params.get("symbols", "")
    symbols = [s for s in (normalize_symbol(x) for x in raw.split(",")) if s][:50]
    try:
        interval = max(2.0, min(60.0, float(websocket.query_params.get("interval", "5"))))
    except ValueError:
        interval = 5.0
    service: AnalysisService = websocket.app.state.analysis
    if not symbols:
        symbols = service.watchlist_symbols()[:50]
    try:
        while True:
            try:
                quotes = await service.quotes(symbols)
                await websocket.send_json({"type": "quotes", "time": datetime.now(IST).isoformat(), "quotes": quotes})
            except ProviderError as exc:
                await websocket.send_json({"type": "error", "code": exc.code, "message": exc.message})
            await asyncio.sleep(interval)
    except (WebSocketDisconnect, RuntimeError):
        return
