from datetime import UTC, datetime
from enum import StrEnum
from re import fullmatch
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
    iv_source: str = Field(default="official", pattern="^(official|quote_derived)$")
    delta: float | None = None
    underlying_price: float = Field(gt=0)
    quote_timestamp: str | None = None
    volume: float | None = Field(default=None, ge=0)
    open_interest: float | None = Field(default=None, ge=0)

    @property
    def midpoint(self) -> float:
        return round((self.bid + self.ask) / 2, 4)

    @property
    def spread_pct(self) -> float:
        return round((self.ask - self.bid) / self.midpoint, 10) if self.midpoint else 1.0


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
    plan_id: str = Field(default_factory=lambda: f"vg-plan-{uuid4().hex[:20]}")
    trade_mode: str = Field(default="production", pattern="^(production|exploration)$")
    score_threshold: int = Field(default=70, ge=1, le=100)
    strategy: str = Field(pattern="^(single_leg|debit_spread)$")
    legs: list[OptionLeg] = Field(min_length=1, max_length=2)
    qty: int = Field(default=1, ge=1)
    # Alpaca represents a multi-leg credit limit as a negative number. Entries
    # are debits; a generated closing spread is a credit.
    limit_price: float
    max_loss_usd: float = Field(gt=0)
    candidate: OptionCandidate
    thesis: Thesis
    # A preview becomes submittable only while its original two-leg quotes are
    # still within this short approval window.
    approval_expires_at: datetime | None = None
    quote_timestamps: list[str] = Field(default_factory=list, max_length=2)
    client_order_id: str = Field(default_factory=lambda: f"vg-{uuid4().hex[:20]}")
    parent_client_order_id: str | None = None

    @model_validator(mode="after")
    def plan_shape_is_consistent(self):
        if self.trade_mode == "production" and self.score_threshold != 70:
            raise ValueError("production plans must retain the 70-point threshold")
        if self.strategy == "single_leg" and len(self.legs) != 1:
            raise ValueError("single_leg plans need exactly one leg")
        if self.strategy == "debit_spread" and len(self.legs) != 2:
            raise ValueError("debit_spread plans need exactly two legs")
        if self.limit_price == 0:
            raise ValueError("limit price cannot be zero")
        if self.strategy == "debit_spread":
            if {leg.side for leg in self.legs} != {Side.BUY, Side.SELL}:
                raise ValueError("debit_spread plans need one buy and one sell leg")
            opening = {
                (Side.BUY, PositionIntent.BUY_TO_OPEN),
                (Side.SELL, PositionIntent.SELL_TO_OPEN),
            }
            closing = {
                (Side.SELL, PositionIntent.SELL_TO_CLOSE),
                (Side.BUY, PositionIntent.BUY_TO_CLOSE),
            }
            intents = {(leg.side, leg.position_intent) for leg in self.legs}
            if intents != opening and intents != closing:
                raise ValueError("debit spread legs must be consistently opened or closed")
            if intents == opening and self.limit_price < 0:
                raise ValueError("opening debit spread must use a positive debit limit")
            if intents == closing and self.limit_price > 0:
                raise ValueError("closing debit spread must use a negative credit limit")
            self._validate_defined_risk_economics(opening=intents == opening)
        return self

    def _validate_defined_risk_economics(self, *, opening: bool) -> None:
        contracts = [self._occ_contract(leg.symbol) for leg in self.legs]
        if any(contract is None for contract in contracts):
            raise ValueError("debit spread legs must use valid OCC option symbols")
        first, second = contracts
        assert first is not None and second is not None
        if first[:3] != second[:3]:
            raise ValueError("debit spread legs must share underlying, expiration, and option type")
        width = abs(first[3] - second[3])
        if width <= 0 or abs(self.limit_price) >= width:
            raise ValueError("debit spread price must be positive risk below its strike width")
        original_long = next(
            leg
            for leg in self.legs
            if leg.position_intent in {PositionIntent.BUY_TO_OPEN, PositionIntent.SELL_TO_CLOSE}
        )
        original_short = next(leg for leg in self.legs if leg is not original_long)
        long_contract = self._occ_contract(original_long.symbol)
        short_contract = self._occ_contract(original_short.symbol)
        assert long_contract is not None and short_contract is not None
        option_type = long_contract[2]
        if option_type == "C" and long_contract[3] >= short_contract[3]:
            raise ValueError("call debit spread requires the long strike below the short strike")
        if option_type == "P" and long_contract[3] <= short_contract[3]:
            raise ValueError("put debit spread requires the long strike above the short strike")
        if opening:
            expected_max_loss = round(self.limit_price * 100 * self.qty, 2)
            if abs(self.max_loss_usd - expected_max_loss) > 0.01:
                raise ValueError(
                    "maximum loss must equal debit times contract multiplier and quantity"
                )
            if self.candidate.symbol != original_long.symbol:
                raise ValueError("candidate must be the opening long option leg")
            expected_option_type = "call" if option_type == "C" else "put"
            expiration = (
                datetime.strptime(long_contract[1], "%y%m%d").replace(tzinfo=UTC).date().isoformat()
            )
            if (
                self.underlying != self.candidate.underlying
                or long_contract[0] != self.underlying
                or self.candidate.option_type != expected_option_type
                or self.candidate.expiration != expiration
                or abs(self.candidate.strike - long_contract[3]) > 0.0001
            ):
                raise ValueError("candidate metadata must match the opening long OCC contract")

    @staticmethod
    def _occ_contract(symbol: str) -> tuple[str, str, str, float] | None:
        match = fullmatch(r"([A-Z.]{1,8})(\d{6})([CP])(\d{8})", symbol)
        if match is None:
            return None
        return match.group(1), match.group(2), match.group(3), int(match.group(4)) / 1000

    @property
    def spread_width(self) -> float | None:
        if self.strategy != "debit_spread":
            return None
        contracts = [self._occ_contract(leg.symbol) for leg in self.legs]
        if any(contract is None for contract in contracts):
            return None
        first, second = contracts
        assert first is not None and second is not None
        return round(abs(first[3] - second[3]), 4)

    @property
    def maximum_profit_usd(self) -> float | None:
        width = self.spread_width
        if width is None or self.is_closing:
            return None
        return round((width - self.limit_price) * 100 * self.qty, 2)

    @property
    def is_closing(self) -> bool:
        return bool(self.legs) and all(
            leg.position_intent in {PositionIntent.BUY_TO_CLOSE, PositionIntent.SELL_TO_CLOSE}
            for leg in self.legs
        )

    def closing_plan(self, *, executable_credit: float) -> "TradePlan":
        """Create the only permitted exit: reverse every leg atomically.

        ``executable_credit`` is the conservative long-bid minus short-ask
        value. Alpaca represents a credit multi-leg limit with a negative price.
        """
        if self.is_closing:
            raise ValueError("cannot close an already-closing plan")
        if executable_credit <= 0:
            raise ValueError("executable closing credit must be positive")
        transitions = {
            PositionIntent.BUY_TO_OPEN: (Side.SELL, PositionIntent.SELL_TO_CLOSE),
            PositionIntent.SELL_TO_OPEN: (Side.BUY, PositionIntent.BUY_TO_CLOSE),
        }
        return TradePlan(
            underlying=self.underlying,
            trade_mode=self.trade_mode,
            score_threshold=self.score_threshold,
            strategy=self.strategy,
            legs=[
                OptionLeg(
                    symbol=leg.symbol,
                    side=transitions[leg.position_intent][0],
                    ratio_qty=leg.ratio_qty,
                    position_intent=transitions[leg.position_intent][1],
                )
                for leg in self.legs
            ],
            qty=self.qty,
            limit_price=-round(executable_credit, 4),
            max_loss_usd=self.max_loss_usd,
            candidate=self.candidate,
            thesis=self.thesis,
            quote_timestamps=[],
            client_order_id=f"vg-exit-{uuid4().hex[:18]}",
            parent_client_order_id=self.client_order_id,
        )

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
