"""Read-only summaries of VegaGuard's live shadow-evaluation evidence."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .strategy.metrics import confidence_intervals, max_drawdown


def build_session_report(candidates: list[dict], reprices: list[dict]) -> dict[str, Any]:
    """Build a report whose P&L fields are explicitly hypothetical.

    Repricing records are evidence marks made from fresh quotes, not Alpaca
    paper fills. A candidate contributes only its latest successful reprice to
    threshold performance to avoid counting the same spread three times.
    """
    observations = len(candidates)
    latest_candidates: dict[str, dict] = {}
    candidate_to_opportunity: dict[int, str] = {}
    for candidate in candidates:
        opportunity_id = str(candidate.get("opportunity_id") or f"legacy-{candidate['id']}")
        candidate_to_opportunity[int(candidate["id"])] = opportunity_id
        previous = latest_candidates.get(opportunity_id)
        if previous is None or str(candidate["observed_at"]) > str(previous["observed_at"]):
            latest_candidates[opportunity_id] = candidate
    grouped_candidates = list(latest_candidates.values())
    reprice_statuses = Counter(
        str((candidate.get("reprice_status") or {}).get("status") or "not_scheduled")
        for candidate in grouped_candidates
    )
    scores = [
        int(candidate["score"])
        for candidate in grouped_candidates
        if candidate["score"] is not None
    ]
    reasons = Counter(
        reason for candidate in grouped_candidates for reason in candidate.get("reasons", [])
    )
    qualified = sum(
        candidate["classification"] in {"qualifying_candidate", "exploration_eligible"}
        for candidate in grouped_candidates
    )
    quote_failures = sum(
        1
        for reason, count in reasons.items()
        if any(token in reason.lower() for token in ("stale", "quote", "fresh"))
        for _ in range(count)
    )
    liquidity_failures = sum(
        1
        for reason, count in reasons.items()
        if any(token in reason.lower() for token in ("liquid", "bid-ask", "spread"))
        for _ in range(count)
    )
    reprice_failures = [
        str((reprice.get("outcome") or {}).get("reason") or "") for reprice in reprices
    ]
    quote_failures += sum(
        any(token in reason.lower() for token in ("stale", "quote", "fresh"))
        for reason in reprice_failures
    )
    liquidity_failures += sum(
        any(token in reason.lower() for token in ("liquid", "bid-ask", "spread"))
        for reason in reprice_failures
    )
    latest_priced: dict[str, dict] = {}
    for reprice in reprices:
        outcome = reprice.get("outcome") or {}
        if outcome.get("status") != "priced":
            continue
        opportunity_id = candidate_to_opportunity.get(
            int(reprice["candidate_id"]), f"legacy-{reprice['candidate_id']}"
        )
        previous = latest_priced.get(opportunity_id)
        if previous is None or str(reprice["repriced_at"]) > str(previous["repriced_at"]):
            latest_priced[opportunity_id] = reprice
    by_bucket = Counter(item["outcome_bucket"] for item in latest_priced.values())
    opportunity_scores = {
        opportunity_id: int(candidate.get("score") or 0)
        for opportunity_id, candidate in latest_candidates.items()
    }
    return {
        "mode": "read_only_live_shadow_evaluation",
        "outcomes_are_hypothetical": True,
        "scan_count": observations,
        "candidate_count": len(grouped_candidates),
        "opportunity_count": len(grouped_candidates),
        "observation_count": observations,
        "reprice_count": len(reprices),
        "reprice_status_distribution": dict(sorted(reprice_statuses.items())),
        "rejection_reason_distribution": dict(sorted(reasons.items())),
        "score_distribution": _score_distribution(scores),
        "qualification_rate": round(qualified / len(grouped_candidates), 4)
        if grouped_candidates
        else 0.0,
        "qualified_candidate_count": qualified,
        "quote_freshness_failures": quote_failures,
        "liquidity_failures": liquidity_failures,
        "hypothetical_outcome_buckets": dict(sorted(by_bucket.items())),
        "hypothetical_pnl_by_threshold": {
            str(threshold): _pnl_metrics(
                [
                    reprice["outcome"]["net_hypothetical_pnl"]
                    for opportunity_id, reprice in latest_priced.items()
                    if abs(opportunity_scores.get(opportunity_id, 0)) >= threshold
                ]
            )
            for threshold in (40, 50, 60, 70)
        },
        "hypothetical_pnl_by_outcome_bucket": {
            bucket: _pnl_metrics(
                [
                    reprice["outcome"]["net_hypothetical_pnl"]
                    for reprice in latest_priced.values()
                    if reprice["outcome_bucket"] == bucket
                ]
            )
            for bucket in ("selected", "exploration", "shadow")
        },
    }


def _score_distribution(scores: list[int]) -> dict[str, int]:
    buckets = Counter()
    for score in scores:
        label = (
            "<=-70"
            if score <= -70
            else "-69..-40"
            if score <= -40
            else "-39..-1"
            if score < 0
            else "0"
            if score == 0
            else "1..39"
            if score < 40
            else "40..49"
            if score < 50
            else "50..59"
            if score < 60
            else "60..69"
            if score < 70
            else ">=70"
        )
        buckets[label] += 1
    return dict(sorted(buckets.items()))


def _pnl_metrics(pnls: list[float]) -> dict[str, Any]:
    values = [round(float(pnl), 2) for pnl in pnls]
    wins = [pnl for pnl in values if pnl > 0]
    losses = [pnl for pnl in values if pnl < 0]
    gross_losses = abs(sum(losses))
    return {
        "outcome_count": len(values),
        "net_hypothetical_pnl": round(sum(values), 2),
        "expectancy_usd_per_opportunity": round(sum(values) / len(values), 2) if values else 0.0,
        "win_rate": round(len(wins) / len(values), 4) if values else 0.0,
        "profit_factor": round(sum(wins) / gross_losses, 4) if gross_losses else None,
        "maximum_drawdown": max_drawdown(values),
        "confidence_intervals": confidence_intervals(values),
    }
