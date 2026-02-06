"""
SQLAlchemy ORM models for LLM Evaluation & Monitoring Platform.
Maps to PostgreSQL schema: llm_requests, llm_responses, llm_evaluations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import BigInteger, Integer, Numeric, String


class Base(DeclarativeBase):
    pass


class LLMRequest(Base):
    """Request context for LLM invocations. One row per invocation."""

    __tablename__ = "llm_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    prompt_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    application_id: Mapped[str] = mapped_column(String(128), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    response: Mapped[LLMResponse | None] = relationship(
        "LLMResponse",
        back_populates="request",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_llm_requests_created_at", "created_at"),
        Index("idx_llm_requests_application_created_at", "application_id", "created_at"),
        Index(
            "idx_llm_requests_prompt_version_created_at",
            "prompt_name",
            "prompt_version",
            "created_at",
        ),
        Index(
            "idx_llm_requests_model_version_created_at",
            "model_name",
            "model_version",
            "created_at",
        ),
        Index(
            "idx_llm_requests_aggregation",
            "application_id",
            "prompt_name",
            "prompt_version",
            "model_name",
            "model_version",
            "created_at",
        ),
    )


class LLMResponse(Base):
    """Response data for LLM invocations. One-to-one with LLMRequest."""

    __tablename__ = "llm_responses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_requests.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    cost_usd: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    error_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    request: Mapped[LLMRequest] = relationship(
        "LLMRequest",
        back_populates="response",
    )
    evaluations: Mapped[list[LLMEvaluation]] = relationship(
        "LLMEvaluation",
        back_populates="response",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('success', 'partial_failure', 'timeout', 'error')",
            name="chk_status",
        ),
        Index("idx_llm_responses_created_at", "created_at"),
    )


class LLMEvaluation(Base):
    """Per-response evaluation results. One row per (response, criterion)."""

    __tablename__ = "llm_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_responses.id", ondelete="CASCADE"),
        nullable=False,
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    criterion_name: Mapped[str] = mapped_column(String(255), nullable=False)
    criterion_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    score: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    outcome: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    result_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    response: Mapped[LLMResponse] = relationship(
        "LLMResponse",
        back_populates="evaluations",
    )

    __table_args__ = (
        CheckConstraint(
            "score IS NOT NULL OR outcome IS NOT NULL",
            name="chk_eval_result",
        ),
        Index("idx_llm_evaluations_response_id", "response_id"),
        Index("idx_llm_evaluations_run_id", "evaluation_run_id"),
        Index(
            "idx_llm_evaluations_criterion",
            "criterion_name",
            "criterion_version",
        ),
        Index("idx_llm_evaluations_created_at", "created_at"),
    )
