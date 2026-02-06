# Limitations

Honest constraints of the current system. This document is for engineers evaluating or operating the platform.

---

## What Is Not Built

- **Evaluation run orchestration.** Submission, queue, and workers for evaluation runs are designed but not implemented. Evaluation logic (rule-based, LLM judge) exists; the pipeline to run it at scale does not.
- **Dataset store.** No API or storage for versioned evaluation datasets. Users cannot create or reference datasets via the platform.
- **Version registry.** Prompt and model versions are passed inline with requests. There is no separate registry or validation that versions exist before ingestion.
- **Lineage API.** The repository supports lineage lookup; there is no dedicated GET endpoint for it. Users must query the database or add one.
- **Rollup producer.** Metrics are computed on-demand. No precomputed rollups for large time windows. Large queries may be slow.
- **Health endpoints.** Liveness and readiness are documented but not implemented. Add them for orchestration.

---

## Intentionally Simplified

### No User Interface

All interaction is programmatic. No dashboards, charts, or web UI. Users call APIs directly or build their own tooling. This reduces scope and maintenance; it also means non-engineers cannot use the platform without custom clients.

### No Authentication or Authorization

The system assumes a trusted internal network. Any client that can reach the API can read and write data. No per-team isolation, no audit trail of who did what. Suitable for single-tenant internal use only.

### No Real-Time Alerting

No PagerDuty, Slack, or push notifications. Users poll for evaluation run status and query metrics. They must build their own alerting if they want automated detection of regressions or anomalies.

### No Built-In Inference

The platform stores and evaluates outputs. It does not call LLM APIs for production traffic. Applications must instrument their inference pipelines and push data. The LLM-as-judge evaluator does call an LLM, but only for evaluation, not for the outputs being evaluated.

### No Automated Regression Detection

The platform computes metrics and supports comparison. It does not automatically compare runs, flag regressions, or suggest rollbacks. Users run comparisons programmatically and interpret results.

### Single-Turn Only

Request/response pairs are atomic. No modeling of conversation history, turns, or multi-turn context. Multi-turn applications must flatten or approximate.

### Push-Only Ingestion

Applications push logs. The platform does not pull from production systems, log aggregators, or data lakes. Integration effort is on the application side.

---

## Technical Constraints

### Metrics Query Performance

Aggregation over large time ranges (e.g. one month, all applications) scans the request store. Without rollups, latency can exceed 10 seconds. Indexes help but do not eliminate the cost for ad hoc queries.

### Evaluation Scale

Evaluation logic can process large datasets, but there is no worker pipeline to orchestrate it. Running evaluations at scale (e.g. 100k items) requires custom scripting until workers are implemented.

### No Request-Level Sampling Configuration

The platform accepts whatever is pushed. It does not support server-side sampling (e.g. "store 10% of requests"). Applications control volume.

### Cost Attribution Depends on Client Data

Cost and token attribution are only as good as the data applications send. If applications omit token counts or misreport cost, aggregates will be wrong or incomplete. The platform does not validate against provider billing.

### JSON Schema Evaluator Requires jsonschema

The JsonSchemaEvaluator depends on the `jsonschema` package. It is an optional dependency; install explicitly if used.

---

## Operational Constraints

### No SLAs

The platform does not provide contractual guarantees for availability or latency. It is best-effort. Teams relying on it for critical decisions should have fallbacks.

### No Retention Automation

Retention periods are documented but not enforced by the platform. Implementing retention (e.g. purging old requests) requires a separate job or manual process.

### Single-Region Assumption

Deployment documentation assumes a single database and single region. Cross-region replication, failover, and global latency are not addressed.

### No On-Premise or Air-Gapped Support

Designed for standard cloud or internal infrastructure with network access. Air-gapped or strictly offline deployment is not supported.

---

## Known Gaps

- **Application ID validation:** Any string is accepted. No registry of valid applications.
- **Prompt/model version format:** Free-form strings. No semantic versioning or naming convention enforced.
- **Large payload handling:** Very large `input_text` or `output_text` may stress storage and queries. No explicit limits beyond database constraints.
- **Concurrent write handling:** Optimistic concurrency or conflict resolution is not implemented. Last write wins.
- **Idempotency for logs:** POST /logs does not support idempotency keys. Duplicate submissions create duplicate records.
