"""Application settings, read only from environment variables (optionally a local .env file)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ROOT_DIR holds shipped read-only files (frontend, universe); HOME_DIR holds .env and user data.
# They differ only inside a PyInstaller desktop build, where HOME_DIR is the folder of the executable.
_FROZEN = getattr(sys, "frozen", False)
ROOT_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
HOME_DIR = Path(os.environ.get("SWING_HOME") or (Path(sys.executable).parent if _FROZEN else ROOT_DIR))
DATA_DIR = ROOT_DIR / "data"
USER_DATA_DIR = HOME_DIR / "data"
FRONTEND_DIR = ROOT_DIR / "frontend"

VALID_TIMEFRAMES = ("1d", "1h", "15m", "5m")


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default


@dataclass(frozen=True)
class Settings:
    demo_mode: bool = True
    demo_fallback: bool = False
    provider: str = "samco"

    samco_base_url: str = "https://api.stocknote.com"
    samco_user_id: str = field(default="", repr=False)
    samco_password: str = field(default="", repr=False)
    samco_yob: str = field(default="", repr=False)
    samco_timeout_seconds: float = 10.0
    samco_max_concurrency: int = 3

    ai_enabled: bool = True
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    anthropic_api_key_present: bool = False

    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: tuple[str, ...] = ()

    default_capital: float = 500000.0
    default_risk_pct: float = 1.0
    max_position_pct: float = 20.0

    watchlist_timeframes: tuple[str, ...] = VALID_TIMEFRAMES
    cache_ttl_seconds: int = 60
    reference_data_file: str = ""
    universe_file: str = ""
    user_watchlist_file: str = ""

    @property
    def samco_configured(self) -> bool:
        return bool(self.samco_user_id and self.samco_password and self.samco_yob)

    @property
    def mode(self) -> str:
        return "DEMO" if self.demo_mode else "LIVE"


def load_settings() -> Settings:
    load_dotenv(HOME_DIR / ".env", override=False)
    tfs = tuple(
        tf for tf in (t.strip() for t in _str("WATCHLIST_TIMEFRAMES", ",".join(VALID_TIMEFRAMES)).split(","))
        if tf in VALID_TIMEFRAMES
    )
    if "1d" not in tfs:
        tfs = ("1d",) + tfs
    cors = tuple(o.strip() for o in _str("CORS_ORIGINS", "").split(",") if o.strip())
    return Settings(
        demo_mode=_bool("DEMO_MODE", True),
        demo_fallback=_bool("DEMO_FALLBACK", False),
        provider=_str("MARKET_DATA_PROVIDER", "samco").lower() or "samco",
        samco_base_url=_str("SAMCO_BASE_URL", "https://api.stocknote.com").rstrip("/"),
        samco_user_id=_str("SAMCO_USER_ID"),
        samco_password=os.environ.get("SAMCO_PASSWORD", ""),
        samco_yob=_str("SAMCO_YOB"),
        samco_timeout_seconds=_float("SAMCO_TIMEOUT_SECONDS", 10.0),
        samco_max_concurrency=max(1, _int("SAMCO_MAX_CONCURRENCY", 3)),
        ai_enabled=_bool("AI_ENABLED", True),
        ai_model=_str("AI_MODEL", "claude-opus-5-5") or "claude-opus-5-5",
        ai_effort=_str("AI_EFFORT", "medium") or "medium",
        anthropic_api_key_present=bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        host=_str("HOST", "127.0.0.1") or "127.0.0.1",
        port=_int("PORT", 8000),
        cors_origins=cors,
        default_capital=_float("DEFAULT_CAPITAL", 500000.0),
        default_risk_pct=_float("DEFAULT_RISK_PCT", 1.0),
        max_position_pct=_float("MAX_POSITION_PCT", 20.0),
        watchlist_timeframes=tfs,
        cache_ttl_seconds=max(5, _int("CACHE_TTL_SECONDS", 60)),
        reference_data_file=_str("REFERENCE_DATA_FILE", str(USER_DATA_DIR / "reference_live.json")),
        universe_file=_str("UNIVERSE_FILE", str(DATA_DIR / "universe.json")),
        user_watchlist_file=_str("USER_WATCHLIST_FILE", str(USER_DATA_DIR / "user_watchlist.json")),
    )
