import json

from openai import AsyncOpenAI

from .config import Settings
from .models import Opportunity, Thesis


class OpenAIThesisAgent:
    """Generates a narrow, reviewable trade-or-skip thesis from supplied market evidence."""

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

You may only assess the given option candidate. Never invent market data, contracts, or price targets. Prefer skip when evidence is weak. You are not permitted to choose position size or bypass risk checks.

Opportunity:\n{json.dumps(opportunity.model_dump(), default=str)}"""
        response = await self.client.responses.create(
            model=self.settings.openai_model, input=prompt
        )
        return Thesis.model_validate_json(response.output_text)
