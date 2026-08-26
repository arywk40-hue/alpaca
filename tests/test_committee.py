from test_service import _scan

from vegaguard.committee import (
    AdversarialRiskAgent,
    CounterfactualAuditor,
    ExecutionAgent,
    RiskBudgetAllocator,
    StructureVolatilityAgent,
)


def test_bounded_committee_reviews_and_allocates_without_mutating_spread():
    scan = _scan()
    assert scan.spread is not None
    structure = StructureVolatilityAgent().review(scan.spread)
    adversarial = AdversarialRiskAgent().review(scan.spread)
    assert structure.approved
    assert adversarial.approved
    assert ExecutionAgent().choose(market_open=True, reviews=[structure, adversarial]) == "limit"
    allocations = RiskBudgetAllocator().allocate([(scan, 130)], risk_budget_usd=130)
    assert allocations[0].underlying == "SPY"
    assert allocations[0].max_loss_usd == 130


def test_counterfactual_auditor_reports_relative_outcome():
    result = CounterfactualAuditor().compare(selected_net_pnl=50, shadow_net_pnl=20)
    assert result.verdict == "selected_outperformed"
    assert result.difference == 30
