from types import SimpleNamespace

import pytest

from vegaguard.config import Settings
from vegaguard.models import Opportunity, OptionCandidate
from vegaguard.thesis import OpenAIThesisAgent


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
