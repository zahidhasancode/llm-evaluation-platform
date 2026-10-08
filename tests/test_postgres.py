"""
Optional checks against a real PostgreSQL database.

Skipped unless TEST_POSTGRES_URL points at an empty, disposable database, e.g.
    TEST_POSTGRES_URL=postgresql://postgres@localhost:5432/llm_eval_test pytest -m postgres
The tables are created at the start and dropped at the end.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.metrics import compute_metrics, records_from_request_response_pairs
from storage.models import Base
from storage.repository import (
    aggregate_metrics,
    fetch_requests_and_responses_by_time_range,
    insert_llm_request,
    insert_llm_response,
)

URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not URL, reason="TEST_POSTGRES_URL is not set"),
]


@pytest.fixture()
def pg_session() -> Iterator[Session]:
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as s:
            yield s
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_sql_aggregate_matches_python_aggregation(pg_session: Session) -> None:
    for latency, cost in [(100, "0.01"), (200, None), (300, "0.02"), (1000, "0.03")]:
        req = insert_llm_request(
            pg_session, prompt_name="p", prompt_version="v1", model_name="m",
            model_version="1", application_id="app", input_text="x",
        )
        insert_llm_response(
            pg_session, request_id=str(req.id), status="success", latency_ms=latency,
            cost_usd=Decimal(cost) if cost else None,
        )
    pg_session.commit()

    now = datetime.now(timezone.utc)
    window = {"start_time": now - timedelta(hours=1), "end_time": now + timedelta(hours=1)}

    sql = aggregate_metrics(pg_session, **window)
    py = compute_metrics(
        records_from_request_response_pairs(
            fetch_requests_and_responses_by_time_range(pg_session, **window)
        )
    )

    assert float(sql["avg_latency_ms"]) == pytest.approx(py.average_latency_ms) == 400
    # percentile_cont and core.metrics both interpolate linearly.
    assert sql["p95_latency_ms"] == pytest.approx(py.p95_latency_ms) == pytest.approx(895.0)
    assert sql["total_cost_usd"] == py.total_cost_usd == Decimal("0.06")
