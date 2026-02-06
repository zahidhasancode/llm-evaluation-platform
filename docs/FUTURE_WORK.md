# Future Work

Realistic next steps for the platform. Not committed or scheduled; prioritization depends on adoption and feedback.

---

## Near-Term: Complete Core Pipeline

### Evaluation Run Orchestration

Implement the worker pipeline: API endpoint for run submission, job queue integration, worker process that consumes runs, loads datasets, executes evaluators, and writes results. This unblocks evaluation at scale without custom scripting.

### Dataset Creation and Storage

Add storage and API for versioned evaluation datasets. Support creation from stored requests (filter by version, application, time range) and from user uploads. Enable "run eval on dataset X" without manual data assembly.

### Version Registry

Add storage and API for prompt and model versions. Validate that request ingestion references registered versions. Enables lineage and prevents orphaned references.

### Health and Readiness Endpoints

Implement `/health` and `/ready`. Readiness should check database connectivity. Required for Kubernetes and load balancers.

---

## Scaling Improvements

### Precomputed Rollups

Add a periodic job that precomputes metrics (token sum, latency percentiles) for fixed time windows (e.g. hourly, daily) by application, prompt version, model version. Serve rollups for large-range queries to keep latency bounded.

### Query Limits and Timeouts

Enforce maximum time range or result set size for metrics queries. Return 400 for requests that would be too expensive. Prevents a single expensive query from impacting the API.

### Connection Pool Tuning

Document and expose pool size configuration. Allow tuning for expected concurrency. Add metrics for pool utilization.

### Worker Autoscaling

Design worker scaling based on queue depth. Document how to scale workers in Kubernetes or similar (e.g. HPA on queue length). Ensure workers handle graceful shutdown and drain in-flight runs.

---

## Additional Evaluators

### Exact Match and Similarity

Evaluator that compares output to expected output: exact match, substring containment, or embedding similarity (e.g. cosine). Useful for regression testing on golden sets.

### Regex and Pattern Matching

Evaluator that checks output against configurable regex patterns. Supports "must contain" or "must not contain" rules.

### Structured Output Validation

Evaluator that validates output against a JSON schema and optionally checks required fields or value constraints. Extends JsonSchemaEvaluator with more granular rules.

### Custom Script Evaluators

Allow users to provide evaluation logic as a script (e.g. Python) that the platform runs in a sandbox. High flexibility; requires careful security and isolation design.

### Safety Evaluators (Toxicity, PII)

Evaluators that detect toxic content or PII leakage. May use classifiers or heuristics. Depends on organizational requirements and acceptable false positive rates.

---

## Alerting and Automation

### Scheduled Comparisons

Run comparison between baseline and candidate (e.g. prompt v1 vs v2) on a schedule. Store results. Optionally trigger a notification when deltas exceed thresholds.

### Regression Alerts

When a new evaluation run completes, compare to the previous run on the same dataset. If score drops beyond a threshold, emit an alert (webhook, Slack, PagerDuty). Requires defining "previous run" and threshold configuration.

### Cost and Latency Anomaly Detection

Alert when daily or hourly cost or p95 latency exceeds a baseline (e.g. 2x the 7-day rolling average). Simple rule-based; no ML. Helps catch provider issues or traffic spikes.

### Webhook for Run Completion

Allow users to register a webhook URL. When an evaluation run completes (or fails), POST to that URL. Reduces polling for integrators.

---

## Product and UX

### Web UI

Basic UI for querying metrics, viewing comparison results, and monitoring evaluation runs. Internal tool quality; not a polished product. Reduces barrier for non-engineers.

### CLI

Command-line tool for common operations: submit logs, query metrics, trigger evaluations, fetch comparison results. Wraps API calls for local workflows and scripts.

### Export to BI Tools

Export endpoints or scheduled exports to formats suitable for data warehouses or BI tools (e.g. Parquet, CSV to S3). Enables dashboards in Tableau, Looker, etc., without building them in the platform.

---

## Platform and Operations

### Authentication and RBAC

Add authentication (e.g. API keys, OAuth). Add role-based access: read-only vs read-write, per-application or per-team scoping. Required for multi-team adoption.

### Audit Logging

Log who performed which actions (e.g. who submitted a run, who created a dataset). Store in a separate audit table or log stream. Supports compliance and debugging.

### Multi-Tenancy

Support multiple teams or applications with data isolation. Requires schema or partitioning changes and access control. Significant effort.

### Retention Automation

Implement a job that deletes or archives data beyond retention policy. Configurable per table (requests, results, run state). Run daily or weekly.

### On-Premise or Air-Gapped Deployment

Document and test deployment in environments without external network access. May require bundling dependencies, alternative queue backends, and modified judge setup (e.g. local model).

---

## Deprioritized or Deferred

- **Streaming evaluation:** Evaluating outputs as they arrive in real time. Complex; batch covers most use cases.
- **Multi-turn conversation support:** Modeling turns and context. Requires schema and query pattern changes.
- **Automatic log ingestion:** Pulling from production systems. High integration complexity; push is sufficient for many teams.
- **Formal SLAs:** Contractual guarantees. Requires operational maturity and monitoring; defer until demand is clear.
- **LLM inference for evals:** The platform could run inference to generate outputs for evaluation. Out of scope; applications supply outputs.
