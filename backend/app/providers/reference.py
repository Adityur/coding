"""Reference data: fundamentals, shareholding (FII/DII), news/catalysts and F&O open interest.

SAMCO's market-data API does not provide fundamentals or news. In LIVE mode these come from a
user-maintained JSON file (REFERENCE_DATA_FILE); anything missing is returned as null with
source=UNAVAILABLE. In DEMO mode a deterministic generator fills them and labels them DEMO.
"""
from __future__ import annotations

import json
import logging
import random
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

from .base import IST

log = logging.getLogger("swing.reference")

DEMO_HEADLINES = [
    ("Quarterly results ahead of estimates; margins expand", 0.7, True),
    ("Order book update shows steady pipeline", 0.4, True),
    ("Management reiterates full-year guidance", 0.2, False),
    ("Sector peers report mixed demand trends", 0.0, False),
    ("Brokerage cuts target price citing valuation", -0.4, False),
    ("Quarterly profit misses estimates on higher costs", -0.6, True),
    ("Board approves capacity expansion plan", 0.5, True),
    ("Promoter pledge reduced", 0.3, False),
]


def _empty(source: str = "UNAVAILABLE") -> dict:
    return {
        "fundamentals": {"roe": None, "roe_growth": None, "sales_growth": None, "profit_growth": None, "pe": None,
                         "sector_pe": None, "source": source, "as_of": None},
        "shareholding": {"fii_change": None, "dii_change": None, "source": source, "as_of": None},
        "news": {"items": [], "sentiment": None, "catalyst": None, "source": source, "as_of": None},
        "fno": {"eligible": None, "oi": None, "oi_change_pct": None, "pcr": None, "source": source, "as_of": None},
    }


class DemoReference:
    source = "DEMO"

    def get(self, symbol: str, fno_eligible: bool) -> dict:
        today = datetime.now(IST).date()
        r = random.Random(zlib.crc32(f"ref|{symbol}|{today.isoformat()}".encode()))
        p = random.Random(zlib.crc32(f"refp|{symbol}".encode()))
        as_of = today.isoformat()
        out = _empty("DEMO")
        out["fundamentals"].update({
            "roe": round(p.uniform(6, 32), 1), "roe_growth": round(p.uniform(-4, 6), 1),
            "sales_growth": round(p.uniform(-5, 28), 1), "profit_growth": round(p.uniform(-15, 35), 1),
            "pe": round(p.uniform(9, 70), 1), "sector_pe": round(p.uniform(18, 40), 1), "as_of": as_of,
        })
        out["shareholding"].update({"fii_change": round(r.uniform(-1.5, 1.5), 2),
                                    "dii_change": round(r.uniform(-1.2, 1.2), 2), "as_of": as_of})
        picks = r.sample(DEMO_HEADLINES, k=2)
        items = [{"headline": f"[DEMO] {h}", "sentiment": s, "catalyst": c,
                  "date": (today - timedelta(days=i * 2)).isoformat(), "source": "DEMO"} for i, (h, s, c) in enumerate(picks)]
        out["news"].update({"items": items, "sentiment": round(sum(i["sentiment"] for i in items) / len(items), 2),
                            "catalyst": next((i["headline"] for i in items if i["catalyst"]), None), "as_of": as_of})
        if fno_eligible:
            out["fno"].update({"eligible": True, "oi": round(r.uniform(5e6, 6e7)), "oi_change_pct": round(r.uniform(-12, 12), 2),
                               "pcr": round(r.uniform(0.5, 1.5), 2), "as_of": as_of})
        else:
            out["fno"].update({"eligible": False})
        return out


class FileReference:
    """Loads REFERENCE_DATA_FILE (see data/reference_live.example.json). Reloads when the file changes."""

    source = "REFERENCE_FILE"

    def __init__(self, path: str):
        self._path = Path(path) if path else None
        self._mtime: float | None = None
        self._data: dict = {}

    def _load(self) -> dict:
        if not self._path or not self._path.exists():
            return {}
        mtime = self._path.stat().st_mtime
        if mtime != self._mtime:
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Could not read reference data file: %s", type(exc).__name__)
                self._data = {}
            self._mtime = mtime
        return self._data

    @property
    def available(self) -> bool:
        return bool(self._load().get("symbols"))

    def get(self, symbol: str, fno_eligible: bool) -> dict:
        data = self._load()
        entry = (data.get("symbols") or {}).get(symbol)
        out = _empty()
        out["fno"]["eligible"] = fno_eligible
        if not entry:
            return out
        as_of = data.get("as_of")
        label = data.get("source") or self.source
        if f := entry.get("fundamentals"):
            out["fundamentals"].update({k: f.get(k) for k in ("roe", "roe_growth", "sales_growth", "profit_growth", "pe", "sector_pe")})
            out["fundamentals"].update({"source": label, "as_of": f.get("as_of", as_of)})
        if s := entry.get("shareholding"):
            out["shareholding"].update({"fii_change": s.get("fii_change"), "dii_change": s.get("dii_change"),
                                        "source": label, "as_of": s.get("as_of", as_of)})
        if news := entry.get("news"):
            items = [n for n in news if isinstance(n, dict) and n.get("headline")]
            sents = [float(n["sentiment"]) for n in items if isinstance(n.get("sentiment"), (int, float))]
            out["news"].update({
                "items": items, "sentiment": round(sum(sents) / len(sents), 2) if sents else None,
                "catalyst": next((n["headline"] for n in items if n.get("catalyst")), None),
                "source": label, "as_of": as_of,
            })
        if fno := entry.get("fno"):
            out["fno"].update({"oi": fno.get("oi"), "oi_change_pct": fno.get("oi_change_pct"), "pcr": fno.get("pcr"),
                               "source": label, "as_of": fno.get("as_of", as_of)})
        return out


def reference_age_days(as_of: str | None) -> int | None:
    if not as_of:
        return None
    try:
        return (datetime.now(IST).date() - date.fromisoformat(str(as_of)[:10])).days
    except ValueError:
        return None
