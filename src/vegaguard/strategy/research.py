"""Offline-only scoring experiments. Nothing in this module can submit an order."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .backtest import HistoricalBacktester, HistoricalBacktestResult
from .replay import ReplayObservation, ReplayResult, run_replay
from .scorer import score_signal, score_signal_conflict_tolerant


def _variant_report(result: ReplayResult) -> dict[str, Any]:
    regimes = Counter(decision.regime.value for decision in result.decisions)
    rejections = Counter(
        reason
        for decision in result.decisions
        if decision.regime.value not in {"bullish", "bearish"}
        for reason in decision.reasons
    )
    return {
        "trade_count": result.summary.trade_count,
        "performance": result.summary.as_dict(),
        "regime_distribution": dict(sorted(regimes.items())),
        "rejection_reasons": dict(sorted(rejections.items())),
    }


def compare_replay_scorers(observations: list[ReplayObservation]) -> dict[str, Any]:
    """Compare baseline and experimental scoring using identical known-at-time inputs."""
    baseline = run_replay(observations, scorer=score_signal)
    conflict_tolerant = run_replay(observations, scorer=score_signal_conflict_tolerant)
    return {
        "mode": "offline_research_only",
        "live_execution": "disabled_by_design",
        "observations": len(observations),
        "baseline": _variant_report(baseline),
        "conflict_tolerant": _variant_report(conflict_tolerant),
        "threshold_comparison": compare_score_thresholds(observations),
        "out_of_sample_assessment": "unavailable: no normalized historical option dataset was supplied",
        "limitations": [
            "The experimental scorer is not connected to the live scanner or execution path.",
            "Replay output is not evidence of future or live performance.",
            "Do not promote this scorer without a separate, point-in-time out-of-sample backtest.",
        ],
    }


def compare_score_thresholds(
    observations: list[ReplayObservation], thresholds: Iterable[int] = (40, 50, 60, 70)
) -> dict[str, dict[str, Any]]:
    """Replay the unchanged production scorer at explicit research thresholds.

    This report is offline-only. It neither changes the live 70-point setting
    nor recommends promotion from a small sample.
    """
    report: dict[str, dict[str, Any]] = {}
    for threshold in thresholds:
        if not 1 <= threshold <= 100:
            raise ValueError("research thresholds must be between 1 and 100")
        result = run_replay(
            observations,
            scorer=lambda inputs, threshold=threshold: score_signal(inputs, threshold=threshold),
        )
        report[str(threshold)] = _variant_report(result)
    return report


def confidence_calibration_study(
    result: HistoricalBacktestResult,
    *,
    minimum_observations_per_bucket: int = 30,
) -> dict[str, Any]:
    """Map offline score strength to empirical completed-option outcomes.

    The production score is not itself a probability. This routine only
    displays an empirical mapping for research review and cannot alter live
    confidence, risk policy, score thresholds, or execution settings.
    """
    if minimum_observations_per_bucket < 1:
        raise ValueError("minimum_observations_per_bucket must be positive")
    grouped: dict[tuple[str, str], list[float]] = {}
    for trade in result.trades:
        key = (_confidence_bucket(abs(int(trade.entry_score))), trade.regime)
        grouped.setdefault(key, []).append(float(trade.net_pnl))
    buckets = [
        _calibration_bucket(label, regime, pnls, minimum_observations_per_bucket)
        for (label, regime), pnls in sorted(grouped.items())
    ]
    real_history = result.data_classification == "REAL HISTORICAL OPTION BACKTEST"
    eligible_buckets = [bucket for bucket in buckets if bucket["sufficient_observations"]]
    return {
        "mode": "offline_confidence_calibration_research",
        "live_execution": "disabled_by_design",
        "production_threshold": 70,
        "data_classification": result.data_classification,
        "completed_trade_count": len(result.trades),
        "minimum_observations_per_bucket": minimum_observations_per_bucket,
        "status": (
            "ready_for_research_review"
            if real_history and eligible_buckets
            else "insufficient_real_historical_evidence"
        ),
        "buckets": buckets,
        "eligible_bucket_count": len(eligible_buckets),
        "automatic_live_calibration": False,
        "limitations": [
            "Score strength is not a predicted probability without genuine historical options outcomes.",
            "The displayed empirical rate includes the conservative bid/ask, fee, and slippage assumptions in the supplied backtest.",
            "This report cannot change production thresholds, sizing, risk gates, or paper execution settings.",
        ],
    }


def _confidence_bucket(score: int) -> str:
    if score < 40:
        return "<40"
    if score < 50:
        return "40-49"
    if score < 60:
        return "50-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    return "80-100"


def _calibration_bucket(
    score_bucket: str, regime: str, pnls: list[float], minimum_observations: int
) -> dict[str, Any]:
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    # Laplace smoothing avoids presenting a tiny sample as certain. It is a
    # research display value, never a live-trading input.
    smoothed_win_probability = round((len(wins) + 1) / (len(pnls) + 2), 4)
    return {
        "score_bucket": score_bucket,
        "regime": regime,
        "trade_count": len(pnls),
        "win_count": len(wins),
        "observed_win_rate": round(len(wins) / len(pnls), 4) if pnls else None,
        "smoothed_empirical_win_probability": smoothed_win_probability,
        "average_net_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "net_pnl": round(sum(pnls), 2),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
        "sufficient_observations": len(pnls) >= minimum_observations,
    }


def walk_forward_threshold_study(
    data_dir: str | Path,
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
    thresholds: Iterable[int] = (40, 50, 60, 70),
    train_fraction: float = 0.70,
    minimum_in_sample_trades: int = 30,
    initial_equity: float = 100_000.0,
    max_open_positions: int = 3,
    max_contracts_per_trade: int = 1,
    fee_per_contract_usd: float = 0.0,
    slippage_per_leg_usd: float = 0.0,
    quote_derived_risk_free_rate: float = 0.04,
    exit_horizon_minutes: int | None = None,
) -> dict[str, Any]:
    """Evaluate score thresholds on a chronological train/test split, offline only.

    The selection uses only the earlier in-sample segment. The later segment is
    held out for reporting, never for threshold selection. This routine cannot
    modify settings, call market data, or submit an order.
    """
    if end <= start:
        raise ValueError("end must be after start")
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between zero and one")
    if minimum_in_sample_trades < 1:
        raise ValueError("minimum_in_sample_trades must be positive")
    normalized_thresholds = tuple(sorted({int(value) for value in thresholds}))
    if not normalized_thresholds or any(not 1 <= value <= 100 for value in normalized_thresholds):
        raise ValueError("research thresholds must be between 1 and 100")
    split_at = start + (end - start) * train_fraction
    test_start = split_at + timedelta(microseconds=1)

    def run_window(threshold: int, window_start: datetime, window_end: datetime) -> dict[str, Any]:
        return (
            HistoricalBacktester(
                data_dir,
                symbols=symbols,
                start=window_start,
                end=window_end,
                initial_equity=initial_equity,
                max_open_positions=max_open_positions,
                max_contracts_per_trade=max_contracts_per_trade,
                score_threshold=threshold,
                fee_per_contract_usd=fee_per_contract_usd,
                slippage_per_leg_usd=slippage_per_leg_usd,
                quote_derived_risk_free_rate=quote_derived_risk_free_rate,
                exit_horizon_minutes=exit_horizon_minutes,
            )
            .run()
            .as_dict()
        )

    results = {
        str(threshold): {
            "in_sample": run_window(threshold, start, split_at),
            "out_of_sample": run_window(threshold, test_start, end),
        }
        for threshold in normalized_thresholds
    }
    eligible = [
        threshold
        for threshold in normalized_thresholds
        if results[str(threshold)]["in_sample"]["classification"]
        == "REAL HISTORICAL OPTION BACKTEST"
        and results[str(threshold)]["in_sample"]["trade_count"] >= minimum_in_sample_trades
    ]
    selected_threshold = (
        max(
            eligible,
            key=lambda threshold: (
                float(results[str(threshold)]["in_sample"]["net_pnl"]),
                float(results[str(threshold)]["in_sample"]["profit_factor"] or 0.0),
                threshold,
            ),
        )
        if eligible
        else None
    )
    selected_out_of_sample = (
        results[str(selected_threshold)]["out_of_sample"]
        if selected_threshold is not None
        else None
    )
    return {
        "mode": "offline_point_in_time_walk_forward_research",
        "live_execution": "disabled_by_design",
        "production_threshold": 70,
        "split": {
            "in_sample_start": start.isoformat(),
            "in_sample_end": split_at.isoformat(),
            "out_of_sample_start": test_start.isoformat(),
            "out_of_sample_end": end.isoformat(),
            "train_fraction": train_fraction,
        },
        "minimum_in_sample_trades": minimum_in_sample_trades,
        "cost_assumptions": {
            "fee_per_contract_usd": fee_per_contract_usd,
            "slippage_per_leg_usd": slippage_per_leg_usd,
            "quote_derived_risk_free_rate": quote_derived_risk_free_rate,
            "exit_horizon_minutes": exit_horizon_minutes,
            "bid_ask_method": "opening long ask minus short bid; closing long bid minus short ask",
        },
        "thresholds": results,
        "selected_threshold_from_in_sample": selected_threshold,
        "selected_threshold_out_of_sample": selected_out_of_sample,
        "automatic_production_promotion": False,
        "recommendation": (
            "INSUFFICIENT EVIDENCE: no real, sufficiently sized in-sample option result"
            if selected_threshold is None
            else "research selection only: review held-out performance, drawdown, and execution risk manually"
        ),
    }
