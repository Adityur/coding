# Architecture

```
Frontend  (frontend/: index.html, js/app.js, js/api.js, js/chart.js; no build step)
   │   same files run in: browser · desktop window (pywebview) · Android (Capacitor)
   ▼   REST (JSON) + WebSocket /ws/quotes
API  (backend/app/api/routes.py; validation, error format, timestamps, data_source)
   ▼
Application services  (backend/app/services/)
   ├── analysis.py   orchestration, caching, watchlist ranking, sector context, demo fallback
   └── ai.py         AI service layer (Claude or rule-based); used by the API, never by UI code
   ▼
Analysis engines  (backend/app/engines/)
   ├── indicators.py  SMA/EMA/RSI/ATR/MACD/slope/pivots (pure functions)
   ├── technical.py   per-timeframe analysis + multi-timeframe summary
   ├── scoring.py     9 transparent scores → total, rating, signal, confidence
   └── risk.py        entry / stop / target / R:R / position size
   ▼
Data providers  (backend/app/providers/)
   ├── base.py        MarketDataProvider interface, Candle, Quote, ProviderError
   ├── demo.py        DemoProvider: deterministic synthetic data, labelled DEMO
   ├── samco.py       SamcoProvider: StockNote REST API
   ├── reference.py   fundamentals/news/FII-DII/F&O: DemoReference | FileReference
   └── factory.py     picks the provider from DEMO_MODE / MARKET_DATA_PROVIDER
   ▼
SAMCO StockNote API · reference JSON file · Anthropic API
```

## Design rules

- **No fake live data.** `DEMO_MODE=false` without credentials gives an `UnavailableProvider`: endpoints return `503 provider_not_configured` and the UI shows a red badge. A labelled `DEMO (fallback)` is used only when `DEMO_FALLBACK=true`.
- **Unknown means null.** Indicators return `None` when history is too short. Each timeframe reports `data_quality: ok | partial | insufficient` and lists what is missing. Scores with no usable inputs are `null` and are left out of the total.
- **No random numbers in decisions.** Demo data is a seeded random walk per (symbol, day). Everything downstream is deterministic.
- **Secrets stay server-side.** Credentials are read from the environment / `.env` only. They are excluded from dataclass repr, redacted from logs, and replaced with `***` in provider errors. `/health` and `/api/config` report booleans only.
- **No execution.** The router has no order, position or trade routes. A test asserts this.

## Provider contract

```python
class MarketDataProvider:
    name: str; is_live: bool
    async def get_quote(symbol) -> Quote                  # ltp, o/h/l, prev_close, change, volume, ts, data_source, is_live
    async def get_candles(symbol, timeframe) -> [Candle]  # "1d" | "1h" | "15m" | "5m"
    async def get_benchmark_candles(timeframe) -> [Candle]  # NIFTY 50
    async def status() -> dict
```

SAMCO endpoints used: `POST /login` (userId, password, yob → `sessionToken`, sent as the `x-session-token` header), `GET /quote/getQuote`, `GET /history/candleData`, `GET /intraday/candleData` (interval 5/15/60), `GET /history/indexCandleData`, `GET /intraday/indexCandleData`. Session expiry (401/403, or a "session/token" failure) triggers one re-login. Timeouts and network errors retry with backoff and then raise `ProviderError` (504/502). Concurrency is capped by `SAMCO_MAX_CONCURRENCY`.

Live quotes reach the UI through the app's own WebSocket (`/ws/quotes`), which polls provider quotes every *n* seconds. The client reconnects with exponential backoff (1 s → 30 s). SAMCO's native binary streaming socket is not used.

## Technical engine (per timeframe)

| Output | Definition |
|---|---|
| Moving averages | SMA 20/50/200, EMA 9/21; `price_above` per MA |
| MA alignment | bullish if price > SMA20 > SMA50 > SMA200 (uses those available, min 3); bearish if reversed |
| MA crossover | EMA9/EMA21 cross within 5 bars; golden/death cross (SMA50/200) within 10 bars |
| Slope / angle | linear-regression slope of last 10 SMA values as % of price per bar; angle = atan(%/bar), so 1 %/bar = 45° |
| Higher high / higher low | swing pivots (window ±3 bars); last vs previous pivot; a close above the last pivot high counts as HH |
| Trend | UPTREND = HH & HL & close > SMA50; DOWNTREND = LH & LL & close < SMA50; otherwise SIDEWAYS |
| Momentum | RSI14 (Wilder), MACD 12/26/9, ROC10 |
| Breakout | close > prior 20-bar high = BREAKOUT; < 20-bar low = BREAKDOWN; 10-bar range < 2.5×ATR = TIGHT_RANGE; within 2 % of high = NEAR_HIGH |
| Volume | last / 20-bar average; confirmation = ratio ≥ 1.5 on an up bar; 20-bar up/down volume ratio |
| Relative strength | (1+stock return)/(1+NIFTY return) over 20 and 60 days, aligned by date |
| Support / resistance | nearest swing lows below / highs above price (last 120 bars), falling back to the 20-bar range |
| High zone | within 5 % of the 252-bar (52-week) high |

## Scoring engine

Each score is `100 × points earned ÷ points possible`, counting only factors that have data. Every factor (`name, value, points, max, note`) is returned by `/api/stock/{s}/score` and shown in the UI.

