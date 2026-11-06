import asyncio
from dataclasses import replace
from types import SimpleNamespace

from app.providers.demo import DemoProvider
from app.providers.reference import DemoReference
from app.services.ai import AIAssessment, AIService, build_facts, rule_based
from app.services.analysis import AnalysisService


def analysis(settings, ai=None):
    ai = ai or AIService(settings)
    svc = AnalysisService(settings, DemoProvider(), DemoReference(), ai)
    return asyncio.run(svc.analyze("INFY"))


GOOD = AIAssessment(setup_summary="s", bullish_factors=["b"], bearish_factors=["x"], catalyst_interpretation="c",
                    trend_interpretation="t", technical_alignment="a", risk_warnings=["w"], entry_quality="FAIR",
                    confidence=140, final_assessment="f", ai_remark="r")


class FakeMessages:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, []

    async def parse(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.response


def fake_client(messages):
    return SimpleNamespace(beta=SimpleNamespace(messages=messages))


def test_rule_based_without_api_key(settings):
    a = analysis(settings)
    r = asyncio.run(AIService(settings).analyze(a))
    assert r["engine"] == "rule-based" and r["model"] is None
    assert {"live_data", "calculated_data", "ai_interpretation"} <= set(r)
    assert r["live_data"]["label"].startswith("DEMO DATA")
    assert any("ANTHROPIC_API_KEY" in w for w in r["warnings"])
    ai = r["ai_interpretation"]
    for k in ("setup_summary", "bullish_factors", "bearish_factors", "catalyst_interpretation", "trend_interpretation",
              "technical_alignment", "risk_warnings", "entry_quality", "confidence", "final_assessment"):
        assert k in ai


def test_rule_based_flags_demo_data(settings):
    out = rule_based(analysis(settings))
    assert any("DEMO" in w for w in out.risk_warnings)
    assert len(out.ai_remark) < 140


def test_claude_path_uses_structured_output_and_clamps_confidence(settings):
    s = replace(settings, anthropic_api_key_present=True)
    msgs = FakeMessages(SimpleNamespace(stop_reason="end_turn", parsed_output=GOOD))
    svc = AIService(s, client=fake_client(msgs))
    r = asyncio.run(svc.analyze(analysis(s, svc)))
    assert r["engine"] == "claude" and r["model"] == "claude-opus-5-5"
    assert r["ai_interpretation"]["confidence"] == 100
    call = msgs.calls[0]
    assert call["output_format"] is AIAssessment and call["fallbacks"] == "default"
    assert "Use only facts present in the JSON" in call["system"]


def test_claude_refusal_falls_back_to_rules(settings):
    s = replace(settings, anthropic_api_key_present=True)
    msgs = FakeMessages(SimpleNamespace(stop_reason="refusal", parsed_output=None, stop_details=SimpleNamespace(category="cyber")))
    svc = AIService(s, client=fake_client(msgs))
    r = asyncio.run(svc.analyze(analysis(s, svc)))
    assert r["engine"] == "rule-based" and any("declined" in w for w in r["warnings"])


def test_claude_error_falls_back_without_leaking(settings):
    s = replace(settings, anthropic_api_key_present=True)
    svc = AIService(s, client=fake_client(FakeMessages(exc=ConnectionError("sk-ant-secret-key"))))
    r = asyncio.run(svc.analyze(analysis(s, svc)))
    assert r["engine"] == "rule-based"
    assert "sk-ant-secret-key" not in str(r)


def test_ai_disabled_flag(settings):
    s = replace(settings, ai_enabled=False, anthropic_api_key_present=True)
    assert AIService(s).status()["engine"] == "rule-based"


def test_facts_separate_market_calculated_reference(settings):
    f = build_facts(analysis(settings))
    assert set(f) >= {"market_data", "calculated_data", "reference_data"}
    assert f["market_data"]["is_live"] is False
