"""
POST /logs endpoint for LLM Evaluation & Monitoring Platform.
Accepts LLM request and response data, validates, and persists via repository.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Generator, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from storage.repository import (
    RepositoryError,
    insert_llm_request,
    insert_llm_response,
)

router = APIRouter(prefix="/logs", tags=["logs"])

# -----------------------------------------------------------------------------
# Session dependency
# -----------------------------------------------------------------------------
# DATABASE_URL must be set. Engine created on first use.
_session_factory: sessionmaker | None = None


def _get_session_factory() -> sessionmaker:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    engine = create_engine(url)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session. Caller must configure DATABASE_URL."""
    global _session_factory
    if _session_factory is None:
        _session_factory = _get_session_factory()
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------

ResponseStatus = Literal["success", "partial_failure", "timeout", "error"]


class ResponseData(BaseModel):
    """Response data: output, tokens, latency, cost, and error info."""

    status: ResponseStatus = Field(
        ...,
        description="One of: success, partial_failure, timeout, error",
    )
    output_text: str | None = None
    input_token_count: int | None = Field(None, ge=0)
    output_token_count: int | None = Field(None, ge=0)
    latency_ms: int | None = Field(None, ge=0)
    cost_usd: Decimal | float | None = Field(None, ge=0)
    error_type: str | None = Field(None, max_length=128)
    error_code: str | None = Field(None, max_length=64)
    metadata: dict[str, Any] | None = None


class LogEntryRequest(BaseModel):
    """Single log entry: request metadata plus response data."""

    prompt_name: str = Field(..., min_length=1, max_length=255)
    prompt_version: str = Field(..., min_length=1, max_length=128)
    model_name: str = Field(..., min_length=1, max_length=255)
    model_version: str = Field(..., min_length=1, max_length=128)
    application_id: str = Field(..., min_length=1, max_length=128)
    input_text: str = Field(...)
    response: ResponseData
    metadata: dict[str, Any] | None = None


class LogCreatedResponse(BaseModel):
    """Response after successful log ingestion."""

    request_id: str
    response_id: str
    status: Literal["created"] = "created"


class ErrorDetail(BaseModel):
    """Error response body."""

    error: str
    detail: str | None = None


# -----------------------------------------------------------------------------
# Endpoint
# -----------------------------------------------------------------------------


@router.post(
    "",
    response_model=LogCreatedResponse,
    responses={
        400: {"model": ErrorDetail, "description": "Validation error"},
        500: {"model": ErrorDetail, "description": "Database error"},
    },
)
def post_logs(
    body: LogEntryRequest,
    db: Session = Depends(get_db),
) -> LogCreatedResponse:
    """
    Ingest a single LLM request and response.

    Persists request metadata (prompt, model, application, input) and response
    data (output, tokens, latency, cost, status). Returns IDs for both records.
    """
    try:
        request = insert_llm_request(
            db,
            prompt_name=body.prompt_name,
            prompt_version=body.prompt_version,
            model_name=body.model_name,
            model_version=body.model_version,
            application_id=body.application_id,
            input_text=body.input_text,
            metadata_=body.metadata,
        )

        cost_usd: Decimal | None = None
        if body.response.cost_usd is not None:
            cost_usd = (
                Decimal(str(body.response.cost_usd))
                if not isinstance(body.response.cost_usd, Decimal)
                else body.response.cost_usd
            )

        response = insert_llm_response(
            db,
            request_id=str(request.id),
            output_text=body.response.output_text,
            input_token_count=body.response.input_token_count,
            output_token_count=body.response.output_token_count,
            latency_ms=body.response.latency_ms,
            cost_usd=cost_usd,
            status=body.response.status,
            error_type=body.response.error_type,
            error_code=body.response.error_code,
            metadata_=body.response.metadata,
        )

        db.commit()
        return LogCreatedResponse(
            request_id=str(request.id),
            response_id=str(response.id),
        )
    except RepositoryError as e:
        db.rollback()
        detail = str(e.__cause__) if e.__cause__ else str(e)
        if "constraint violation" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail={"error": "constraint_violation", "detail": detail},
            ) from e
        raise HTTPException(
            status_code=500,
            detail={"error": "database_error", "detail": detail},
        ) from e
