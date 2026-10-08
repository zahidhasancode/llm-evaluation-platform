"""POST /logs and GET /metrics through FastAPI's TestClient (SQLite backend)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import api.metrics
from storage.models import LLMRequest, LLMResponse
from storage.repository import RepositoryError, insert_evaluation_results


def log_body(**overrides) -> dict:
    body = {
        "prompt_name": "summarization",
        "prompt_version": "v2",
        "model_name": "gpt-4",
        "model_version": "2024-01",
        "application_id": "docs-app",
        "input_text": "Summarize the following...",
        "response": {
            "status": "success",
            "output_text": "The main points are...",
            "input_token_count": 50,
            "output_token_count": 20,
            "latency_ms": 1200,
            "cost_usd": 0.001,
        },
    }
    response_overrides = overrides.pop("response", {})
    body.update(overrides)
    body["response"].update(response_overrides)
    return body


def window() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "start_time": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# --- POST /logs --------------------------------------------------------------


def test_post_log_persists_request_and_response(
    client: TestClient, session_factory: sessionmaker
) -> None:
    res = client.post("/logs", json=log_body(metadata={"user_tier": "free"}))

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "created"

    with session_factory() as s:
        req = s.get(LLMRequest, uuid.UUID(data["request_id"]))
        resp = s.get(LLMResponse, uuid.UUID(data["response_id"]))
        assert req.prompt_version == "v2"
        assert req.metadata_ == {"user_tier": "free"}
        assert resp.request_id == req.id
        assert resp.latency_ms == 1200
        assert str(resp.cost_usd) == "0.00100000"


def test_post_log_accepts_failed_call_without_output(
    client: TestClient, session_factory: sessionmaker
) -> None:
    body = log_body(response={"status": "timeout", "output_text": None, "latency_ms": None,
                              "cost_usd": None, "error_type": "timeout", "error_code": "504"})
    assert client.post("/logs", json=body).status_code == 200
    with session_factory() as s:
        resp = s.scalars(select(LLMResponse)).one()
        assert (resp.status, resp.error_code, resp.output_text) == ("timeout", "504", None)


@pytest.mark.parametrize(
    "body",
    [
        log_body(response={"status": "ok"}),  # not an allowed status
        log_body(response={"latency_ms": -1}),
        log_body(response={"cost_usd": -0.5}),
        log_body(prompt_name=""),
        {k: v for k, v in log_body().items() if k != "model_name"},
    ],
)
def test_post_log_rejects_invalid_body(
    client: TestClient, session_factory: sessionmaker, body: dict
) -> None:
    res = client.post("/logs", json=body)
    assert res.status_code == 422
    with session_factory() as s:
        assert s.scalars(select(LLMRequest)).first() is None


# --- GET /metrics ------------------------------------------------------------


def test_metrics_aggregate_logged_calls(client: TestClient) -> None:
    for latency in (100, 200, 300, 400):
        client.post("/logs", json=log_body(response={"latency_ms": latency, "cost_usd": 0.25}))
    client.post("/logs", json=log_body(response={"status": "error", "latency_ms": None,
                                                 "cost_usd": None}))

    res = client.get("/metrics", params=window())

    assert res.status_code == 200
    assert res.json() == {
        "request_count": 5,
        "error_count": 1,
        "average_latency_ms": 250.0,
        "p95_latency_ms": pytest.approx(385.0),
        "p99_latency_ms": pytest.approx(397.0),
        "total_cost_usd": "1.00000000",
        "average_cost_usd": 0.25,
        "average_evaluation_score": None,
    }


def test_metrics_filters_by_version(client: TestClient) -> None:
    client.post("/logs", json=log_body(prompt_version="v1", response={"latency_ms": 900}))
    client.post("/logs", json=log_body(prompt_version="v2", response={"latency_ms": 300}))
    client.post("/logs", json=log_body(model_name="other", response={"latency_ms": 50}))

    v1 = client.get("/metrics", params={**window(), "prompt_version": "v1"}).json()
    assert (v1["request_count"], v1["average_latency_ms"]) == (1, 900)

    gpt4 = client.get("/metrics", params={**window(), "model_name": "gpt-4"}).json()
    assert gpt4["request_count"] == 2


def test_metrics_on_empty_range(client: TestClient) -> None:
    res = client.get(
        "/metrics", params={"start_time": "2020-01-01T00:00:00Z", "end_time": "2020-01-02T00:00:00Z"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["request_count"] == 0
    assert body["average_latency_ms"] is None


def test_metrics_rejects_bad_datetime(client: TestClient) -> None:
    res = client.get("/metrics", params={"start_time": "yesterday", "end_time": "2026-01-01T00:00:00Z"})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "invalid_datetime"


def test_metrics_rejects_reversed_range(client: TestClient) -> None:
    res = client.get(
        "/metrics", params={"start_time": "2026-02-01T00:00:00Z", "end_time": "2026-01-01T00:00:00Z"}
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "invalid_range"


def test_metrics_requires_time_range(client: TestClient) -> None:
    assert client.get("/metrics").status_code == 422


def test_metrics_reports_database_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args, **_kwargs):
        raise RepositoryError("Fetch failed: database error")

    monkeypatch.setattr(api.metrics, "fetch_requests_and_responses_by_time_range", broken)
    res = client.get("/metrics", params=window())
    assert res.status_code == 500
    assert res.json()["detail"]["error"] == "database_error"



def test_metrics_include_stored_evaluation_scores(
    client: TestClient, session_factory: sessionmaker
) -> None:
    first = client.post("/logs", json=log_body()).json()
    second = client.post("/logs", json=log_body()).json()
    other = client.post("/logs", json=log_body(prompt_version="v9")).json()
    run_id = str(uuid.uuid4())
    with session_factory() as s:
        insert_evaluation_results(
            s,
            results=[
                {"response_id": first["response_id"], "evaluation_run_id": run_id,
                 "criterion_name": "llm_judge", "score": 4.0},
                {"response_id": second["response_id"], "evaluation_run_id": run_id,
                 "criterion_name": "llm_judge", "score": 3.0},
                {"response_id": second["response_id"], "evaluation_run_id": run_id,
                 "criterion_name": "empty_response", "outcome": "pass"},
                {"response_id": other["response_id"], "evaluation_run_id": run_id,
                 "criterion_name": "llm_judge", "score": 0.0},
            ],
        )
        s.commit()

    body = client.get("/metrics", params={**window(), "prompt_version": "v2"}).json()
    assert body["request_count"] == 2
    assert body["average_evaluation_score"] == pytest.approx(3.5)
