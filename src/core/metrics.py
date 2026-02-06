"""
Metrics aggregation logic for LLM Evaluation & Monitoring Platform.
Pure functions that compute aggregates from repository query results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional, Sequence

# -----------------------------------------------------------------------------
# Input structures (can be built from repository results)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestResponseRecord:
    """
    Single request-response row for aggregation.
    Build from repository fetch_requests_and_responses_by_time_range result.
    """

    response_id: str
    prompt_name: str
    prompt_version: str
    model_name: str
    model_version: str
    application_id: str
    created_at: Any  # datetime
    latency_ms: Optional[int]
    cost_usd: Optional[Decimal]
    status: str


@dataclass(frozen=True)
class EvaluationRecord:
    """Single evaluation result for score aggregation."""

    response_id: str
    score: Optional[float]
    outcome: Optional[str] = None


def records_from_request_response_pairs(
    pairs: Sequence[tuple[Any, Any]],
) -> list[RequestResponseRecord]:
    """
    Convert repository fetch result to RequestResponseRecord list.
    Expects (request, response) tuples with attribute access.
    """
    records = []
    for req, resp in pairs:
        records.append(
            RequestResponseRecord(
                response_id=str(resp.id),
                prompt_name=req.prompt_name,
                prompt_version=req.prompt_version,
                model_name=req.model_name,
                model_version=req.model_version,
                application_id=req.application_id,
                created_at=req.created_at,
                latency_ms=resp.latency_ms,
                cost_usd=resp.cost_usd,
                status=resp.status,
            )
        )
    return records


def records_from_evaluations(evals: Sequence[Any]) -> list[EvaluationRecord]:
    """
    Convert evaluation objects to EvaluationRecord list.
    Expects objects with response_id, score, outcome attributes.
    """
    return [
        EvaluationRecord(
            response_id=str(e.response_id),
            score=e.score,
            outcome=e.outcome,
        )
        for e in evals
    ]


# -----------------------------------------------------------------------------
# Output structure
# -----------------------------------------------------------------------------


@dataclass
class AggregatedMetrics:
    """Aggregated metrics for a set of request-response records."""

    request_count: int = 0
    error_count: int = 0
    average_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    p99_latency_ms: Optional[float] = None
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    average_cost_usd: Optional[float] = None
    average_evaluation_score: Optional[float] = None


# -----------------------------------------------------------------------------
# Aggregation logic
# -----------------------------------------------------------------------------


def _percentile(sorted_values: list[float], p: float) -> Optional[float]:
    """Compute percentile from sorted list. p in [0, 1]. Returns None if empty."""
    if not sorted_values:
        return None
    n = len(sorted_values)
    idx = p * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    if lo == hi:
        return sorted_values[lo]
    frac = idx - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])


def _decimal_to_float(d: Optional[Decimal]) -> Optional[float]:
    """Convert Decimal to float for aggregation. Returns None if input is None."""
    if d is None:
        return None
    return float(d)


def compute_metrics(
    records: Sequence[RequestResponseRecord],
    evaluations: Optional[Sequence[EvaluationRecord]] = None,
) -> AggregatedMetrics:
    """
    Compute aggregated metrics from request-response records.

    Args:
        records: Request-response records (from repository or records_from_*).
        evaluations: Optional evaluation records for average score.

    Returns:
        AggregatedMetrics. Latency/cost metrics are None when no valid values.
    """
    records = list(records)
    request_count = len(records)
    error_count = sum(1 for r in records if r.status != "success")

    # Latency: exclude None
    latency_values = [r.latency_ms for r in records if r.latency_ms is not None]
    latency_values = [int(v) for v in latency_values]
    latency_values.sort()

    average_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    p99_latency_ms: Optional[float] = None
    if latency_values:
        average_latency_ms = sum(latency_values) / len(latency_values)
        p95_latency_ms = _percentile(latency_values, 0.95)
        p99_latency_ms = _percentile(latency_values, 0.99)

    # Cost: treat None as 0 for total; average over non-None
    cost_values = [_decimal_to_float(r.cost_usd) for r in records if r.cost_usd is not None]
    total_cost_usd = sum(
        (r.cost_usd if r.cost_usd is not None else Decimal("0")) for r in records
    )
    average_cost_usd: Optional[float] = None
    if cost_values:
        average_cost_usd = sum(cost_values) / len(cost_values)

    # Evaluation score: average over records with numeric score
    average_evaluation_score: Optional[float] = None
    if evaluations:
        response_ids = {r.response_id for r in records}
        eval_by_response: dict[str, list[float]] = {}
        for e in evaluations:
            if e.response_id in response_ids and e.score is not None:
                eval_by_response.setdefault(e.response_id, []).append(float(e.score))
        if eval_by_response:
            all_scores = [s for scores in eval_by_response.values() for s in scores]
            average_evaluation_score = sum(all_scores) / len(all_scores)

    return AggregatedMetrics(
        request_count=request_count,
        error_count=error_count,
        average_latency_ms=average_latency_ms,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        total_cost_usd=total_cost_usd,
        average_cost_usd=average_cost_usd,
        average_evaluation_score=average_evaluation_score,
    )


def compute_metrics_grouped(
    records: Sequence[RequestResponseRecord],
    group_by: Sequence[str],
    evaluations: Optional[Sequence[EvaluationRecord]] = None,
) -> dict[tuple[str, ...], AggregatedMetrics]:
    """
    Compute metrics grouped by dimension values.

    Args:
        records: Request-response records.
        group_by: Dimension names: model_name, model_version, prompt_name,
                  prompt_version, application_id. Order defines the group key.
        evaluations: Optional evaluation records for average score.

    Returns:
        Dict mapping (dim_value_1, dim_value_2, ...) to AggregatedMetrics.
        Group keys follow the order of group_by.
    """
    valid_dims = {"model_name", "model_version", "prompt_name", "prompt_version", "application_id"}
    for dim in group_by:
        if dim not in valid_dims:
            raise ValueError(f"Invalid group_by dimension: {dim}")

    groups: dict[tuple[str, ...], list[RequestResponseRecord]] = {}
    for r in records:
        key = tuple(getattr(r, dim) for dim in group_by)
        groups.setdefault(key, []).append(r)

    result = {}
    for key, group_records in groups.items():
        result[key] = compute_metrics(group_records, evaluations)
    return result


def metrics_to_dict(m: AggregatedMetrics) -> dict[str, Any]:
    """Convert AggregatedMetrics to a JSON-serializable dict."""
    return {
        "request_count": m.request_count,
        "error_count": m.error_count,
        "average_latency_ms": m.average_latency_ms,
        "p95_latency_ms": m.p95_latency_ms,
        "p99_latency_ms": m.p99_latency_ms,
        "total_cost_usd": str(m.total_cost_usd),
        "average_cost_usd": m.average_cost_usd,
        "average_evaluation_score": m.average_evaluation_score,
    }
