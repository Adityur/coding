"""AI analysis service.

Uses Claude (Anthropic API) when ANTHROPIC_API_KEY is set and AI_ENABLED=true; otherwise a
deterministic rule-based interpreter produces the same structure. Both only interpret the supplied
structured data and must not introduce market facts. Output separates market data, calculated data
and AI interpretation.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ..config import Settings
from ..engines.scoring import WEIGHTS
from ..providers.base import IST

log = logging.getLogger("swing.ai")

DISCLAIMER = ("AI interpretation of the data shown. Not investment advice and not a prediction of future "
              "returns. Verify independently before acting. This app does not place orders.")

SYSTEM_PROMPT = """You are a swing-trading analysis assistant inside a decision-support app for Indian equities (NSE).
You receive one JSON object with three sections:
- market_data: prices/quotes from the data provider. If is_live is false, it is synthetic DEMO data - say so.
- calculated_data: indicators, multi-timeframe structure, scores with contributing factors, the rule-based signal and a risk plan, all computed by the app.
- reference_data: fundamentals, shareholding, news and F&O data with their own source labels; null means unavailable.

Rules:
- Use only facts present in the JSON. Do not add news, earnings dates, price targets, macro events or numbers that are not in it.
- When a field is null or unavailable, say it is unavailable rather than guessing.
- Interpret; do not repeat every number. Refer to the app's signal, and say clearly if you disagree with it and why, based on the data.
- Never promise or imply guaranteed returns. Describe risks plainly.
- The app does not execute trades; never suggest that it will.
- Keep each list item to one sentence. ai_remark must be under 140 characters."""


class AIAssessment(BaseModel):
    setup_summary: str
    bullish_factors: list[str]
    bearish_factors: list[str]
    catalyst_interpretation: str
    trend_interpretation: str
    technical_alignment: str
    risk_warnings: list[str]
    entry_quality: Literal["GOOD", "FAIR", "POOR", "NOT_APPLICABLE"]
    confidence: int
    final_assessment: str
    ai_remark: str


def build_facts(analysis: dict) -> dict:
    tech = analysis.get("technical", {})
    tf_summary = {}
    for tf, a in tech.items():
        if not a:
            continue
        tf_summary[tf] = {k: a.get(k) for k in ("trend", "ma_alignment", "pattern", "atr14", "support", "resistance")}
        tf_summary[tf].update({"structure": a.get("structure"), "momentum": a.get("momentum"),
                               "breakout": a.get("breakout"), "volume": a.get("volume"),
                               "ma_crossover": a.get("ma_crossover"), "slope": a.get("slope"),
                               "data_quality": (a.get("data_quality") or {}).get("status")})
    daily = tech.get("1d") or {}
    scores = {k: {"score": v.get("score"), "factors": [f for f in v.get("factors", []) if f.get("points") is not None]}
              for k, v in (analysis.get("scores") or {}).items()}
    return {
        "symbol": analysis.get("symbol"), "name": analysis.get("name"), "sector": analysis.get("sector"),
        "market_data": {"quote": analysis.get("quote"), "data_source": analysis.get("data_source"),
                        "is_live": analysis.get("is_live"), "timestamp": analysis.get("timestamp")},
        "calculated_data": {"timeframes": tf_summary, "high_zone": daily.get("high_zone"),
                            "relative_strength": daily.get("relative_strength"), "moving_averages": daily.get("moving_averages"),
                            "multi_timeframe": analysis.get("multi_timeframe"), "scores": scores,
                            "decision": analysis.get("decision"), "risk_plan": analysis.get("risk")},
        "reference_data": analysis.get("reference"),
    }


def rule_based(analysis: dict) -> AIAssessment:
    decision = analysis.get("decision") or {}
    scores = analysis.get("scores") or {}
    daily = (analysis.get("technical") or {}).get("1d") or {}
    mtf = analysis.get("multi_timeframe") or {}
    risk = analysis.get("risk") or {}
    ref = analysis.get("reference") or {}

    bull, bear = [], []
    for key, card in sorted(scores.items(), key=lambda kv: -WEIGHTS.get(kv[0], 0)):
        for f in card.get("factors", []):
            if f.get("points") is None or not f.get("max"):
                continue
            ratio = f["points"] / f["max"]
            label = f"{key.replace('_score', '').replace('_', ' ')}: {f['name']}"
            if ratio >= 0.8:
                bull.append(label + (f" ({f['note']})" if f.get("note") else ""))
            elif ratio <= 0.2:
                bear.append(label + (f" ({f['note']})" if f.get("note") else ""))

    news = ref.get("news") or {}
    if news.get("items"):
        s = news.get("sentiment")
        tone = "positive" if s and s > 0.15 else "negative" if s and s < -0.15 else "neutral"
        catalyst = f"News flow is {tone} (avg sentiment {s}). " + (
            f"Catalyst: {news['catalyst']}." if news.get("catalyst") else "No specific catalyst flagged.")
    else:
        catalyst = "No news/catalyst data available for this symbol."

    trend = daily.get("trend") or "UNKNOWN"
    hh = (daily.get("structure") or {}).get("higher_high")
    hl = (daily.get("structure") or {}).get("higher_low")
    trend_txt = (f"Daily trend {trend}; higher high: {_yn(hh)}, higher low: {_yn(hl)}; "
                 f"MA alignment {daily.get('ma_alignment') or 'unknown'}; SMA20 angle "
                 f"{(daily.get('slope') or {}).get('sma20_angle_deg')} deg.")
    align = mtf.get("alignment") or "UNKNOWN"
    tf_txt = ", ".join(f"{tf}: {r.get('trend') or 'n/a'}" for tf, r in (mtf.get("timeframes") or {}).items())
    tech_align = f"Multi-timeframe alignment {align} ({tf_txt})."

    entry_card = scores.get("entry_score") or {}
    es = entry_card.get("score")
    signal = decision.get("signal", "HOLD")
    if signal != "BUY":
        eq = "NOT_APPLICABLE" if signal == "SELL" else ("FAIR" if es and es >= 60 else "POOR")
    else:
        eq = "GOOD" if es and es >= 70 else "FAIR" if es and es >= 50 else "POOR"

    warnings = list(risk.get("warnings") or []) + [w for w in decision.get("warnings", []) if "downgraded" in w]
    if not analysis.get("is_live"):
        warnings.insert(0, "Analysis is based on DEMO (synthetic) data, not live market prices.")

    total = decision.get("total_score")
    rr = risk.get("risk_reward")
    summary = (f"{analysis.get('symbol')} scores {total} overall ({decision.get('rating')}), "
               f"daily trend {trend}, pattern: {daily.get('pattern') or 'none detected'}.")
    final = (f"Rule-based assessment: {signal} with {decision.get('confidence')}% confidence. "
             + (f"Plan: entry {risk.get('entry')}, stop {risk.get('stop_loss')}, target {risk.get('target')} (R:R {rr})."
                if signal == "BUY" else "No new long entry suggested by the rules at this time."))
    remark = f"{signal}: {daily.get('pattern') or trend.lower()}; score {total}, R:R {rr}"[:139]
    return AIAssessment(setup_summary=summary, bullish_factors=bull[:6], bearish_factors=bear[:6],
                        catalyst_interpretation=catalyst, trend_interpretation=trend_txt, technical_alignment=tech_align,
                        risk_warnings=warnings[:6], entry_quality=eq, confidence=int(decision.get("confidence") or 0),
                        final_assessment=final, ai_remark=remark)


def _yn(v) -> str:
    return "unknown" if v is None else ("yes" if v else "no")


class AIService:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self._client = client
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self.ttl = 900

    @property
    def llm_available(self) -> bool:
        return self.settings.ai_enabled and (self._client is not None or self.settings.anthropic_api_key_present)

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(timeout=90.0, max_retries=2)
        return self._client

    def status(self) -> dict:
        return {"enabled": self.settings.ai_enabled, "engine": "claude" if self.llm_available else "rule-based",
                "model": self.settings.ai_model if self.llm_available else None}

    def remark(self, analysis: dict) -> str:
        return rule_based(analysis).ai_remark

    async def analyze(self, analysis: dict, *, use_llm: bool = True) -> dict:
        key = (analysis.get("symbol"), analysis.get("timestamp"), use_llm and self.llm_available)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]

        warnings: list[str] = []
        engine, model = "rule-based", None
        assessment: AIAssessment | None = None
        if use_llm and self.llm_available:
            try:
                assessment = await self._claude(analysis)
                engine, model = "claude", self.settings.ai_model
            except _Refused as exc:
                warnings.append(f"Claude declined this request ({exc}); showing rule-based interpretation.")
            except Exception as exc:  # network/API/parse failure must not break the endpoint
                log.warning("AI request failed: %s", type(exc).__name__)
                warnings.append(f"AI provider unavailable ({type(exc).__name__}); showing rule-based interpretation.")
        elif use_llm and self.settings.ai_enabled:
            warnings.append("ANTHROPIC_API_KEY not configured; showing rule-based interpretation.")
        if assessment is None:
            assessment = rule_based(analysis)

        facts = build_facts(analysis)
        result = {
            "symbol": analysis.get("symbol"), "engine": engine, "model": model,
            "generated_at": datetime.now(IST).isoformat(),
            "live_data": {"label": ("LIVE DATA" if analysis.get("is_live") else "DEMO DATA (synthetic, not live)"),
                          **facts["market_data"]},
            "calculated_data": {"label": "CALCULATED DATA (app engines)", "decision": analysis.get("decision"),
                                "scores": {k: v.get("score") for k, v in (analysis.get("scores") or {}).items()},
                                "risk": analysis.get("risk"), "multi_timeframe": analysis.get("multi_timeframe")},
            "reference_data": {"label": "REFERENCE DATA", "sources": {k: (v or {}).get("source") for k, v in (analysis.get("reference") or {}).items()}},
            "ai_interpretation": {"label": f"AI INTERPRETATION ({'Claude' if engine == 'claude' else 'rule-based engine'})",
                                  **assessment.model_dump()},
            "warnings": warnings, "disclaimer": DISCLAIMER,
        }
        result["ai_interpretation"]["confidence"] = max(0, min(100, int(result["ai_interpretation"]["confidence"])))
        if len(self._cache) > 300:
            self._cache.clear()
        self._cache[key] = (time.monotonic(), result)
        return result

    async def _claude(self, analysis: dict) -> AIAssessment:
        client = self._get_client()
        facts = json.dumps(build_facts(analysis), default=str, sort_keys=True)
        response = await client.beta.messages.parse(
            model=self.settings.ai_model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": self.settings.ai_effort},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Analyse this swing setup:\n{facts}"}],
            output_format=AIAssessment,
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise _Refused(getattr(details, "category", None) or "refusal")
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError("no structured output")
        return parsed


class _Refused(Exception):
    pass
