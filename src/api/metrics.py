"""
GET /metrics endpoint for LLM Evaluation & Monitoring Platform.
Returns aggregated metrics for request-response data in a time range.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.metrics import (
    compute_metrics,
    metrics_to_dict,
    records_from_evaluations,
    records_from_request_response_pairs,
)
from storage.repository import (
    RepositoryError,
    fetch_evaluations_for_responses,
    fetch_requests_and_responses_by_time_range,
)

from .logs import get_db

router = APIRouter(prefix="/metrics", tags=["metrics"])


# -----------------------------------------------------------------------------
# Query validation
# -----------------------------------------------------------------------------


def _parse_datetime(v: str | datetime) -> datetime:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        s = v.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            raise ValueError("Invalid datetime format. Use ISO 8601 (e.g. 2024-01-15T00:00:00Z).")
    raise ValueError("Expected datetime or ISO 8601 string")


# -----------------------------------------------------------------------------
# Response model
# -----------------------------------------------------------------------------


class MetricsResponse(BaseModel):
    """Stable JSON structure for metrics response."""

    request_count: int
    error_count: int
    average_latency_ms: Optional[float]
    p95_latency_ms: Optional[float]
    p99_latency_ms: Optional[float]
    total_cost_usd: str
    average_cost_usd: Optional[float]
    average_evaluation_score: Optional[float]


class ErrorDetail(BaseModel):
    """Error response body."""

    error: str
    detail: Optional[str] = None


# -----------------------------------------------------------------------------
# Endpoint
# -----------------------------------------------------------------------------


@router.get(
    "",
    response_model=MetricsResponse,
    responses={
        400: {"model": ErrorDetail, "description": "Invalid query parameters"},
        500: {"model": ErrorDetail, "description": "Database error"},
    },
)
def get_metrics(
    start_time: str = Query(..., description="ISO 8601 datetime, inclusive start"),
    end_time: str = Query(..., description="ISO 8601 datetime, inclusive end"),
    model_name: Optional[str] = Query(None, max_length=255),
    model_version: Optional[str] = Query(None, max_length=128),
    prompt_name: Optional[str] = Query(None, max_length=255),
    prompt_version: Optional[str] = Query(None, max_length=128),
    db: Session = Depends(get_db),
) -> MetricsResponse:
    """
    Return aggregated metrics for logged requests in the given time range.

    Optional filters: model_name, model_version, prompt_name, prompt_version.
    average_evaluation_score is the mean of all numeric evaluation scores stored
    for the matching responses (null when there are none).
    """
    try:
        start = _parse_datetime(start_time)
        end = _parse_datetime(end_time)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_datetime", "detail": str(e)},
        ) from e

    if end < start:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_range", "detail": "end_time must be >= start_time"},
        )

    try:
        pairs = fetch_requests_and_responses_by_time_range(
            db,
            start_time=start,
            end_time=end,
            model_name=model_name,
            model_version=model_version,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )
        evaluations = fetch_evaluations_for_responses(
            db, response_ids=[resp.id for _, resp in pairs]
        )
    except RepositoryError as e:
        raise HTTPException(
            status_code=500,
            detail={"error": "database_error", "detail": str(e.__cause__ or e)},
        ) from e

    records = records_from_request_response_pairs(pairs)
    aggregated = compute_metrics(records, records_from_evaluations(evaluations))
    data = metrics_to_dict(aggregated)

    return MetricsResponse(
        request_count=data["request_count"],
        error_count=data["error_count"],
        average_latency_ms=data["average_latency_ms"],
        p95_latency_ms=data["p95_latency_ms"],
        p99_latency_ms=data["p99_latency_ms"],
        total_cost_usd=data["total_cost_usd"],
        average_cost_usd=data["average_cost_usd"],
        average_evaluation_score=data["average_evaluation_score"],
    )
