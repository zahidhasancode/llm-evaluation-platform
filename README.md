# LLM Evaluation & Monitoring Platform

Internal platform for storing LLM request data, running evaluations, and aggregating metrics. Enables teams to compare prompt and model versions, attribute cost and latency, and trace production incidents.

---

## 1. Overview

The platform is an observability and evaluation layer for LLM-powered systems. It sits downstream of inference: applications push request metadata and outputs; the platform stores, evaluates, and aggregates. It does not run inference or call LLM APIs for production traffic.

**Target users:** ML engineers, platform engineers, and product teams shipping LLM-powered features.

**Scope:** Internal applications and services. v1 assumes a trusted network; no authentication or multi-tenancy.

---

## 2. Problem the System Solves

Teams deploying LLMs in production face several gaps:

- **Output quality is hard to measure.** Free-form text resists traditional metrics. Production systems lack structured feedback.
- **Regressions ship silently.** Prompt or model changes can degrade outputs without detection. A/B tests rarely cover full traffic.
- **Versioning is not traceable.** Prompts and models evolve; few teams maintain a record of what ran when and how it performed.
- **Latency and cost are unpredictable.** Token usage varies; operational tooling does not expose LLM-specific metrics. Cost attribution and forecasting are difficult.
- **Traditional ML tooling does not fit.** Conventional evaluation assumes fixed schemas and batch workflows. LLM workloads are dynamic and non-deterministic.

The platform addresses these by centralizing logging, evaluation, and aggregation in one system with version-aware queries.

---

## 3. Core Capabilities

| Capability | Description |
|------------|-------------|
| **Request/response logging** | Ingest request metadata (prompt version, model version, application) and response data (output, tokens, latency, cost, status). |
| **Version tracking** | Associate each request with prompt version and model version. Support lineage lookup (request ID → versions). |
| **Metrics aggregation** | Compute average and p95/p99 latency, total and average cost, request count, error count by time range, application, prompt, and model. |
| **Rule-based evaluation** | Evaluate outputs with configurable rules: length validation, empty response detection, JSON schema validity. |
| **LLM-as-judge evaluation** | Score relevance, completeness, and format adherence via a separate judge model. Structured rubric, deterministic settings. |
| **Comparison** | Compare two prompt or model versions. Compute deltas for latency, cost, evaluation score. Decision-oriented summaries. |

---

## 4. High-Level Architecture

```
Applications                    Platform
     │                              │
     ├── POST /logs ──────────────► API ──► Storage (PostgreSQL)
     │                                    │
     └── GET /metrics ◄──────────── API ◄─┘
                                         ▲
     Evaluation workers ─────────────────┘
     (queue → load run → evaluate → write results)
```

- **API:** Stateless FastAPI service. Ingests logs, serves metrics. No UI in v1.
- **Storage:** PostgreSQL. Tables: `llm_requests`, `llm_responses`, `llm_evaluations`.
- **Workers:** Consume evaluation runs from a job queue, execute evaluators, persist results. Scale by adding workers.
- **Aggregation:** On-demand computation over stored requests. Optional rollups for large time windows.

See `docs/SYSTEM_DESIGN.md` for details.

---

## 5. Example Usage

### Ingest a request and response

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

Response: `{"request_id": "...", "response_id": "...", "status": "created"}`

### Query aggregated metrics

```bash
curl "http://localhost:8000/metrics?start_time=2024-01-01T00:00:00Z&end_time=2024-01-31T23:59:59Z&model_name=gpt-4"
```

Response: `{"request_count": 1000, "error_count": 5, "average_latency_ms": 850, "p95_latency_ms": 2100, "total_cost_usd": "12.50", ...}`

### Programmatic comparison

```python
from core.metrics import compute_metrics, records_from_request_response_pairs
from core.comparison import compare_prompt_versions

# Fetch data for two prompt versions, then:
baseline_metrics = compute_metrics(records_v1)
candidate_metrics = compute_metrics(records_v2)
result = compare_prompt_versions(baseline_metrics, candidate_metrics)
# result.summary: ["Latency: candidate 200ms faster (improvement)", ...]
```

---

## 6. Deployment Overview

- **Requirements:** Python 3.10+, PostgreSQL 14+, job queue (for workers).
- **Environment:** `DATABASE_URL` required. `QUEUE_URL` if workers are used.
- **API:** `uvicorn main:app --workers 4`. Stateless; scale horizontally.
- **Workers:** Run one or more worker processes. Scale with queue depth.
- **Database:** Apply schema from `docs/DATA_MODEL.md`. Configure retention.

See `docs/DEPLOYMENT.md` for full instructions.

---

## 7. Limitations

- **No UI.** All interaction is programmatic. No dashboards or visualizations in v1.
- **No auth or RBAC.** Assumes trusted internal network.
- **No real-time alerting.** No PagerDuty, Slack, or push notifications. Users poll for results.
- **No built-in inference.** The platform stores and evaluates outputs. Applications supply them.
- **No automated regression detection.** Users compare results programmatically.
- **No multi-turn support.** Request/response pairs are single-turn.
- **No SLAs.** No contractual guarantees for availability or latency in v1.
- **No automatic log ingestion.** Applications must push data. No pull from production systems.

---

## 8. Future Work

Potential directions (not committed):

- Web UI for metrics and comparison
- Real-time or scheduled alerting
- Authentication and per-team access control
- Automated regression detection and reporting
- Multi-turn conversation support
- Built-in safety checks (toxicity, PII)
- Export to BI or analytics tools
- Precomputed rollups for large-range queries
- Formal SLAs and SLOs

Prioritization depends on adoption and feedback. See `docs/SUCCESS_METRICS.md` for how we measure platform value.

---

## Documentation

| Document | Purpose |
|----------|---------|
| `docs/PROBLEM_STATEMENT.md` | Problem definition |
| `docs/REQUIREMENTS.md` | Functional and non-functional requirements |
| `docs/SYSTEM_DESIGN.md` | Architecture and data flow |
| `docs/DATA_MODEL.md` | PostgreSQL schema (DDL) |
| `docs/FAILURE_MODES.md` | Production failure scenarios and mitigations |
| `docs/TESTING_STRATEGY.md` | Unit and integration testing approach |
| `docs/DEPLOYMENT.md` | Deployment instructions |
| `docs/SUCCESS_METRICS.md` | How we measure platform success |
