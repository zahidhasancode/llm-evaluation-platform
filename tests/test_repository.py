"""storage.repository against an in-memory SQLite database."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import LLMEvaluation, LLMRequest, LLMResponse
from storage.repository import (
    RepositoryError,
    fetch_evaluations_for_responses,
    fetch_requests_and_responses_by_time_range,
    insert_evaluation_results,
    insert_llm_request,
    insert_llm_response,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def add_pair(
    session: Session,
    *,
    created_at: datetime = T0,
    prompt_version: str = "v1",
    model_name: str = "model-a",
    application_id: str = "app",
    status: str = "success",
    latency_ms: int | None = 100,
) -> tuple[LLMRequest, LLMResponse]:
    req = insert_llm_request(
        session,
        prompt_name="summary",
        prompt_version=prompt_version,
        model_name=model_name,
        model_version="1",
        application_id=application_id,
        input_text="Summarise this.",
        metadata_={"source": "test"},
    )
    req.created_at = created_at
    resp = insert_llm_response(
        session,
        request_id=str(req.id),
        output_text="Summary.",
        input_token_count=10,
        output_token_count=3,
        latency_ms=latency_ms,
        cost_usd=Decimal("0.00012345"),
        status=status,
    )
    session.commit()
    return req, resp


def test_insert_request_and_response_round_trip(session: Session) -> None:
    req, resp = add_pair(session)
    session.expire_all()

    stored_req = session.get(LLMRequest, req.id)
    stored_resp = session.get(LLMResponse, resp.id)
    assert stored_req.metadata_ == {"source": "test"}
    assert stored_req.response.id == resp.id
    assert stored_resp.request_id == req.id
    assert stored_resp.cost_usd == Decimal("0.00012345")
    assert stored_resp.status == "success"


def test_status_check_constraint_is_enforced(session: Session) -> None:
    req = insert_llm_request(
        session, prompt_name="p", prompt_version="v", model_name="m", model_version="1",
        application_id="a", input_text="x",
    )
    with pytest.raises(RepositoryError, match="constraint violation"):
        insert_llm_response(session, request_id=req.id, status="ok")


def test_second_response_for_same_request_is_rejected(session: Session) -> None:
    req, _ = add_pair(session)
    with pytest.raises(RepositoryError, match="constraint violation"):
        insert_llm_response(session, request_id=req.id, status="success")


def test_response_for_unknown_request_is_rejected(session: Session) -> None:
    with pytest.raises(RepositoryError, match="constraint violation"):
        insert_llm_response(session, request_id=uuid.uuid4(), status="success")


def test_malformed_request_id_is_rejected(session: Session) -> None:
    with pytest.raises(RepositoryError, match="Invalid UUID"):
        insert_llm_response(session, request_id="not-a-uuid", status="success")


def test_fetch_is_inclusive_ordered_and_bounded(session: Session) -> None:
    early, _ = add_pair(session, created_at=T0)
    late, _ = add_pair(session, created_at=T0 + timedelta(hours=2))
    add_pair(session, created_at=T0 - timedelta(seconds=1))  # before range
    add_pair(session, created_at=T0 + timedelta(hours=2, seconds=1))  # after range

    pairs = fetch_requests_and_responses_by_time_range(
        session, start_time=T0, end_time=T0 + timedelta(hours=2)
    )
    assert [r.id for r, _ in pairs] == [early.id, late.id]


def test_fetch_skips_requests_without_response(session: Session) -> None:
    add_pair(session)
    orphan = insert_llm_request(
        session, prompt_name="p", prompt_version="v", model_name="m", model_version="1",
        application_id="a", input_text="x",
    )
    orphan.created_at = T0
    session.commit()

    pairs = fetch_requests_and_responses_by_time_range(
        session, start_time=T0 - timedelta(days=1), end_time=T0 + timedelta(days=1)
    )
    assert len(pairs) == 1
    assert orphan.id not in {r.id for r, _ in pairs}


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({}, 4),
        ({"prompt_version": "v2"}, 1),
        ({"model_name": "model-b"}, 1),
        ({"application_id": "other-app"}, 1),
        ({"prompt_version": "v1"}, 2),
        ({"prompt_version": "v1", "model_name": "model-a"}, 1),
        ({"model_version": "does-not-exist"}, 0),
    ],
)
def test_fetch_filters(session: Session, filters: dict, expected: int) -> None:
    add_pair(session)
    add_pair(session, prompt_version="v2")
    add_pair(session, model_name="model-b")
    add_pair(session, application_id="other-app", prompt_version="v3")

    pairs = fetch_requests_and_responses_by_time_range(
        session, start_time=T0, end_time=T0, **filters
    )
    assert len(pairs) == expected


def test_insert_evaluation_results(session: Session) -> None:
    _, resp = add_pair(session)
    run_id = uuid.uuid4()
    rows = insert_evaluation_results(
        session,
        results=[
            {"response_id": str(resp.id), "evaluation_run_id": str(run_id),
             "criterion_name": "length", "score": 1.0, "outcome": "pass"},
            {"response_id": resp.id, "evaluation_run_id": run_id,
             "criterion_name": "llm_judge", "criterion_version": "rubric-v1", "score": 3.5,
             "result_metadata": {"input_tokens": 120}},
        ],
    )
    session.commit()
    assert len(rows) == 2

    stored = session.scalars(select(LLMEvaluation).order_by(LLMEvaluation.criterion_name)).all()
    assert [e.criterion_name for e in stored] == ["length", "llm_judge"]
    assert stored[1].score == Decimal("3.5")
    assert stored[1].result_metadata == {"input_tokens": 120}
    assert all(e.evaluation_run_id == run_id for e in stored)


def test_evaluation_needs_score_or_outcome(session: Session) -> None:
    _, resp = add_pair(session)
    with pytest.raises(RepositoryError, match="at least one of 'score' or 'outcome'"):
        insert_evaluation_results(
            session,
            results=[{"response_id": resp.id, "evaluation_run_id": uuid.uuid4(),
                      "criterion_name": "x"}],
        )


def test_evaluation_for_unknown_response_is_rejected(session: Session) -> None:
    with pytest.raises(RepositoryError, match="constraint violation"):
        insert_evaluation_results(
            session,
            results=[{"response_id": uuid.uuid4(), "evaluation_run_id": uuid.uuid4(),
                      "criterion_name": "x", "score": 1}],
        )


def test_fetch_evaluations_for_responses(session: Session) -> None:
    _, wanted = add_pair(session)
    _, other = add_pair(session)
    run_id = uuid.uuid4()
    insert_evaluation_results(
        session,
        results=[
            {"response_id": wanted.id, "evaluation_run_id": run_id, "criterion_name": "a", "score": 1},
            {"response_id": wanted.id, "evaluation_run_id": run_id, "criterion_name": "b", "outcome": "fail"},
            {"response_id": other.id, "evaluation_run_id": run_id, "criterion_name": "a", "score": 0},
        ],
    )
    session.commit()

    rows = fetch_evaluations_for_responses(session, response_ids=[str(wanted.id)])
    assert sorted(r.criterion_name for r in rows) == ["a", "b"]
    assert fetch_evaluations_for_responses(session, response_ids=[]) == []
