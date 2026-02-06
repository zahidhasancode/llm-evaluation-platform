# Failure Modes

This document describes realistic production failure scenarios for the LLM Evaluation & Monitoring Platform, how the system behaves in each case, and recommended mitigations.

---

## 1. Database Failures

### Scenario

PostgreSQL becomes unavailable due to:
- Primary instance failure before failover completes
- Network partition between application and database
- Connection pool exhaustion under load
- Disk full or storage I/O errors

### System Behavior

- **Request ingestion (POST /logs):** Writes fail. The API returns 500. Clients receive no acknowledgment. Request data is lost unless the client retries.
- **Metrics queries (GET /metrics):** Queries fail. The API returns 500. Users cannot retrieve aggregated metrics.
- **Evaluation workers:** Runs fail when reading datasets or writing results. Run state may remain "running" until timeout. Partial results are not persisted (by design).

Idempotency keys on evaluation run submission prevent duplicate runs if the client retries after a timeout; however, if the failure occurs after the run record is written but before the queue message is processed, the run may be orphaned (pending forever).

### Mitigation Strategies

- **Connection pooling:** Use a pool with sensible limits. Monitor pool utilization. Set connection timeouts.
- **Retries:** Clients should retry POST /logs with exponential backoff. Use idempotency keys for evaluation run submission.
- **Read replicas:** Route metrics queries to read replicas when available. Accept replication lag for non-critical dashboards.
- **Health checks:** Expose liveness and readiness probes. Readiness should fail when the database is unreachable. Orchestrators can stop sending traffic.
- **Circuit breaker:** Consider circuit-breaking database calls after repeated failures to avoid cascading timeouts.
- **Run timeout:** Implement a background job that marks runs as "failed" if they remain "running" beyond a threshold (e.g. 24 hours).

---

## 2. Partial Logging

### Scenario

Applications fail to push request data to the platform reliably:
- Batch upload jobs fail partway through
- Network blips cause drops before acknowledgment
- Client-side buffering is lost on process crash
- Rate limiting causes clients to drop or skip log entries

### System Behavior

- **Incomplete coverage:** Metrics aggregates undercount requests. Cost attribution is low. Evaluation datasets drawn from production logs miss a portion of traffic.
- **Skewed metrics:** If failures correlate with certain applications, models, or time windows, aggregates are biased. p95 latency may be understated if slow requests are dropped more often.
- **Incident traceability:** When investigating an incident, some affected requests may not be in the platform. Root cause analysis is incomplete.

The platform has no visibility into what was not logged. It cannot distinguish "no traffic" from "logging failed."

### Mitigation Strategies

- **Client-side buffering:** Buffer request logs locally (e.g. file, in-memory queue) and retry pushes. Flush on graceful shutdown.
- **Batch size and backpressure:** Use smaller batches to reduce blast radius of partial failures. Respect 429 or 5xx responses; back off and retry.
- **Coverage monitoring:** Track the proportion of expected vs. actual log volume if a separate source of truth exists (e.g. application metrics, provider billing). Alert on large gaps.
- **Sampling and critical paths:** For high-volume applications, consider sampling. Ensure critical paths (e.g. payment flows) are always logged.
- **Durable queues:** If using a queue between applications and the platform, use a durable queue so logs survive client restarts.

---

## 3. Evaluation Failures

### Scenario

Evaluation runs fail due to:
- Worker crash mid-run
- Dataset too large (OOM, timeout)
- Invalid or malformed evaluation criteria
- Storage unavailable when writing results
- Bug in evaluation logic (e.g. rule-based evaluator raises)

### System Behavior

- **Run state:** Run transitions to "failed." No partial results are persisted (by design). Users must resubmit.
- **Idempotency:** Resubmission with the same idempotency key returns the existing run. If the run failed, the user gets the failed run ID; they must use a new key to retry.
- **Worker failure:** If a worker crashes, the queue may redeliver the message. Workers must handle duplicate delivery (e.g. detect existing results, skip write). A run that was partially processed and then failed will be retried from scratch.

Users receive run status via polling. There is no push notification. If users do not poll, they may not notice failure until later.

### Mitigation Strategies

- **Graceful degradation:** For rule-based evaluators, catch exceptions and return a failure result (score 0, outcome "fail", details with error) rather than crashing the worker.
- **Dataset size limits:** Enforce max dataset size. Reject or split large runs. Document limits clearly.
- **Criteria validation:** Validate evaluation criteria at submission time. Return 400 for invalid criteria rather than failing mid-run.
- **Retry policy:** Document retry behavior. Recommend users retry with a new idempotency key after transient failures.
- **Run timeout:** Mark long-running runs as failed. Avoid indefinite "running" state.
- **Monitoring:** Track run failure rate, failure reasons, and run duration. Alert on elevated failure rate.

---

## 4. LLM Judge Timeouts and Cost Spikes

### Scenario

