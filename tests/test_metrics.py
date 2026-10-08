"""Metric aggregation in core.metrics: latency percentiles, cost, error and quality."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.metrics import (
    EvaluationRecord,
    RequestResponseRecord,
    compute_metrics,
    compute_metrics_grouped,
    metrics_to_dict,
    records_from_evaluations,
    records_from_request_response_pairs,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def rec(
    response_id: str = "r",
    *,
    latency_ms: int | None = 100,
    cost_usd: str | None = "0.01",
    status: str = "success",
    model_name: str = "model-a",
    prompt_version: str = "v1",
) -> RequestResponseRecord:
    return RequestResponseRecord(
        response_id=response_id,
        prompt_name="summary",
        prompt_version=prompt_version,
        model_name=model_name,
        model_version="1",
        application_id="app",
        created_at=T0,
        latency_ms=latency_ms,
        cost_usd=Decimal(cost_usd) if cost_usd is not None else None,
        status=status,
    )


def test_empty_input_gives_counts_of_zero_and_no_averages() -> None:
    m = compute_metrics([])
    assert m.request_count == 0
    assert m.error_count == 0
    assert m.average_latency_ms is None
    assert m.p95_latency_ms is None
    assert m.p99_latency_ms is None
    assert m.total_cost_usd == 0
    assert m.average_cost_usd is None
    assert m.average_evaluation_score is None


def test_latency_percentiles_use_linear_interpolation() -> None:
    # Latencies 1..100 ms, shuffled order.
    records = [rec(str(i), latency_ms=v) for i, v in enumerate(reversed(range(1, 101)))]
    m = compute_metrics(records)
    assert m.average_latency_ms == pytest.approx(50.5)
    # Same definition as PostgreSQL percentile_cont / numpy "linear".
    assert m.p95_latency_ms == pytest.approx(95.05)
    assert m.p99_latency_ms == pytest.approx(99.01)


def test_single_latency_is_every_percentile() -> None:
    m = compute_metrics([rec(latency_ms=420)])
    assert m.average_latency_ms == m.p95_latency_ms == m.p99_latency_ms == 420


def test_missing_latency_is_excluded_not_counted_as_zero() -> None:
    m = compute_metrics([rec("a", latency_ms=None), rec("b", latency_ms=300)])
    assert m.request_count == 2
    assert m.average_latency_ms == 300


def test_cost_total_is_exact_decimal_and_average_skips_missing() -> None:
    records = [rec("a", cost_usd="0.10"), rec("b", cost_usd="0.20"), rec("c", cost_usd=None)]
    m = compute_metrics(records)
    assert m.total_cost_usd == Decimal("0.30")
    assert m.average_cost_usd == pytest.approx(0.15)


def test_every_non_success_status_counts_as_error() -> None:
    statuses = ["success", "partial_failure", "timeout", "error", "success"]
    m = compute_metrics([rec(str(i), status=s) for i, s in enumerate(statuses)])
    assert m.request_count == 5
    assert m.error_count == 3


def test_quality_score_averages_only_matching_scored_evaluations() -> None:
    records = [rec("a"), rec("b")]
    evaluations = [
        EvaluationRecord("a", 1.0),
        EvaluationRecord("a", 0.0),
        EvaluationRecord("b", 0.5),
        EvaluationRecord("b", None, outcome="pass"),  # no numeric score
        EvaluationRecord("other", 0.0),  # response not in this record set
    ]
    m = compute_metrics(records, evaluations)
    assert m.average_evaluation_score == pytest.approx(0.5)


def test_quality_score_is_none_without_scored_evaluations() -> None:
    m = compute_metrics([rec("a")], [EvaluationRecord("a", None, outcome="fail")])
    assert m.average_evaluation_score is None


def test_grouped_metrics_split_by_dimension_order() -> None:
    records = [
        rec("1", model_name="a", prompt_version="v1", latency_ms=100),
        rec("2", model_name="a", prompt_version="v2", latency_ms=200),
        rec("3", model_name="b", prompt_version="v1", latency_ms=300),
        rec("4", model_name="a", prompt_version="v1", latency_ms=500),
    ]
    groups = compute_metrics_grouped(records, ["model_name", "prompt_version"])
    assert set(groups) == {("a", "v1"), ("a", "v2"), ("b", "v1")}
    assert groups[("a", "v1")].request_count == 2
    assert groups[("a", "v1")].average_latency_ms == 300


def test_grouped_metrics_reject_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="Invalid group_by dimension: user_id"):
        compute_metrics_grouped([rec()], ["user_id"])


def test_metrics_to_dict_serialises_cost_as_string() -> None:
    d = metrics_to_dict(compute_metrics([rec(cost_usd="0.00100000")]))
    assert d["total_cost_usd"] == "0.00100000"
    assert d["request_count"] == 1


def test_records_are_built_from_orm_like_pairs() -> None:
    req = SimpleNamespace(
        prompt_name="p", prompt_version="v1", model_name="m", model_version="1",
        application_id="app", created_at=T0,
    )
    resp = SimpleNamespace(id=123, latency_ms=50, cost_usd=Decimal("0.5"), status="timeout")
    (r,) = records_from_request_response_pairs([(req, resp)])
    assert r.response_id == "123"
    assert r.status == "timeout"
    assert r.latency_ms == 50

    (e,) = records_from_evaluations([SimpleNamespace(response_id=123, score=0.7, outcome="pass")])
    assert e == EvaluationRecord("123", 0.7, "pass")