| Score | Weight | Factors (max points) |
|---|---|---|
| trend_score | 18 % | daily trend (25), MA alignment (15), SMA20 angle (10), daily HH (10), daily HL (10), EMA9>21 (5), 1h trend (10), 15m trend (6), 5m trend (4) |
| price_score | 10 % | above SMA20/50/200 (10 each), distance from 52w high (15), ROC10 (10), today's change (5) |
| volume_score | 12 % | last-bar volume ratio (15; 0 if heavy volume on a down bar), 20-bar up/down volume (15), confirmed up bar (10) |
| entry_score | 12 % | extension above SMA20 in ATRs (25), daily RSI zone (20), 15m trend (10), 5m trend (5), breakout/base status (15), stop distance (10) |
| rr_score | 12 % | R:R piecewise: 0.5→0, 1→30, 1.5→55, 2→75, ≥3→100 |
| fundamental_score | 12 % | ROE (20), ROE growth (10), sales growth (15), profit growth (20), PE vs sector PE (10), FII Δ (5), DII Δ (5) |
| sector_score | 8 % | average RS20 of sector peers (20), % of peers in uptrend (15) |
| news_score | 8 % | average sentiment (20), catalyst direction (10) |
| fno_score | 8 % | price/OI buildup: long buildup 25, short covering 18, long unwinding 9, short buildup 3; PCR band (10). Not applicable for non-F&O stocks. |

- **total_score**: weighted mean of available scores, with weights renormalised. **average_score**: simple mean.
- **Signal**: BUY if total ≥ 62 **and** the daily trend is not DOWN **and** R:R ≥ 1.5 **and** entry score ≥ 35 **and** data quality is not insufficient. If total ≥ 62 but a check fails, it is downgraded to HOLD with the reason. SELL if total < 40, or the daily trend is DOWN with bearish MAs and total < 50. Otherwise HOLD.
- **Rating**: STRONG BUY (BUY with total ≥ 75), BUY, HOLD, SELL, STRONG SELL (SELL with total < 30).
- **Confidence** = 100 × data-quality factor × (0.4 × weight coverage + 0.3 × score agreement + 0.3 × conviction), where agreement = 1 − stdev/35 and conviction = |total − 50| / 30.

## Risk engine

- Entry = last price.
- Stop = nearest support − 0.25×ATR if that lies 1–3 ATR below entry, otherwise entry − 2×ATR.
- Target = the first swing resistance at least 1.5R away, otherwise a 2R projection. Target 2 = 3R.
- Position size = floor(capital × risk % ÷ risk per share), capped at `MAX_POSITION_PCT` of capital.
- Warnings: stop > 8 %, R:R < 1.5, resistance closer than 1.5R, zero quantity.
- For non-BUY signals the plan is marked hypothetical and a trailing exit level for holders is added.

## AI service

`AIService.analyze()` builds a JSON fact sheet in three sections (`market_data`, `calculated_data`, `reference_data`) and calls Claude (`claude-opus-5-5`, `client.beta.messages.parse` with a Pydantic schema, adaptive thinking at `AI_EFFORT`, `fallbacks="default"` for server-side refusal fallback). The system prompt forbids facts that are not in the JSON. If the model refuses, errors, or no key is configured, a deterministic rule-based interpreter returns the same schema. Results are cached for 15 minutes per (symbol, data timestamp). Response sections: `live_data`, `calculated_data`, `reference_data`, `ai_interpretation`.

## API reference

| Method & path | Purpose |
|---|---|
| `GET /health` | status, mode, provider connection, AI engine |
| `GET /api/config` | non-secret runtime config |
| `GET /api/universe` · `GET /api/search?q=` | instruments |
| `GET /api/watchlist?signal&sector&min_score&sort&order&limit&capital&risk_pct` | ranked rows with every watchlist field |
| `GET` / `PUT /api/watchlist/symbols` | custom watchlist |
| `GET /api/quote/{symbol}` | quote |
| `GET /api/stock/{symbol}` | full analysis |
| `GET /api/stock/{symbol}/technical?timeframe=` · `/mtf` · `/fundamentals` · `/news` · `/fno` · `/score` · `/risk?capital&risk_pct` · `/signal` · `/ai?llm=` · `/chart?timeframe&limit` | slices of the analysis |
| `WS /ws/quotes?symbols=A,B&interval=5` | quote stream |

Errors always use `{"error": {"code", "message", "details?"}, "timestamp"}`. Codes: `invalid_symbol`, `validation_error`, `invalid_sort`, `provider_not_configured` (503), `provider_timeout` (504), `provider_error` (502), `not_found`, `internal_error`.

Stock responses include `data_source`, `is_live`, `mode`, `timestamp` (time of the market data) and `generated_at`.

## Repository layout

```
run.py                  start the server
backend/app/            API, services, engines, providers
backend/tests/          88 tests (pytest; browser tests use Playwright)
frontend/               web UI (shared by all targets) + PWA manifest/service worker
data/universe.json      default watchlist (22 NSE large caps, sector, F&O flag)
desktop/                pywebview launcher + PyInstaller spec
mobile/                 Capacitor Android project (android/ is committed)
```
