"""Version comparison in core.comparison."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.comparison import (
    compare_metrics,
    compare_model_versions,
    compare_prompt_versions,
    comparison_to_dict,
)
from core.metrics import AggregatedMetrics


def metrics(**kw) -> AggregatedMetrics:
    defaults = dict(
        request_count=100,
        average_latency_ms=1000.0,
        total_cost_usd=Decimal("1.00"),
        average_cost_usd=0.01,
        average_evaluation_score=0.80,
    )
    defaults.update(kw)
    return AggregatedMetrics(**defaults)


def test_better_candidate_is_reported_as_improvement() -> None:
    baseline = metrics()
    candidate = metrics(
        average_latency_ms=800.0,
        total_cost_usd=Decimal("0.75"),
        average_cost_usd=0.0075,
        average_evaluation_score=0.90,
    )
    result = compare_prompt_versions(baseline, candidate)

    assert result.comparison_type == "prompt_version"
    assert result.average_latency_ms.delta == pytest.approx(-200)
    assert result.average_latency_ms.delta_percent == pytest.approx(-20)
    assert result.total_cost_usd.delta == pytest.approx(-0.25)
    assert result.average_evaluation_score.delta == pytest.approx(0.10)
    assert result.summary == [
        "Latency: candidate 200ms faster (improvement)",
        "Total cost: candidate $0.250000 cheaper (improvement)",
        "Eval score: candidate 0.10 higher (improvement)",
    ]


def test_worse_candidate_is_reported_as_regression() -> None:
    result = compare_model_versions(
        metrics(),
        metrics(average_latency_ms=1500.0, total_cost_usd=Decimal("2.00"), average_evaluation_score=0.5),
    )
    assert result.comparison_type == "model_version"
    assert result.summary == [
        "Latency: candidate 500ms slower (regression)",
        "Total cost: candidate $1.000000 more expensive (regression)",
        "Eval score: candidate 0.30 lower (regression)",
    ]


def test_identical_metrics_report_no_change() -> None:
    result = compare_metrics(metrics(), metrics())
    assert result.summary == ["Latency: no change", "Total cost: no change", "Eval score: no change"]
    assert result.average_latency_ms.delta_percent == 0


def test_missing_value_makes_metric_not_comparable() -> None:
    result = compare_metrics(metrics(average_evaluation_score=None), metrics())
    assert result.average_evaluation_score.comparable is False
    assert result.average_evaluation_score.delta is None
    assert not any(line.startswith("Eval score") for line in result.summary)


def test_zero_baseline_has_no_percentage() -> None:
    result = compare_metrics(
        metrics(total_cost_usd=Decimal("0")), metrics(total_cost_usd=Decimal("0.5"))
    )
    assert result.total_cost_usd.comparable is True
    assert result.total_cost_usd.delta_percent is None


def test_different_sample_sizes_are_flagged() -> None:
    result = compare_metrics(metrics(request_count=100), metrics(request_count=40))
    assert "Request count differs: baseline=100, candidate=40" in result.summary


def test_comparison_to_dict_is_json_friendly() -> None:
    d = comparison_to_dict(compare_metrics(metrics(), metrics(total_cost_usd=Decimal("1.50"))))
    assert d["total_cost_usd"]["baseline"] == "1.00"
    assert d["total_cost_usd"]["candidate"] == "1.50"
    assert d["total_cost_usd"]["delta"] == pytest.approx(0.5)
    assert d["average_latency_ms"]["comparable"] is True
    assert isinstance(d["summary"], list)
