"""Bounded committee roles operating only on validated strategy outputs."""

from __future__ import annotations

from dataclasses import dataclass

from .scanner import ScanResult
from .strategy.spread_builder import DebitSpread


@dataclass(frozen=True)
class CommitteeReview:
    approved: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Allocation:
    underlying: str
    max_loss_usd: float
    score: int


@dataclass(frozen=True)
class CounterfactualResult:
    selected_net_pnl: float
    shadow_net_pnl: float
    difference: float
    verdict: str


class StructureVolatilityAgent:
    """Validates calculated spread economics; it cannot select legs or prices."""

    def review(self, spread: DebitSpread) -> CommitteeReview:
        reasons: list[str] = []
        if spread.debit >= spread.width * 0.40:
            reasons.append("debit consumes at least 40% of strike width")
        if (
            spread.long_leg.implied_volatility is None
            or spread.short_leg.implied_volatility is None
        ):
            reasons.append("missing implied volatility")
        if spread.long_leg.delta is None or spread.short_leg.delta is None:
            reasons.append("missing Greeks")
        return CommitteeReview(not reasons, tuple(reasons or ["validated calculated debit spread"]))


class AdversarialRiskAgent:
    """Applies conservative shock checks without changing deterministic plan inputs."""

    def review(self, spread: DebitSpread) -> CommitteeReview:
        reasons: list[str] = []
        if spread.long_leg.spread_pct > 0.08 or spread.short_leg.spread_pct > 0.08:
            reasons.append("liquidity shock: leg bid/ask spread exceeds 8%")
        if spread.max_loss_per_contract <= 0:
            reasons.append("price shock: maximum loss is not defined")
        if spread.long_leg.dte < 14:
            reasons.append("time-decay shock: expiry is too near")
        if spread.long_leg.implied_volatility and spread.long_leg.implied_volatility > 2.0:
            reasons.append("IV shock: implied volatility is implausibly high")
        return CommitteeReview(not reasons, tuple(reasons or ["shock scenarios passed"]))


class RiskBudgetAllocator:
    """Ranks fixed strategy candidates without changing their proposed structures."""

    def allocate(
        self, candidates: list[tuple[ScanResult, float]], *, risk_budget_usd: float, limit: int = 3
    ) -> list[Allocation]:
        remaining = risk_budget_usd
        allocations: list[Allocation] = []
        ranked = sorted(
            candidates,
            key=lambda item: item[0].score.score if item[0].score else -101,
            reverse=True,
        )
        for scan, max_loss in ranked:
            if (
                scan.score is None
                or max_loss <= 0
                or max_loss > remaining
                or len(allocations) >= limit
            ):
                continue
            allocations.append(Allocation(scan.underlying, max_loss, scan.score.score))
            remaining -= max_loss
        return allocations


class ExecutionAgent:
    """Chooses an execution posture only; it cannot submit or mutate an order."""

    def choose(self, *, market_open: bool, reviews: list[CommitteeReview]) -> str:
        if not market_open:
            return "no_trade"
        if not all(review.approved for review in reviews):
            return "wait"
        return "limit"


class CounterfactualAuditor:
    """Compares selected and journaled shadow outcomes after an exit."""

    def compare(self, *, selected_net_pnl: float, shadow_net_pnl: float) -> CounterfactualResult:
        difference = round(selected_net_pnl - shadow_net_pnl, 2)
        verdict = (
            "selected_outperformed"
            if difference > 0
            else "shadow_outperformed"
            if difference < 0
            else "tie"
        )
        return CounterfactualResult(selected_net_pnl, shadow_net_pnl, difference, verdict)
