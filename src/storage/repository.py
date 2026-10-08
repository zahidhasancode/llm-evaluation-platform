"""
Repository layer for LLM Evaluation & Monitoring Platform.
Provides session-based data access for requests, responses, and evaluations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .models import LLMEvaluation, LLMRequest, LLMResponse


class RepositoryError(Exception):
    """Raised when a repository operation fails due to a database error."""

    pass


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """
    Normalise an id to uuid.UUID.

    The UUID columns use as_uuid=True. PostgreSQL drivers accept strings, but
    SQLAlchemy's non-native UUID handling (e.g. SQLite) requires UUID objects.
    """
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError as e:
        raise RepositoryError(f"Invalid UUID: {value!r}") from e


def insert_llm_request(
    session: Session,
    *,
    prompt_name: str,
    prompt_version: str,
    model_name: str,
    model_version: str,
    application_id: str,
    input_text: str,
    metadata_: Optional[dict[str, Any]] = None,
) -> LLMRequest:
    """
    Insert an LLM request record.

    Args:
        session: SQLAlchemy session. Caller owns transaction lifecycle.
        prompt_name: Human-readable prompt identifier.
        prompt_version: Version of the prompt (e.g. git sha, semantic version).
        model_name: Model identifier (e.g. provider name, model family).
        model_version: Model version (e.g. gpt-4-2024-01).
        application_id: Application or service that made the request.
        input_text: The prompt text sent to the model.
        metadata_: Optional extensible metadata. Do not store PII in plaintext.

    Returns:
        The created LLMRequest instance with id populated.

    Raises:
        RepositoryError: If the insert fails (e.g. constraint violation).
    """
    try:
        request = LLMRequest(
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            model_name=model_name,
            model_version=model_version,
            application_id=application_id,
            input_text=input_text,
            metadata_=metadata_,
        )
        session.add(request)
        session.flush()
        return request
    except IntegrityError as e:
        session.rollback()
        raise RepositoryError("Insert failed: constraint violation") from e
    except SQLAlchemyError as e:
        session.rollback()
        raise RepositoryError("Insert failed: database error") from e


def insert_llm_response(
    session: Session,
    *,
    request_id: uuid.UUID | str,
    output_text: Optional[str] = None,
    input_token_count: Optional[int] = None,
    output_token_count: Optional[int] = None,
    latency_ms: Optional[int] = None,
    cost_usd: Optional[Decimal] = None,
    status: str,
    error_type: Optional[str] = None,
    error_code: Optional[str] = None,
    metadata_: Optional[dict[str, Any]] = None,
) -> LLMResponse:
    """
    Insert an LLM response record linked to a request.

    Args:
        session: SQLAlchemy session. Caller owns transaction lifecycle.
        request_id: UUID (or UUID string) of the LLMRequest this response belongs to.
        output_text: Model output text. Optional for failed requests.
        input_token_count: Number of input tokens.
        output_token_count: Number of output tokens.
        latency_ms: Response latency in milliseconds.
        cost_usd: Cost in USD for this response.
        status: One of 'success', 'partial_failure', 'timeout', 'error'.
        error_type: Error type when status indicates failure.
        error_code: Error code when status indicates failure.
        metadata_: Optional extensible metadata.

    Returns:
        The created LLMResponse instance with id populated.

    Raises:
        RepositoryError: If the insert fails (e.g. FK violation, check constraint).
    """
    request_uuid = _as_uuid(request_id)
    try:
        response = LLMResponse(
            request_id=request_uuid,
            output_text=output_text,
            input_token_count=input_token_count,
            output_token_count=output_token_count,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
            error_type=error_type,
            error_code=error_code,
            metadata_=metadata_,
        )
        session.add(response)
        session.flush()
        return response
    except IntegrityError as e:
        session.rollback()
        raise RepositoryError("Insert failed: constraint violation") from e
    except SQLAlchemyError as e:
        session.rollback()
        raise RepositoryError("Insert failed: database error") from e


def insert_evaluation_results(
    session: Session,
    *,
    results: list[dict[str, Any]],
) -> list[LLMEvaluation]:
    """
    Insert evaluation result records in bulk.

    Each dict in results must have: response_id, evaluation_run_id, criterion_name.
    Each dict must have at least one of: score, outcome.
    Optional: criterion_version, result_metadata.

    Args:
        session: SQLAlchemy session. Caller owns transaction lifecycle.
        results: List of dicts, each representing one evaluation result.

    Returns:
        List of created LLMEvaluation instances.

    Raises:
        RepositoryError: If the insert fails (e.g. FK violation, check constraint).
    """
    try:
        evaluations = []
        for r in results:
            if "score" not in r and "outcome" not in r:
                raise RepositoryError(
                    "Each result must have at least one of 'score' or 'outcome'"
                )
            ev = LLMEvaluation(
                response_id=_as_uuid(r["response_id"]),
                evaluation_run_id=_as_uuid(r["evaluation_run_id"]),
                criterion_name=r["criterion_name"],
                criterion_version=r.get("criterion_version"),
                score=r.get("score"),
                outcome=r.get("outcome"),
                result_metadata=r.get("result_metadata"),
            )
            session.add(ev)
            evaluations.append(ev)
        session.flush()
        return evaluations
    except IntegrityError as e:
        session.rollback()
        raise RepositoryError("Insert failed: constraint violation") from e
    except SQLAlchemyError as e:
        session.rollback()
        raise RepositoryError("Insert failed: database error") from e


def fetch_requests_and_responses_by_time_range(
    session: Session,
    *,
    start_time: datetime,
    end_time: datetime,
    application_id: Optional[str] = None,
    prompt_name: Optional[str] = None,
    prompt_version: Optional[str] = None,
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
) -> list[tuple[LLMRequest, LLMResponse]]:
    """
    Fetch request-response pairs within a time range.

    Filters by llm_requests.created_at. Optional filters for application,
    prompt, and model. Only returns pairs that have a response (inner join).

    Args:
        session: SQLAlchemy session.
        start_time: Inclusive start of time range (timezone-aware).
        end_time: Inclusive end of time range (timezone-aware).
        application_id: Optional filter by application.
        prompt_name: Optional filter by prompt name.
        prompt_version: Optional filter by prompt version.
        model_name: Optional filter by model name.
        model_version: Optional filter by model version.

    Returns:
        List of (LLMRequest, LLMResponse) tuples, ordered by created_at ascending.

    Raises:
        RepositoryError: If the query fails.
    """
    try:
        stmt = (
            select(LLMRequest, LLMResponse)
            .join(LLMResponse, LLMRequest.id == LLMResponse.request_id)
            .where(LLMRequest.created_at >= start_time)
            .where(LLMRequest.created_at <= end_time)
            .order_by(LLMRequest.created_at.asc())
        )
        if application_id is not None:
            stmt = stmt.where(LLMRequest.application_id == application_id)
        if prompt_name is not None:
            stmt = stmt.where(LLMRequest.prompt_name == prompt_name)
        if prompt_version is not None:
            stmt = stmt.where(LLMRequest.prompt_version == prompt_version)
        if model_name is not None:
            stmt = stmt.where(LLMRequest.model_name == model_name)
        if model_version is not None:
            stmt = stmt.where(LLMRequest.model_version == model_version)

        rows = session.execute(stmt).all()
        return [(r, resp) for r, resp in rows]
    except SQLAlchemyError as e:
        raise RepositoryError("Fetch failed: database error") from e


def fetch_evaluations_for_responses(
    session: Session,
    *,
    response_ids: list[uuid.UUID | str],
) -> list[LLMEvaluation]:
    """
    Fetch all evaluation results stored for the given responses.

    Args:
        session: SQLAlchemy session.
        response_ids: Response ids (UUID or UUID string). Empty list returns [].

    Returns:
        List of LLMEvaluation rows, in no particular order.

    Raises:
        RepositoryError: If an id is not a UUID or the query fails.
    """
    if not response_ids:
        return []
    ids = [_as_uuid(r) for r in response_ids]
    try:
        stmt = select(LLMEvaluation).where(LLMEvaluation.response_id.in_(ids))
        return list(session.scalars(stmt).all())
    except SQLAlchemyError as e:
        raise RepositoryError("Fetch failed: database error") from e


def aggregate_metrics(
    session: Session,
    *,
    start_time: datetime,
    end_time: datetime,
    application_id: Optional[str] = None,
    prompt_name: Optional[str] = None,
    prompt_version: Optional[str] = None,
    model_name: Optional[str] = None,
    model_version: Optional[str] = None,
) -> dict[str, Any]:
    """
    Aggregate basic metrics: avg latency, p95 latency, total cost.

    Computes over llm_responses joined to llm_requests, filtered by
    request.created_at. Null latency values are excluded from avg and p95.
    Null cost values are treated as 0 for total_cost_usd.

    Args:
        session: SQLAlchemy session.
        start_time: Inclusive start of time range (timezone-aware).
        end_time: Inclusive end of time range (timezone-aware).
        application_id: Optional filter by application.
        prompt_name: Optional filter by prompt name.
        prompt_version: Optional filter by prompt version.
        model_name: Optional filter by model name.
        model_version: Optional filter by model version.

    Returns:
        Dict with keys: avg_latency_ms, p95_latency_ms, total_cost_usd.
        Values are None when no rows match or no non-null values for that metric.

    Raises:
        RepositoryError: If the query fails.
    """
    try:
        stmt = (
            select(
                func.avg(LLMResponse.latency_ms).label("avg_latency_ms"),
                func.percentile_cont(0.95)
                .within_group(LLMResponse.latency_ms)
                .label("p95_latency_ms"),
                func.coalesce(func.sum(LLMResponse.cost_usd), 0).label("total_cost_usd"),
            )
            .select_from(LLMResponse)
            .join(LLMRequest, LLMResponse.request_id == LLMRequest.id)
            .where(LLMRequest.created_at >= start_time)
            .where(LLMRequest.created_at <= end_time)
        )
        if application_id is not None:
            stmt = stmt.where(LLMRequest.application_id == application_id)
        if prompt_name is not None:
            stmt = stmt.where(LLMRequest.prompt_name == prompt_name)
        if prompt_version is not None:
            stmt = stmt.where(LLMRequest.prompt_version == prompt_version)
        if model_name is not None:
            stmt = stmt.where(LLMRequest.model_name == model_name)
        if model_version is not None:
            stmt = stmt.where(LLMRequest.model_version == model_version)

        row = session.execute(stmt).one()

        return {
            "avg_latency_ms": row.avg_latency_ms,
            "p95_latency_ms": row.p95_latency_ms,
            "total_cost_usd": row.total_cost_usd if row.total_cost_usd is not None else Decimal("0"),
        }
    except SQLAlchemyError as e:
        raise RepositoryError("Aggregate failed: database error") from e
