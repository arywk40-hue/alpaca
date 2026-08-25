from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PositionIntent(StrEnum):
    BUY_TO_OPEN = "buy_to_open"
    SELL_TO_OPEN = "sell_to_open"
    BUY_TO_CLOSE = "buy_to_close"
    SELL_TO_CLOSE = "sell_to_close"


class OptionLeg(BaseModel):
    symbol: str
    side: Side
    ratio_qty: int = Field(ge=1, default=1)
    position_intent: PositionIntent


class OptionCandidate(BaseModel):
    underlying: str
    symbol: str
    option_type: str = Field(pattern="^(call|put)$")
    strike: float = Field(gt=0)
    expiration: str
    dte: int = Field(ge=0)
    bid: float = Field(ge=0)
    ask: float = Field(gt=0)
    implied_volatility: float | None = Field(default=None, ge=0)
    delta: float | None = None
    underlying_price: float = Field(gt=0)

    @property
    def midpoint(self) -> float:
        return round((self.bid + self.ask) / 2, 4)

    @property
    def spread_pct(self) -> float:
        return (self.ask - self.bid) / self.midpoint if self.midpoint else 1.0


class Opportunity(BaseModel):
    candidate: OptionCandidate
    return_1d_pct: float
    return_5d_pct: float
    realized_volatility: float = Field(ge=0)
    evidence: list[str] = Field(min_length=1, max_length=8)


class Thesis(BaseModel):
    action: str = Field(pattern="^(trade|skip)$")
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=20, max_length=800)
    invalidation: str = Field(min_length=10, max_length=300)
    candidate_symbol: str


class TradePlan(BaseModel):
    underlying: str
    strategy: str = Field(pattern="^(single_leg|debit_spread)$")
    legs: list[OptionLeg] = Field(min_length=1, max_length=2)
    qty: int = Field(default=1, ge=1)
    limit_price: float = Field(gt=0)
    max_loss_usd: float = Field(gt=0)
    candidate: OptionCandidate
    thesis: Thesis
    client_order_id: str = Field(default_factory=lambda: f"vg-{uuid4().hex[:20]}")

    @model_validator(mode="after")
    def plan_shape_is_consistent(self):
        if self.strategy == "single_leg" and len(self.legs) != 1:
            raise ValueError("single_leg plans need exactly one leg")
        if self.strategy == "debit_spread" and len(self.legs) != 2:
            raise ValueError("debit_spread plans need exactly two legs")
        if self.strategy == "debit_spread" and {leg.side for leg in self.legs} != {
            Side.BUY,
            Side.SELL,
        }:
            raise ValueError("debit_spread plans need one buy and one sell leg")
        return self

    def mcp_arguments(self) -> dict:
        if self.strategy == "single_leg":
            leg = self.legs[0]
            return {
                "symbol": leg.symbol,
                "qty": str(self.qty),
                "side": leg.side.value,
                "type": "limit",
                "time_in_force": "day",
                "limit_price": str(self.limit_price),
                "client_order_id": self.client_order_id,
            }
        return {
            "order_class": "mleg",
            "qty": str(self.qty),
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(self.limit_price),
            "client_order_id": self.client_order_id,
            "legs": [leg.model_dump(mode="json") for leg in self.legs],
        }


class GateResult(BaseModel):
    approved: bool
    reasons: list[str]


class JournalEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event: str
    plan: TradePlan | None = None
    gate: GateResult | None = None
    payload: dict = Field(default_factory=dict)
