"""Start the Swing Watchlist AI server: python run.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import uvicorn  # noqa: E402

from app.config import load_settings  # noqa: E402

if __name__ == "__main__":
    s = load_settings()
    print(f"Swing Watchlist AI - mode={s.mode} provider={'DEMO' if s.demo_mode else s.provider.upper()} "
          f"-> http://{s.host}:{s.port}")
    uvicorn.run("app.main:create_app", factory=True, host=s.host, port=s.port, log_level="info")
