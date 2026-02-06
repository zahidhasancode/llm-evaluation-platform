# Testing Strategy

This document defines the testing approach for the LLM Evaluation & Monitoring Platform. It is intended for engineers implementing and maintaining the platform.

---

## 1. Unit Testing Approach

### Scope

Unit tests target pure functions and isolated components with no external dependencies. They run fast and should constitute the majority of the test suite.

### Principles

- **Test behavior, not implementation.** Assert on inputs and outputs. Avoid coupling tests to internal structure.
- **Use fixtures for shared data.** Define reusable request/response records, evaluation inputs, and metric summaries. Keep tests readable.
- **One logical assertion per test where practical.** A test that fails should point to a single issue. Use parameterized tests for multiple input variants.
- **Mock external dependencies.** Database, LLM APIs, and queues are mocked. The unit under test receives fakes or in-memory implementations.

### What to Test

| Component | Focus |
|-----------|-------|
| **Metrics aggregation** (`core.metrics`) | `compute_metrics` with empty, single-item, and multi-item inputs. Percentile accuracy (p95, p99) for known distributions. `compute_metrics_grouped` with various `group_by` combinations. `records_from_*` converters with valid and edge-case inputs. |
| **Comparison logic** (`core.comparison`) | `compare_metrics`, `compare_prompt_versions`, `compare_model_versions` with baseline better, candidate better, equal, and None/missing values. Summary string content. |
| **Rule-based evaluators** (`evaluation.rules`) | Each evaluator (LengthEvaluator, EmptyResponseEvaluator, JsonSchemaEvaluator) with pass, fail, and edge cases. Null/empty input handling. Invalid JSON, invalid schema. |
| **LLM judge evaluator** (`evaluation.llm_judge`) | Mock the client. Test parse success, parse failure, validation failure, API exception. Verify structured output and cost/token details. Do not call real LLMs. |
| **API validation** | Pydantic models for request/response. Valid and invalid payloads. Boundary values (max length, empty strings, invalid status). |

### Test Data

- Use minimal, representative fixtures. A few request-response records are sufficient for aggregation tests.
- For percentiles, use a small ordered list where the expected p95/p99 can be computed by hand.
- For evaluators, use inputs that clearly pass or fail. Avoid ambiguous cases in unit tests.

---

## 2. Integration Testing Approach

### Scope

Integration tests verify that components work together correctly. They use a real database (or a test database) and exercise the full path from API or repository through storage.

### Principles

- **Use a dedicated test database.** Do not run integration tests against production or shared dev databases. Use PostgreSQL (or SQLite for basic smoke tests if schema allows).
- **Isolate test data.** Each test should create its own data. Use transactions with rollback, or truncate tables between tests. Avoid order-dependent tests.
- **Test critical paths only.** Focus on the main flows: ingest → store → fetch; fetch → aggregate → return. Do not exhaustively cover every parameter combination.
- **Keep tests independent.** No shared mutable state. Tests can run in any order or in parallel (if the test DB supports it).

### What to Test

| Flow | Description |
|------|-------------|
| **Request/response ingestion** | POST /logs with valid payload → verify records in DB. Verify FK constraints (invalid request_id returns 409). |
| **Metrics retrieval** | Insert known data → GET /metrics with filters → assert response matches expected aggregates. |
| **Repository → metrics** | Call `fetch_requests_and_responses_by_time_range` → `records_from_request_response_pairs` → `compute_metrics` → assert correct output. |
| **Evaluation run (when implemented)** | Submit run → worker processes → results stored. Verify run state transitions and result association. |
| **Comparison with real data** | Fetch metrics for two versions → `compare_prompt_versions` → assert deltas and summary. |

### Database Setup

- Use schema migrations or create tables from the DDL before integration tests.
- Optionally use a container (e.g. Docker) for PostgreSQL in CI. For local development, a local Postgres instance or SQLite (if compatible) is acceptable for v1.
- Ensure `DATABASE_URL` or equivalent is set for the test environment. Use a separate URL from development.

---

## 3. Components That Must Be Tested

### High Priority (Required for v1)

| Component | Unit | Integration | Rationale |
|-----------|------|-------------|-----------|
| **Repository** | N/A (thin over ORM) | Yes | Data correctness. FK, constraints, query filters. |
| **Metrics aggregation** | Yes | Yes | Core correctness. Percentiles and aggregates must be accurate. |
| **Comparison logic** | Yes | Optional | Pure logic; unit tests sufficient. Integration adds confidence. |
| **Rule-based evaluators** | Yes | No | Pure logic. No DB. |
| **API: POST /logs** | Yes (validation) | Yes | Entry point for data. Validation and persistence must work. |
| **API: GET /metrics** | Yes (validation) | Yes | Primary read path. Filters and response shape. |
| **LLM judge evaluator** | Yes (mocked client) | No | No real LLM calls in tests. Mock covers success and failure paths. |

