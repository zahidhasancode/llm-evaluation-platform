# LLM Evaluation Platform

A personal prototype of a backend for logging LLM calls, scoring their outputs and comparing prompt or model versions. Built with FastAPI, SQLAlchemy and PostgreSQL.

[![CI](https://github.com/zahidhasancode/llm-evaluation-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/zahidhasancode/llm-evaluation-platform/actions/workflows/ci.yml)

---

## Status

This is a prototype. It has not been deployed or used with real traffic. The `docs/` folder describes a larger system than the code in `src/`.

**Implemented and tested**

| Part | Where | Notes |
|------|-------|-------|
| `POST /logs` | `src/api/logs.py` | Stores one request and its response (status, output, tokens, latency, cost, error info). |
| `GET /metrics` | `src/api/metrics.py` | Aggregates logged calls in a time range. Optional filters: model name/version, prompt name/version. |
| Storage | `src/storage/models.py`, `src/storage/repository.py` | Tables `llm_requests`, `llm_responses`, `llm_evaluations`. Insert and query functions. |
| Rule-based evaluators | `src/evaluation/rules.py` | Length bounds, empty response, valid JSON, JSON Schema. |
| LLM-as-judge evaluator | `src/evaluation/llm_judge.py` | Rubric prompt (relevance, completeness, format adherence, 0–5), JSON parsing, token and cost tracking. You supply the LLM client. |
| Metric aggregation | `src/core/metrics.py` | Request and error counts, average / p95 / p99 latency, total and average cost, average evaluation score, grouping by dimension. |
| Version comparison | `src/core/comparison.py` | Deltas between two metric summaries plus short "improvement / regression" lines. |

**Designed in `docs/` but not built**

- Evaluation run submission, a job queue and evaluation workers (`src/workers/` is empty).
- Dataset store, version registry, lineage endpoint.
- Precomputed rollups, health and readiness endpoints.
- HTTP endpoints for comparisons or for writing evaluation results. Today both are Python-only.

No LLM provider client is included. The judge has only been run against a fake client in the tests.

---

## What it does

Applications that call an LLM push one record per call to `POST /logs`. Each record carries the prompt name and version, model name and version, application id, input, and the response data.

`GET /metrics` returns counts, latency percentiles, cost and the average evaluation score for a time range, optionally for one prompt or model version.

Evaluators score a single output. Their results can be stored per response and criterion with `insert_evaluation_results()`. `GET /metrics` then averages the stored numeric scores.

`core.comparison` takes two metric summaries (for example prompt v1 and v2) and reports the change in latency, cost and evaluation score.

## How it works

```
client ── POST /logs ───► api/logs.py ────► storage/repository.py ──► PostgreSQL
client ── GET /metrics ─► api/metrics.py ─► storage/repository.py      (llm_requests,
                               │                                        llm_responses,
                               └─► core/metrics.py (aggregation)        llm_evaluations)

Python only:  evaluation/rules.py, evaluation/llm_judge.py  ─► EvaluationResult
              core/comparison.py  (AggregatedMetrics A vs B ─► ComparisonResult)
```

- `src/main.py` builds the FastAPI app and mounts both routers.
- The API opens a SQLAlchemy session per request from `DATABASE_URL`.
- `GET /metrics` loads the matching request/response rows and their evaluations, then aggregates in Python (`core.metrics`). Percentiles use linear interpolation, the same definition as PostgreSQL `percentile_cont`.
- `storage.repository.aggregate_metrics()` computes average and p95 latency and total cost in SQL. It uses `percentile_cont`, so it only works on PostgreSQL. The API does not use it yet.
- Every evaluator returns an `EvaluationResult(score, outcome, details)`. Rule evaluators score 1.0 or 0.0. The judge returns the mean of its criterion scores (0–5) and keeps the per-criterion explanations in `details`.

---

## Quick start

I ran these on macOS with Python 3.11.9 and PostgreSQL 16 (my local server used a different port; adjust the URL to yours).

### Tests and lint (no database needed)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
ruff check .
pytest
```

### Run the API against PostgreSQL

```bash
createdb -E UTF8 -T template0 llm_eval
psql -d llm_eval -f docs/DATA_MODEL.md        # the file is plain SQL (the schema)
export DATABASE_URL=postgresql://postgres@localhost:5432/llm_eval
uvicorn main:app --app-dir src --port 8000
```

Create the database as UTF-8. With psycopg 3, a `SQL_ASCII` database makes SQLAlchemy fail on connect.

Interactive API docs are then at `http://localhost:8000/docs`.

---

## Example output

From my local run on 2026-10-08. I logged four calls to an empty database: latencies 1200, 800 and 950 ms, plus one timeout with no latency or cost.

```bash
curl -X POST http://localhost:8000/logs \
  -H "Content-Type: application/json" \
  -d '{
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
      "cost_usd": 0.001
    }
  }'
```

```json
{"request_id":"cdfe5416-7560-468b-b0c0-14c1b19dab3c","response_id":"3f2c3ad1-73cd-47cd-850a-a57e2a155125","status":"created"}
```

```bash
curl "http://localhost:8000/metrics?start_time=2026-10-01T00:00:00Z&end_time=2026-10-31T23:59:59Z&prompt_version=v2"
```

```json
{"request_count":4,"error_count":1,"average_latency_ms":983.3333333333334,"p95_latency_ms":1175.0,"p99_latency_ms":1195.0,"total_cost_usd":"0.00260000","average_cost_usd":0.0008666666666666666,"average_evaluation_score":null}
```

`average_evaluation_score` is `null` because no evaluations were stored for these calls.

Evaluators and comparison from Python (`PYTHONPATH=src`). The metric values passed to the comparison are made-up inputs; the printed results are the real output:

```python
from decimal import Decimal
from evaluation.base import EvaluationInput
from evaluation.rules import JsonSchemaEvaluator
from core.metrics import AggregatedMetrics
from core.comparison import compare_prompt_versions

inp = EvaluationInput(input_text="Reply in JSON", output_text='{"answer": 42}')
schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
JsonSchemaEvaluator(schema).evaluate(inp)
# EvaluationResult(score=0.0, outcome='fail', details={'valid': False,
#   'reason': "42 is not of type 'string' ...", 'path': ['answer'], 'schema_validated': True})

v1 = AggregatedMetrics(request_count=200, average_latency_ms=1150.0,
                       total_cost_usd=Decimal("0.42"), average_evaluation_score=3.9)
v2 = AggregatedMetrics(request_count=200, average_latency_ms=980.0,
                       total_cost_usd=Decimal("0.51"), average_evaluation_score=4.2)
compare_prompt_versions(v1, v2).summary
# Latency: candidate 170ms faster (improvement)
# Total cost: candidate $0.090000 more expensive (regression)
# Eval score: candidate 0.30 higher (improvement)
```

---

## Tests and CI

`pytest` runs 113 tests in `tests/`, with no network, database server or API key:

- `test_rules.py`: length boundaries, empty / `None` output, JSON parse errors, JSON Schema pass and fail.
- `test_llm_judge.py`: the judge with a fake client: averaging, cost estimate, fenced JSON, N/A format score, parse and schema failures, client exceptions.
- `test_metrics.py`, `test_comparison.py`: percentiles, cost, error counts, score averaging, grouping, deltas and summary lines.
- `test_repository.py`: inserts, constraints and time-range / filter queries on in-memory SQLite.
- `test_api.py`: `POST /logs` and `GET /metrics` through FastAPI's `TestClient`, with the database dependency pointed at SQLite.

`tests/test_postgres.py` checks that the SQL aggregate matches the Python one. It is skipped unless you point it at an empty, disposable PostgreSQL database:

```bash
TEST_POSTGRES_URL=postgresql://postgres@localhost:5432/llm_eval_test pytest -m postgres
```

GitHub Actions (`.github/workflows/ci.yml`) runs `ruff check .` and `pytest` on Python 3.11 for every push and pull request.

---

## Limitations

- No authentication, no UI, no rate limits. Do not expose it to a network.
- No migrations. The schema comes from `docs/DATA_MODEL.md` (or `Base.metadata.create_all`).
- `GET /metrics` loads every matching row into memory, so large time windows will be slow.
- Evaluation results can only be written from Python. There is no endpoint for them.
- `POST /logs` has no idempotency key. Sending the same call twice stores it twice.
- Request validation errors return HTTP 422 (FastAPI's default), although the OpenAPI spec also lists 400.
- When the judge call fails or its reply cannot be parsed, the result is `score=0.0, outcome="fail"`. If you store that as a score, it lowers the average quality score.
- Without `DATABASE_URL`, the API starts but every request returns 500.
- In SQLite (tests only) timestamps are stored without a time zone.
- Several files in `docs/` were written as a design for a bigger system. They describe components that do not exist yet, and `API_CONTRACTS.md`, `EVALUATION_STRATEGY.md` and `EXECUTION_PLAN.md` are empty stubs.

## Planned

From the design in `docs/`, in rough order:

- Endpoints to store evaluation results and to compare two versions.
- Evaluation runs: submit a dataset and criteria, execute in background workers, poll for results.
- Versioned datasets, a prompt/model version registry and a lineage lookup endpoint.
- Health and readiness endpoints, SQL-side aggregation and rollups for large windows.
- More evaluators (exact match, regex, similarity) and a real LLM client for the judge.

---

## Tech used

Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2.1, PostgreSQL (psycopg 3), jsonschema, pytest, ruff, GitHub Actions.

## Documentation

| Document | Content |
|----------|---------|
| `docs/PROBLEM_STATEMENT.md` | Problem definition |
| `docs/REQUIREMENTS.md` | Functional and non-functional requirements (design targets, not measured) |
| `docs/SYSTEM_DESIGN.md` | Target architecture and data flow |
| `docs/DATA_MODEL.md` | PostgreSQL schema (plain SQL) |
| `docs/FAILURE_MODES.md` | Failure scenarios and mitigations |
| `docs/TESTING_STRATEGY.md` | Testing approach |
| `docs/DEPLOYMENT.md` | Deployment notes for the target design |
| `docs/LIMITATIONS.md`, `docs/FUTURE_WORK.md` | Known gaps and ideas |
| `docs/SUCCESS_METRICS.md` | How success would be measured |
