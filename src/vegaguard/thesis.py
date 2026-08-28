import json
from collections.abc import Awaitable
from typing import Protocol

from openai import AsyncOpenAI

from .config import Settings
from .models import Opportunity, Thesis


class ThesisAgent(Protocol):
    def evaluate(self, opportunity: Opportunity) -> Awaitable[Thesis]: ...


class DeterministicThesisAgent:
    """Local bounded thesis that works when an OpenAI key is not configured."""

    async def evaluate(self, opportunity: Opportunity) -> Thesis:
        candidate = opportunity.candidate
        tradeable = (
            candidate.implied_volatility is not None
            and candidate.delta is not None
            and candidate.spread_pct <= 0.08
            and abs(opportunity.return_5d_pct) > 0
        )
        if not tradeable:
            return Thesis(
                action="skip",
                confidence=0.0,
                rationale="Validated local evidence is incomplete or liquidity is outside the bounded thesis policy.",
                invalidation="No trade is permitted until the deterministic scanner produces complete liquid evidence.",
                candidate_symbol=candidate.symbol,
            )
        confidence = min(0.9, round(0.55 + min(abs(opportunity.return_5d_pct) / 20, 0.25), 2))
        return Thesis(
            action="trade",
            confidence=confidence,
            rationale=(
                "Local bounded thesis accepts the scanner's validated directional opportunity; "
                f"five-day return is {opportunity.return_5d_pct:.2f}% and the option quote is liquid."
            ),
            invalidation="Exit on deterministic signal reversal, stop-loss, time-stop, expiry rule, or liquidity deterioration.",
            candidate_symbol=candidate.symbol,
        )


class OpenAIThesisAgent:
    """Generates a narrow, reviewable advisory from supplied market evidence."""

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError(
                "Missing OPENAI_API_KEY; VegaGuard does not substitute a fake thesis agent."
            )
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())

    async def evaluate(self, opportunity: Opportunity) -> Thesis:
        prompt = f"""You are the research agent in a paper-options system. Return ONLY valid JSON matching:
{{"action":"trade|skip","confidence":0..1,"rationale":"...","invalidation":"...","candidate_symbol":"..."}}

You may only assess the given option candidate. Never invent market data, contracts, or price targets.
The action is an advisory label only: it cannot approve, veto, size, price, or submit a trade. The
deterministic scanner, spread validator, and risk gate make those decisions independently.

Opportunity:\n{json.dumps(opportunity.model_dump(), default=str)}"""
        response = await self.client.responses.create(
            model=self.settings.openai_model, input=prompt
        )
        return Thesis.model_validate_json(response.output_text)
