import json
from types import SimpleNamespace

import pytest

from vegaguard.config import Settings
from vegaguard.models import Opportunity, OptionCandidate, TradeThesisExplanation
from vegaguard.thesis import DeterministicThesisExplainer, OpenAIThesisAgent


@pytest.mark.asyncio
async def test_openai_thesis_agent_validates_mocked_structured_response():
    agent = OpenAIThesisAgent(Settings(openai_api_key="test-key"))

    class FakeResponses:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                output_text=(
                    '{"action":"skip","confidence":0.2,'
                    '"rationale":"The typed evidence is incomplete, so a paper trade is not justified.",'
                    '"invalidation":"Require fresh Greeks, IV, and aligned deterministic evidence.",'
                    '"candidate_symbol":"SPY260918C00650000"}'
                )
            )

    agent.client = SimpleNamespace(responses=FakeResponses())
    opportunity = Opportunity(
        candidate=OptionCandidate(
            underlying="SPY",
            symbol="SPY260918C00650000",
            option_type="call",
            strike=650,
            expiration="2026-09-18",
            dte=21,
            bid=3.4,
            ask=3.5,
            delta=0.46,
            implied_volatility=0.2,
            underlying_price=640,
        ),
        return_1d_pct=1,
        return_5d_pct=3,
        realized_volatility=0.2,
        evidence=["typed deterministic evidence"],
    )
    thesis = await agent.evaluate(opportunity)
    assert thesis.action == "skip"


@pytest.mark.asyncio
async def test_trade_thesis_explainer_uses_strict_json_schema():
    agent = OpenAIThesisAgent(Settings(openai_api_key="test-key"))
    calls: list[dict] = []

    class FakeResponses:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "thesis": "Validated bullish spread facts are coherent.",
                        "supporting_signals": ["score 70", "fresh quote"],
                        "risks": ["defined debit loss"],
                        "invalidation": "Invalidate when the deterministic signal or quote gate fails.",
                        "explanation": "Advisory summary only; deterministic controls remain authoritative.",
                    }
                )
            )

    agent.client = SimpleNamespace(responses=FakeResponses())
    explanation = await agent.explain(
        {"underlying": "SPY", "score": 70, "risk": {"approved": True}}
    )

    assert isinstance(explanation, TradeThesisExplanation)
    assert explanation.source == "openai"
    assert explanation.supporting_signals == ["score 70", "fresh quote"]
    assert calls[0]["text"]["format"]["type"] == "json_schema"
    assert calls[0]["text"]["format"]["strict"] is True
    assert calls[0]["text"]["format"]["schema"]["required"] == [
        "thesis",
        "supporting_signals",
        "risks",
        "invalidation",
        "explanation",
    ]
    assert calls[0]["store"] is False


@pytest.mark.asyncio
async def test_missing_key_uses_labelled_deterministic_explainer():
    explanation = await OpenAIThesisAgent(Settings()).explain(
        {"underlying": "SPY", "score": None, "risk": {"approved": False}}
    )
    assert explanation.source == "deterministic_fallback"
    assert explanation.fallback_reason == "OPENAI_API_KEY is not configured"
    assert explanation.explanation.startswith("Deterministic fallback:")


@pytest.mark.asyncio
async def test_api_failure_uses_labelled_deterministic_explainer():
    agent = OpenAIThesisAgent(Settings(openai_api_key="test-key"))

    class FailingResponses:
        async def create(self, **_kwargs):
            raise RuntimeError("upstream failure")

    agent.client = SimpleNamespace(responses=FailingResponses())
    explanation = await agent.explain({"underlying": "SPY", "score": 65})
    assert explanation.source == "deterministic_fallback"
    assert explanation.fallback_reason == "OpenAI request failed: RuntimeError"
    assert explanation.thesis


@pytest.mark.asyncio
async def test_unexpected_model_fields_use_deterministic_fallback():
    agent = OpenAIThesisAgent(Settings(openai_api_key="test-key"))

    class ExtraFieldResponses:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "thesis": "A bounded explanation.",
                        "supporting_signals": ["validated score"],
                        "risks": ["defined loss"],
                        "invalidation": "Invalidate on a failed hard gate.",
                        "explanation": "Advisory only.",
                        "legs": ["untrusted-model-leg"],
                    }
                )
            )

    agent.client = SimpleNamespace(responses=ExtraFieldResponses())
    explanation = await agent.explain({"underlying": "SPY", "score": 70})
    assert explanation.source == "deterministic_fallback"
    assert explanation.fallback_reason == "OpenAI request failed: ValueError"


@pytest.mark.asyncio
async def test_deterministic_explainer_is_stable_for_same_facts():
    facts = {"underlying": "SPY", "score": 65, "regime": "neutral", "risk": {}}
    first = await DeterministicThesisExplainer().explain(facts)
    second = await DeterministicThesisExplainer().explain(facts)
    assert first == second
