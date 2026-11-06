# Swing Watchlist AI

A decision-support app for swing trading NSE stocks. It ranks a watchlist and gives a **BUY / HOLD / SELL** signal for each stock, with transparent scores, multi-timeframe technicals, fundamentals, news, F&O, a risk plan, and an AI explanation.

**It never places orders.** There are no order or execution endpoints. SELL means "exit / avoid" for holders.

One codebase runs on three targets:

| Target | How |
|---|---|
| Web (any browser) | `python run.py` → open http://127.0.0.1:8000 |
| Desktop (Windows/macOS/Linux) | native window via pywebview, packaged with PyInstaller — see [BUILD_DESKTOP.md](BUILD_DESKTOP.md) |
| Android | Capacitor shell around the same frontend, talking to your server — see [BUILD_ANDROID.md](BUILD_ANDROID.md) |

## Quick start (demo data, no credentials)

```bash
# Windows: double-click start.bat      macOS/Linux:
./start.sh
```

or manually:

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                               # Windows: copy .env.example .env
python run.py
```

Open http://127.0.0.1:8000. The app starts in **DEMO mode**: prices, fundamentals and news are synthetic and are labelled DEMO everywhere.

## Live data (SAMCO)

Edit `.env`:

```
DEMO_MODE=false
SAMCO_USER_ID=your_id
SAMCO_PASSWORD=your_password
SAMCO_YOB=your_year_of_birth
```

Restart `python run.py`. The badge in the top bar turns green (`LIVE · SAMCO`). If SAMCO is unreachable or credentials are wrong, the app shows an error. It does not quietly switch to fake data.

SAMCO provides prices and candles only. For fundamentals, FII/DII, news and F&O open interest in live mode, copy `data/reference_live.example.json` to `data/reference_live.json` and keep it updated. Missing fields show as unavailable and are left out of scoring.

## AI (optional)

Set `ANTHROPIC_API_KEY` in `.env` to have Claude interpret each setup (stock page → **Run AI analysis**). Without a key, a built-in rule-based interpreter fills in the same fields. Either way, the AI only reads the data on the page and labels it **LIVE/DEMO DATA**, **CALCULATED DATA** or **AI INTERPRETATION**.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                      # 88 tests: unit, provider, engine, AI, API, browser end-to-end
```

The browser tests use Playwright's Chromium (`python -m playwright install chromium` once, or set `CHROMIUM_PATH`). They are skipped if no browser is available.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): layers, scoring formulas, API reference
- [PROJECT_AUDIT.md](PROJECT_AUDIT.md): the starting state and the plan
- [FINAL_STATUS.md](FINAL_STATUS.md): module status and the remaining setup steps for you
- [CHANGELOG.md](CHANGELOG.md)

## हिंदी में (संक्षेप)

1. `start.bat` (Windows) या `./start.sh` चलाएँ, फिर ब्राउज़र में http://127.0.0.1:8000 खोलें। शुरुआत में DEMO डेटा दिखता है।
2. Live डेटा के लिए `.env` में `DEMO_MODE=false` और SAMCO user ID, password और YOB डालें।
3. AI explanation के लिए `.env` में `ANTHROPIC_API_KEY` डालें।
4. यह app सिर्फ़ BUY/SELL/HOLD निर्णय और stock selection में मदद करता है। Order कभी place नहीं करता।
