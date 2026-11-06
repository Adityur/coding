# Changelog

## 1.0.0 — 2026-11-06

Initial build in an empty repository. Scope: decision support (stock selection and BUY/SELL/HOLD), no order execution.

### Added
- FastAPI backend with a provider abstraction: `DemoProvider` (deterministic, labelled DEMO), `SamcoProvider` (StockNote REST: login session, quote, daily/intraday/index candles, re-login, retries, timeouts, concurrency cap), `UnavailableProvider` (live mode without credentials returns explicit 503s).
- Reference data layer for fundamentals, FII/DII, news and F&O OI: demo generator, plus a user-maintained JSON file for live mode.
- Technical engine for 1d/1h/15m/5m: SMA/EMA, alignment, crossovers, slope angle, swing HH/HL, trend, RSI/MACD/ROC, ATR, breakout/patterns, volume confirmation, relative strength vs NIFTY 50, support/resistance, 52-week high zone, and per-timeframe data quality.
- Scoring engine: 9 transparent factor-based scores, weighted total, average, rating, guarded signal, confidence, reasons and warnings.
- Risk engine: ATR/structure-based entry, stop, target, R:R and position sizing with caps and warnings; trailing exit level for holders.
- AI service: Claude structured-output analysis that separates market data, calculated data and AI interpretation, with a deterministic rule-based fallback.
- REST API (watchlist, stock analysis and its slices, chart, quote, search, custom watchlist) and a `/ws/quotes` WebSocket.
- Web frontend: watchlist table with column groups, sorting and filters, mobile card layout, stock research page (canvas chart, score breakdown with factors, multi-timeframe, technicals, fundamentals, news, F&O, risk plan, AI panel), settings, live quote streaming, light/dark theme, PWA manifest and service worker.
- Desktop launcher (pywebview) and PyInstaller spec.
- Android Capacitor 8 project with launcher icons.
- 88 automated tests, including real-browser end-to-end tests.
- Docs: README, PROJECT_AUDIT, ARCHITECTURE, BUILD_DESKTOP, BUILD_ANDROID, FINAL_STATUS.

### Fixed during QA
- Swing-pivot detection missed pivots whose high/low tied with an adjacent bar.
- BUY was given to over-extended setups; an entry-score guard now downgrades these to HOLD.
- The target only considered the nearest resistance; it now uses the first resistance at least 1.5R away.
- Blank values in `.env` overrode file-path defaults with empty paths.
- Unknown `/api/*` paths returned a non-standard 404 body.
- Mobile layout: squashed filter dropdowns and clipped chart timeframe buttons.
