import json
import logging
from collections.abc import Awaitable, Mapping
from typing import ClassVar, Protocol

from openai import AsyncOpenAI

from .config import Settings
from .models import Opportunity, Thesis, TradeThesisExplanation

logger = logging.getLogger(__name__)


class ThesisExplainer(Protocol):
    def explain(self, facts: Mapping[str, object]) -> Awaitable[TradeThesisExplanation]: ...


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


class DeterministicThesisExplainer:
    """Produce an honest, local explanation from validated facts only."""

    async def explain(self, facts: Mapping[str, object]) -> TradeThesisExplanation:
        underlying = str(facts.get("underlying") or "the underlying")
        score = facts.get("score")
        regime = str(facts.get("execution_regime") or facts.get("regime") or "unknown")
        risk = facts.get("risk") if isinstance(facts.get("risk"), Mapping) else {}
        spread = facts.get("spread") if isinstance(facts.get("spread"), Mapping) else {}
        risk_approved = bool(risk.get("approved"))
        signals = [
            f"Validated scanner score: {score if score is not None else 'unavailable'}.",
            f"Validated execution regime: {regime}.",
        ]
        if spread:
            signals.append(
                "Defined-risk debit spread is present with a validated entry quote of "
                f"{spread.get('debit', 'unavailable')}."
            )
        else:
            signals.append("No validated spread facts were supplied.")
        risk_reasons = risk.get("reasons") if isinstance(risk, Mapping) else None
        risks = [str(reason) for reason in risk_reasons or []]
        if not risks:
            risks.append(
                "The deterministic risk gate is the execution authority; this explanation is advisory only."
            )
        thesis = (
            f"Validated facts describe a {regime} {underlying} opportunity; the deterministic "
            f"risk gate is {'approved' if risk_approved else 'not approved'}."
        )
        return TradeThesisExplanation(
            thesis=thesis,
            supporting_signals=signals,
            risks=risks,
            invalidation=(
                "Invalidate on deterministic signal reversal, stale or widened quotes, "
                "changed spread economics, or any failed hard safety gate."
            ),
            explanation=(
                "Deterministic fallback: this advisory summarizes supplied scanner, spread, "
                "and risk facts only. It cannot change score, threshold, legs, quantity, "
                "risk approval, or execution."
            ),
            source="deterministic_fallback",
            fallback_reason="OPENAI_API_KEY is not configured",
        )


class OpenAIThesisAgent:
    """Generates a narrow, reviewable advisory from supplied market evidence.

    ``explain`` is the production integration. ``evaluate`` remains as a
    compatibility adapter for the original thesis object, but its output is not
    used to construct or authorize a plan.
    """

    _EXPLANATION_SCHEMA: ClassVar[dict[str, object]] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "thesis": {"type": "string"},
            "supporting_signals": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "invalidation": {"type": "string"},
            "explanation": {"type": "string"},
        },
        "required": [
            "thesis",
            "supporting_signals",
            "risks",
            "invalidation",
            "explanation",
        ],
    }

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = (
            AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
            if settings.openai_api_key
            else None
        )
        self.fallback = DeterministicThesisExplainer()

    async def explain(self, facts: Mapping[str, object]) -> TradeThesisExplanation:
        """Return strict JSON from OpenAI or a clearly labelled local fallback."""
        if self.client is None:
            return await self.fallback.explain(facts)
        try:
            prompt = (
                "You are VegaGuard's bounded Trade Thesis & Risk Explainer. "
                "Use only the already-validated JSON facts below. Do not invent data, "
                "prices, contracts, P&L, or events. Return ONLY JSON matching the supplied "
                "schema. Your response is advisory and must not alter score, threshold, "
                "legs, quantity, risk approval, or execution."
                f"\nValidated facts:\n{json.dumps(dict(facts), sort_keys=True, separators=(',', ':'), default=str)}"
            )
            response = await self.client.responses.create(
                model=self.settings.openai_model,
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "trade_thesis_risk_explainer",
                        "strict": True,
                        "schema": self._EXPLANATION_SCHEMA,
                    }
                },
                store=False,
            )
            raw = json.loads(response.output_text)
            required = set(self._EXPLANATION_SCHEMA["required"])
            if not isinstance(raw, dict) or set(raw) != required:
                raise ValueError("OpenAI explanation did not contain exactly the required fields")
            parsed = TradeThesisExplanation.model_validate(raw)
            return parsed.model_copy(update={"source": "openai", "fallback_reason": None})
        except Exception as exc:  # noqa: BLE001  # API failures fail closed to local evidence.
            logger.warning(
                "openai_thesis_explainer_failed", extra={"error_type": type(exc).__name__}
            )
            fallback = await self.fallback.explain(facts)
            return fallback.model_copy(
                update={
                    "fallback_reason": f"OpenAI request failed: {type(exc).__name__}",
                }
            )

    async def evaluate(self, opportunity: Opportunity) -> Thesis:
        if self.client is None:
            return await DeterministicThesisAgent().evaluate(opportunity)
        try:
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
        except Exception as exc:  # noqa: BLE001  # Legacy adapter also fails closed.
            logger.warning("openai_legacy_thesis_failed", extra={"error_type": type(exc).__name__})
            return await DeterministicThesisAgent().evaluate(opportunity)


# A short alias keeps callers agnostic to the internal model name.
ThesisExplanation = TradeThesisExplanation
