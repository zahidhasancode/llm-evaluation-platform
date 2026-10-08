"""
Comparison logic for LLM Evaluation & Monitoring Platform.
Compares aggregated metric summaries (prompt versions, model versions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .metrics import AggregatedMetrics


@dataclass
class MetricDelta:
    """Delta for a single metric. direction: 'lower_better' | 'higher_better'."""

    baseline: float | Decimal | None
    candidate: float | Decimal | None
    delta: float | Decimal | None
    delta_percent: float | None
    comparable: bool  # True if both values present and delta computed


@dataclass
class ComparisonResult:
    """Structured comparison between baseline and candidate metrics."""

    comparison_type: str  # "prompt_version" | "model_version"
    request_count_baseline: int
    request_count_candidate: int
    average_latency_ms: MetricDelta
    total_cost_usd: MetricDelta
    average_cost_usd: MetricDelta
    average_evaluation_score: MetricDelta
    summary: list[str] = field(default_factory=list)


def _decimal_to_float(d: Decimal | float | None) -> float | None:
    if d is None:
        return None
    return float(d)


def _compute_delta(
    baseline: float | Decimal | None,
    candidate: float | Decimal | None,
    lower_is_better: bool,
) -> MetricDelta:
    """
    Compute delta between candidate and baseline.
    delta = candidate - baseline. Negative delta for latency/cost means improvement.
    """
    b_val = _decimal_to_float(baseline) if baseline is not None else None
    c_val = _decimal_to_float(candidate) if candidate is not None else None

    if b_val is None or c_val is None:
        return MetricDelta(
            baseline=baseline,
            candidate=candidate,
            delta=None,
            delta_percent=None,
            comparable=False,
        )

    delta = c_val - b_val
    if b_val == 0:
        delta_pct = 0.0 if delta == 0 else None
    else:
        delta_pct = (delta / abs(b_val)) * 100

    return MetricDelta(
        baseline=baseline,
        candidate=candidate,
        delta=delta,
        delta_percent=delta_pct,
        comparable=True,
    )


def _build_summary(result: ComparisonResult) -> list[str]:
    """Build decision-oriented summary lines."""
    lines = []

    if result.average_latency_ms.comparable and result.average_latency_ms.delta is not None:
        d = result.average_latency_ms.delta
        if d < 0:
            lines.append(f"Latency: candidate {abs(d):.0f}ms faster (improvement)")
        elif d > 0:
            lines.append(f"Latency: candidate {d:.0f}ms slower (regression)")
        else:
            lines.append("Latency: no change")

    if result.total_cost_usd.comparable and result.total_cost_usd.delta is not None:
        d = float(result.total_cost_usd.delta)
        if d < 0:
            lines.append(f"Total cost: candidate ${abs(d):.6f} cheaper (improvement)")
        elif d > 0:
            lines.append(f"Total cost: candidate ${d:.6f} more expensive (regression)")
        else:
            lines.append("Total cost: no change")

    score = result.average_evaluation_score
    if score.comparable and score.delta is not None:
        d = float(score.delta)
        if d > 0:
            lines.append(f"Eval score: candidate {d:.2f} higher (improvement)")
        elif d < 0:
            lines.append(f"Eval score: candidate {abs(d):.2f} lower (regression)")
        else:
            lines.append("Eval score: no change")

    if result.request_count_baseline != result.request_count_candidate:
        lines.append(
            f"Request count differs: baseline={result.request_count_baseline}, "
            f"candidate={result.request_count_candidate}"
        )

    return lines


def compare_metrics(
    baseline: AggregatedMetrics,
    candidate: AggregatedMetrics,
    comparison_type: str = "metrics",
) -> ComparisonResult:
    """
    Compare two aggregated metric summaries. Compute deltas and summary.

    Args:
        baseline: Baseline (e.g. current prompt or model).
        candidate: Candidate (e.g. new prompt or model).
        comparison_type: Label for the comparison ("prompt_version", "model_version", etc.).

    Returns:
        ComparisonResult with deltas and decision-oriented summary.
    """
    latency_delta = _compute_delta(
        baseline.average_latency_ms,
        candidate.average_latency_ms,
        lower_is_better=True,
    )
    total_cost_delta = _compute_delta(
        baseline.total_cost_usd,
        candidate.total_cost_usd,
        lower_is_better=True,
    )
    avg_cost_delta = _compute_delta(
        baseline.average_cost_usd,
        candidate.average_cost_usd,
        lower_is_better=True,
    )
    score_delta = _compute_delta(
        baseline.average_evaluation_score,
        candidate.average_evaluation_score,
        lower_is_better=False,
    )

    result = ComparisonResult(
        comparison_type=comparison_type,
        request_count_baseline=baseline.request_count,
        request_count_candidate=candidate.request_count,
        average_latency_ms=latency_delta,
        total_cost_usd=total_cost_delta,
        average_cost_usd=avg_cost_delta,
        average_evaluation_score=score_delta,
        summary=[],
    )
    result.summary = _build_summary(result)
    return result


def compare_prompt_versions(
    baseline: AggregatedMetrics,
    candidate: AggregatedMetrics,
) -> ComparisonResult:
    """Compare two prompt version metric summaries."""
    return compare_metrics(baseline, candidate, comparison_type="prompt_version")


def compare_model_versions(
    baseline: AggregatedMetrics,
    candidate: AggregatedMetrics,
) -> ComparisonResult:
    """Compare two model version metric summaries."""
    return compare_metrics(baseline, candidate, comparison_type="model_version")


def comparison_to_dict(result: ComparisonResult) -> dict[str, Any]:
    """Convert ComparisonResult to a JSON-serializable dict."""
    def delta_to_dict(d: MetricDelta) -> dict[str, Any]:
        return {
            "baseline": str(d.baseline) if isinstance(d.baseline, Decimal) else d.baseline,
            "candidate": str(d.candidate) if isinstance(d.candidate, Decimal) else d.candidate,
            "delta": float(d.delta) if isinstance(d.delta, Decimal) else d.delta,
            "delta_percent": d.delta_percent,
            "comparable": d.comparable,
        }

    return {
        "comparison_type": result.comparison_type,
        "request_count_baseline": result.request_count_baseline,
        "request_count_candidate": result.request_count_candidate,
        "average_latency_ms": delta_to_dict(result.average_latency_ms),
        "total_cost_usd": delta_to_dict(result.total_cost_usd),
        "average_cost_usd": delta_to_dict(result.average_cost_usd),
        "average_evaluation_score": delta_to_dict(result.average_evaluation_score),
        "summary": result.summary,
    }