### Medium Priority (Recommended for v1)

| Component | Unit | Integration | Rationale |
|-----------|------|-------------|-----------|
| **Records converters** | Yes | Via integration | Simple logic but used in critical path. |
| **comparison_to_dict / metrics_to_dict** | Yes | No | Serialization for API. Edge cases (None, Decimal). |
| **Error handling paths** | Yes | Yes | RepositoryError, validation errors, 4xx/5xx responses. |

### Lower Priority (Post v1 or as needed)

| Component | Notes |
|-----------|-------|
| **Rollup producer** | If implemented, test rollup computation and write path. |
| **Job queue consumer** | Test worker pick-up, idempotency, failure handling. |
| **Session/connection handling** | Test pool exhaustion, timeout behavior if relevant. |

---

## 4. What Does Not Require Testing in v1

- **UI/dashboards.** v1 has no UI. No browser or E2E tests.
- **Authentication/RBAC.** v1 has none. No auth tests.
- **Real LLM API calls.** Never call production LLM APIs from tests. Mock the judge client.
- **Performance/load tests.** v1 does not define SLAs. Load testing can be deferred.
- **Chaos or failure injection.** Documented in FAILURE_MODES; automated chaos testing is out of scope for v1.
- **Upgrade/migration tests.** Schema migrations can be tested manually. Automated upgrade tests are optional.
- **Third-party integrations.** No PagerDuty, Slack, or BI tool integrations in v1. No integration tests for these.
- **CLI.** v1 has no CLI. No CLI tests.

---

## 5. Evaluation Logic Testing

### Rule-Based Evaluators

Rule-based evaluators (length, empty response, JSON schema) are deterministic and pure. Test them like any other pure function.

- **Happy path:** Inputs that clearly pass or fail. Assert on `score`, `outcome`, and `details`.
- **Edge cases:** Empty string, None (if allowed), very long strings, malformed JSON, schema that rejects valid JSON.
- **Boundary conditions:** Length at exactly min, exactly max, one below, one above. JSON at boundary of schema.
- **No external calls.** No network, no file I/O. Tests run offline and fast.

### LLM-as-Judge Evaluator

The judge calls an external LLM. In tests, never call the real API.

- **Mock the client.** Implement a fake `LLMClientProtocol` that returns predefined responses. Test:
  - Valid JSON that passes validation → success result with correct score and details.
  - Valid JSON with out-of-range scores → invalid_schema failure.
  - Invalid JSON → parse_failed failure.
  - Client raises exception → llm_call_failed with score 0, outcome "fail".
- **Prompt stability (optional).** If the prompt is critical, snapshot the prompt string for a fixed input. Assert it does not change unexpectedly. Use with care; prompt iteration may be frequent.
- **Contract tests.** Ensure the mock returns `(str, int, int)`. Ensure the evaluator handles all documented client failures.
- **Manual / staging tests.** For qualitative checks (e.g. "does the judge give sensible scores?"), run against a staging LLM with a small dataset. Not part of CI. Document in runbook.

### Evaluation Result Structure

- **EvaluationResult contract:** At least one of `score` or `outcome` must be set. Test that evaluators never return both None.
- **Details shape:** For rule-based evaluators, assert `details` contains expected keys (e.g. `length`, `reason`). For the judge, assert `criteria`, `input_tokens`, `output_tokens`, `estimated_cost_usd`.

### Evaluation Criteria Validation

If criteria are validated at submission time, test valid and invalid criteria. Invalid criteria should produce a clear error before any evaluation runs.

---

## 6. Test Organization

### Layout

```
tests/
  unit/
    test_metrics.py
    test_comparison.py
    test_rules.py
    test_llm_judge.py
    test_api_validation.py
  integration/
    test_repository.py
    test_logs_api.py
    test_metrics_api.py
    conftest.py       # DB session, fixtures
  fixtures/
    requests.py       # Sample request/response data
```

### Running Tests

- **Unit tests:** `pytest tests/unit -v`. No database required. Should complete in seconds.
- **Integration tests:** `pytest tests/integration -v`. Requires `DATABASE_URL` or test DB. Mark with `@pytest.mark.integration` if you want to skip in quick runs.
- **CI:** Run unit tests on every push. Run integration tests on main or before release. Use a CI-provided Postgres service or container.

### Coverage

- Aim for high coverage on `core.metrics`, `core.comparison`, and `evaluation.rules`. These are pure logic and easy to cover.
- Repository and API: focus on happy path and critical error paths. 100% coverage is not required for v1.
- Exclude `if __name__ == "__main__"` and similar blocks from coverage if present.
