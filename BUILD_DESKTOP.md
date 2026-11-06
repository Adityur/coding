# Build: Desktop

The desktop app is the same backend and frontend: `desktop/desktop_app.py` starts the server on a free local port and opens it in a native window (pywebview: WebView2 on Windows, WKWebView on macOS, GTK/Qt on Linux).

## Run without packaging

```bash
pip install -r desktop/requirements-desktop.txt
python desktop/desktop_app.py            # native window
python desktop/desktop_app.py --browser  # opens your default browser instead
```

## Package a standalone app

PyInstaller does not cross-compile, so build on the OS you are targeting. Run from the repository root:

### Windows

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r desktop\requirements-desktop.txt
cd desktop
pyinstaller --noconfirm swing_desktop.spec
```

Output: `desktop\dist\SwingWatchlistAI\SwingWatchlistAI.exe`. It needs the Microsoft Edge WebView2 runtime, which ships with Windows 10 and 11.

### macOS

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r desktop/requirements-desktop.txt
cd desktop && pyinstaller --noconfirm swing_desktop.spec
```

Output: `desktop/dist/SwingWatchlistAI/SwingWatchlistAI`.

### Linux

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1   # GTK backend for pywebview
python3 -m venv --system-site-packages .venv && . .venv/bin/activate
pip install -r desktop/requirements-desktop.txt
cd desktop && pyinstaller --noconfirm swing_desktop.spec
```

## Configure the packaged app

Put a `.env` file **next to the executable** (copy `.env.example`). Runtime files are written to `data/` next to the executable:

- `data/user_watchlist.json`
- `data/reference_live.json` (fundamentals/news for live mode; copy it from `_internal/data/reference_live.example.json`)

To keep these elsewhere, set the environment variable `SWING_HOME` to that folder.

## Verified here

On Linux, the spec builds successfully, and the frozen executable (`--browser` mode) served `/health`, `/api/watchlist` (22 rows) and the UI. The native-window path needs a graphical desktop session, which this environment does not have, so it was not run.

## Optional

- **Icon:** convert `frontend/icon-512.png` to `.ico` (Windows) or `.icns` (macOS) and set `icon=` in `swing_desktop.spec`.
- **Installer:** wrap `dist/SwingWatchlistAI/` with Inno Setup (Windows) or `create-dmg` (macOS).
- **Code signing:** use your own certificate (Authenticode / Apple Developer ID). This is not included.