The LLM-as-judge evaluator calls an external LLM API. Failures include:
- API timeout (30s, 60s, or longer)
- Rate limiting (429)
- Provider outage
- Cost spike from unexpected volume (e.g. a large eval run triggers thousands of judge calls)

### System Behavior

- **Timeout:** The judge's `complete()` raises. The evaluator returns `EvaluationResult(score=0, outcome="fail", details={"error": "llm_call_failed", ...})`. The evaluation run may fail if the judge is used for all items, or produce partial results if some items succeed before the timeout.
- **Rate limiting:** Same as timeout; the client raises. Retries would require logic in the LLM client; the evaluator does not retry.
- **Cost spike:** Token usage scales with dataset size. A 100k-item eval run with the judge could incur significant cost. The platform tracks estimated cost per evaluation in details but does not enforce budgets or alert on cost.

The platform does not call LLMs for the outputs being evaluated; it calls the judge only when running LLM-as-judge evaluations. Judge cost is separate from production inference cost.

### Mitigation Strategies

- **Timeout configuration:** Set explicit timeouts on the LLM client. Fail fast rather than hanging.
- **Batch sizing:** Limit the size of evaluation runs that use the judge. Consider sampling for large datasets.
- **Cost estimation:** Use `input_cost_per_1k` and `output_cost_per_1k` in the judge to estimate cost. Surface estimated cost before running large jobs (if a pre-flight check is added).
- **Rate limiting:** Respect provider rate limits. Use a client that supports backoff or queuing. Consider a dedicated judge model with higher throughput.
- **Fallback:** For critical evals, consider fallback to rule-based evaluators when the judge is unavailable. Document this as an operational procedure.
- **Budget alerts:** Monitor judge token usage and cost. Alert when daily or per-run cost exceeds a threshold.

---

## 5. Latency Anomalies

### Scenario

Unusual latency patterns in production or in the platform itself:
- LLM provider returns responses 10x slower than normal
- Platform metrics queries take minutes instead of seconds
- Evaluation runs that normally complete in hours run for days
- p99 latency spikes without a clear cause

### System Behavior

- **Production latency in logged data:** The platform stores whatever latency value the application reports. If the application logs latency correctly, aggregates (avg, p95, p99) will reflect the spike. If the application times out before logging, the request may not appear, or latency may be missing (null). Nulls are excluded from latency aggregates, so the reported p95 may understate the true tail.
- **Platform query latency:** Slow aggregation queries (e.g. over a large time range, many dimensions) can block the API. Clients may timeout. No partial results are returned.
- **Evaluation run duration:** Long-running runs occupy workers. Other runs queue. Submission latency for new runs may increase. The platform does not preempt or cancel runs.

The platform does not automatically detect or alert on latency anomalies. Users must query metrics and interpret results.

### Mitigation Strategies

- **Rollups:** Precompute metrics for common time windows and dimensions. Use rollups for large-range queries. Document when rollups are used and their freshness.
- **Query limits:** Enforce max time range or max result set size. Return 400 for requests that would be too expensive.
- **Indexing:** Ensure indexes support common query patterns (application, time range, version). Monitor slow queries.
- **Worker capacity:** Scale workers for evaluation throughput. Monitor queue depth and run duration. Alert when backlog grows.
- **Timeout on ingest:** If the application has a timeout before logging, consider logging a "timeout" status with null latency so the request is counted. Enables accurate error rate and request count even when latency is unknown.
- **Operational runbooks:** Document how to investigate latency spikes (e.g. filter by model, prompt, time; compare to baseline; check provider status).

---

## 6. Data Corruption and Schema Drift

### Scenario

- Bad data written (wrong types, truncated strings, invalid JSON in metadata)
- Schema migration applied incompletely (old code writing old schema, new code expecting new)
- Clock skew causing incorrect timestamps

### System Behavior

- **Validation failures:** The API rejects invalid payloads with 4xx. No data is written.
- **Constraint violations:** Unique constraint on (request_id) for responses, check constraints on status. Violations raise `RepositoryError`; API returns 409 or 500.
- **Query failures:** Malformed data may cause aggregation queries to fail or return incorrect results. JSONB fields with invalid structure may cause issues in rare cases.
- **Clock skew:** If application clocks are wrong, `created_at` may be incorrect. Time-range queries and retention policies rely on this field. Ordering and attribution can be wrong.

### Mitigation Strategies

- **Schema migrations:** Use versioned migrations. Test forward and backward compatibility. Coordinate deployments with schema changes.
- **Input validation:** Validate at the API boundary. Reject malformed data early. Log validation failures for debugging.
- **Defensive parsing:** When reading JSONB or optional fields, handle missing or malformed values. Avoid assumptions about structure.
- **Timestamp source:** Prefer server-side timestamps where possible. If client timestamps are used, document the expectation and consider validation (e.g. reject timestamps too far in past or future).
- **Backfill and repair:** Document procedures for correcting bad data (e.g. manual SQL, backfill jobs). Use transactions for bulk corrections.
