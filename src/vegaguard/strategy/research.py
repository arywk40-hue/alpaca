"""Offline-only scoring experiments. Nothing in this module can submit an order."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

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
