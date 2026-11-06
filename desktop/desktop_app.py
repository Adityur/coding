"""Desktop launcher: runs the API server locally and shows the web UI in a native window (pywebview).

    python desktop/desktop_app.py            # native window
    python desktop/desktop_app.py --browser  # no pywebview: open the system browser instead
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import uvicorn  # noqa: E402

from app.main import create_app  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> uvicorn.Server:
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}/health"
    for _ in range(100):
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return server
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Local server failed to start")


def main() -> None:
    ap = argparse.ArgumentParser(description="Swing Watchlist AI desktop")
    ap.add_argument("--browser", action="store_true", help="open in the system browser instead of a native window")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()

    port = args.port or free_port()
    server = start_server(port)
    url = f"http://127.0.0.1:{port}/#/watchlist"
    try:
        if args.browser:
            raise ImportError
        import webview
    except ImportError:
        print(f"Swing Watchlist AI running at {url}  (Ctrl+C to quit)")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        webview.create_window("Swing Watchlist AI", url, width=1440, height=900, min_size=(380, 600))
        webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
