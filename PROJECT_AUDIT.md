# Project Audit

Audit date: 2026-11-06. Repository: `Adityur/coding`. Branch: `claude/swing-watchlist-trading-integration-8c3xdl`.

## Starting state

The brief described an existing project with V1, V2 and FINAL_LIVE versions, HTML prototypes, backend work and partial SAMCO/AI integration. The audit found that **the repository was empty**:

- `git log --all`: no commits
- remote branches: none (GitHub API: "Git Repository is empty")
- working tree: only `.git/`

The earlier work happened in ChatGPT and was never pushed here. The user was asked whether they would upload those files. They then changed the scope to: *"build a decision-making app for BUY/SELL/HOLD and stock selection, without execution"*. No files were uploaded, so the app was built fresh to that scope, using the field list and phase requirements in the original brief as the specification.

The sections below answer the audit questions A–L truthfully against that starting state, and record what now exists.

| | Question | Finding at start | Now |
|---|---|---|---|
| A | Existing functionality | None in repository | Full decision-support app (see FINAL_STATUS.md) |
| B | Missing functionality | Everything | Order execution and trading module: intentionally excluded at the user's request |
| C | Duplicate functionality | None (nothing present) | One canonical implementation. No V1/V2 parallel code. |
| D | Broken functionality | None present to break | 88 automated tests pass |
| E | V1 → V2 differences | Not determinable: neither version exists in the repo | n/a |
| F | HTML-only functionality | No HTML prototypes present | The frontend was designed from the brief's field list. Every field is bound to the API. |
| G | Backend-only functionality | None present | All backend features are visible in the UI, except the `/api/stock/{s}/…` sub-endpoints, which exist for integrations |
| H | Mock/demo functionality | None present | `DemoProvider` + `DemoReference`: deterministic, always labelled `DEMO` |
| I | Live-data functionality | None present | `SamcoProvider` (session, quote, OHLC, history, intraday, index, re-login, timeouts) |
| J | AI functionality | None present | `AIService`: Claude via structured output, with a rule-based fallback |
| K | Trading functionality | None present | Excluded by request. Risk planning (entry/SL/target/size) is included as decision support only. |

## L. Integration plan (as executed)

1. One canonical app at the repository root. No `V1/`, `V2/` or `FINAL_LIVE/` folders were created, because there was nothing to merge.
2. A Python FastAPI backend with a provider abstraction (`DemoProvider` / `SamcoProvider`), plus technical, scoring, risk and AI layers.
3. One dependency-free web frontend, served by the backend. The same files are reused for desktop (pywebview) and Android (Capacitor).
4. Automated tests for every layer, including real-browser end-to-end tests.
5. Docs: ARCHITECTURE, BUILD_DESKTOP, BUILD_ANDROID, FINAL_STATUS, CHANGELOG.

## If the old ChatGPT files turn up

Add them under `legacy/` and ask for a merge pass. The field names in this app follow the brief's list (`price_score`, `hh_15m`, `fii_change`, …), so mapping older HTML or columns onto `/api/watchlist` rows should be straightforward.
