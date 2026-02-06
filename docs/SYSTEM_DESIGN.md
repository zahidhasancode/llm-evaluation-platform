# System Design

## 1. Overview

### Purpose

The LLM Evaluation & Monitoring Platform provides a centralized system for storing LLM request data, running evaluations, and deriving metrics. It enables teams to compare prompt and model versions, attribute cost and latency to applications, and trace production incidents to specific configurations.

### Role in ML Production Workflows

The platform sits downstream of inference. Applications that call LLMs (or self-hosted models) push request metadata and outputs to the platform after inference completes. The platform does not run inference; it stores, evaluates, and aggregates data that users supply. Its role is to:

- **Ingest** request logs and outputs from production or from user-provided datasets
- **Evaluate** outputs against user-defined criteria
- **Store** results and metadata for retrieval and comparison
- **Aggregate** token consumption and latency by prompt version, model version, and application

The platform is an observability and evaluation layer for LLM-powered systems—not a runtime for inference.

---

## 2. High-Level Architecture

### Major Components

| Component | Responsibility |
|-----------|----------------|
| **API** | Single entry point: request ingestion, evaluation run submission, result retrieval, metrics and lineage queries, version registration. Stateless; delegates work to storage, queue, and aggregation logic. |
| **Storage** | Persist all durable data: request records, version registry, datasets, run state, evaluation results. Composed of logical stores with different access patterns (see §3). |
| **Job Queue** | Decouple run submission from execution. API enqueues new runs; workers consume. Supports at-least-once delivery and retries. |
| **Evaluation Workers** | Consume runs from the queue, execute evaluation logic, write results to storage, update run state. Stateless; scale by adding workers. |
| **Aggregation Logic** | Compute token sums and latency percentiles over stored requests by dimension and time range. May use precomputed rollups for large windows. |
| **Rollup Producer** | Periodic job that precomputes metrics summaries (e.g., hourly or daily by application, version) for query latency targets. |

### Data Flow Summary

```
Users / Applications
        │
        ├──► Push request data ───────────────► API ──► Storage (request store)
        │
        ├──► Upload / create dataset ─────────► API ──► Storage (dataset store)
        │
        ├──► Submit evaluation run ───────────► API ──► Storage (run state) + Job Queue
        │                                                    │
        │                                                    ▼
        │                                            Evaluation Workers
        │                                                    │
        │                                                    ▼
        │                                            Storage (results, run state)
        │
        ├──► Query results / lineage ──────────► API ◄── Storage (direct read)
        │
        └──► Query aggregated metrics ─────────► API ◄── Aggregation Logic ◄── Storage (request store)
                                                                                    ▲
                                                              Rollup Producer ──────┘
```

Data flows in four phases: **Logging** (requests), **Dataset Creation** (inputs for eval), **Evaluation** (runs and results), **Metrics** (aggregation and query).

---

## 3. Core Components

### API

The API is the single entry point. It is stateless and horizontally scalable. Responsibilities:

- **Request ingestion** — Accept request records (prompt version ID, model version ID, application ID, timestamp, input, output, token counts, latency, outcome status, error details) in batches or individually. Validate required fields and version references. Write to request store. Return acknowledgment. Ingestion is synchronous from the client perspective; writes are durable before acknowledgment.
- **Dataset creation** — Accept dataset uploads (inputs, optional labels, metadata) or requests to extract a dataset from stored requests by filter (version, application, time range). Version and store in dataset store. Return dataset version ID.
- **Evaluation run submission** — Accept run requests (dataset version ID, evaluation criteria, prompt/model version references). Validate references. Create run record (status: pending) in storage. Enqueue run ID to job queue. Return run ID. Support idempotency keys: same key returns existing run ID without enqueuing again.
- **Result and lineage retrieval** — Serve evaluation run status and per-item results from storage (filtered by run ID). For lineage: given request ID, read request record from storage and return prompt version ID and model version ID.
- **Metrics retrieval** — Invoke aggregation logic with query parameters (dimensions, time range, metric type). Return aggregated values (token sums, latency percentiles).
- **Version registration** — Accept registration of prompt and model versions (identifier, metadata). Ensure uniqueness. Store in version registry.

The API does not execute evaluation or aggregation; it orchestrates reads and writes. For async operations (evaluation runs), it returns immediately with a run ID; clients poll for status.

### Storage

The storage layer persists all durable data. It is logically partitioned into stores with different access patterns and retention needs:

| Store | Contents | Access Pattern | Retention |
|-------|----------|----------------|-----------|
| **Request store** | Request records (input, output, metadata, tokens, latency, status) | High write volume; range and filter queries for retrieval and aggregation | Configurable (e.g., 90 days) |
| **Version registry** | Prompt versions, model versions (ID, metadata) | Low volume; point lookups for validation and lineage | Indefinite |
| **Dataset store** | Versioned datasets (inputs, labels) | Medium volume; bulk reads for eval runs | Configurable |
| **Run state store** | Run metadata (status, timestamps, criteria, version refs) | Moderate writes (status updates); point lookups | Configurable (e.g., 1 year) |
| **Results store** | Per-item evaluation results | Bulk writes per run; range queries by run ID | Configurable |

Storage must support the query patterns required for aggregation (filter by version, application, time range) and for lineage (request ID → version IDs). Implementation may use one or more backing systems; the logical partition guides indexing and retention.

### Job Queue

The job queue decouples run submission from execution. Responsibilities:

- **Enqueue** — API enqueues a run ID when a run is submitted. Message includes run ID and enough context for workers to load the run.
- **Consume** — Workers poll or subscribe for messages. At-least-once delivery; workers must handle duplicate delivery (idempotent result writes or duplicate detection).
- **Retries** — Failed or timed-out runs can be retried. Dead-letter handling for permanently failed runs.

The queue is the only mechanism by which workers discover new runs. No direct API-to-worker coupling.

### Evaluation Workers

Workers execute evaluation logic asynchronously. Stateless; scale by adding worker instances. Responsibilities:

- **Consume** — Take run IDs from the job queue. Load run metadata, dataset, and criteria from storage.
- **Execute** — For each item in the dataset, apply evaluation criteria to input and output. Produce score or outcome per item. No inference; criteria are configurable rules (e.g., exact match, regex, length).
- **Persist** — Write per-item results to results store. Update run state to completed. On failure: update run state to failed, persist error details. Do not persist partial results; failed runs are retried from scratch.
- **Idempotency** — If a run is retried (duplicate queue delivery), detect existing results for the run ID and avoid duplicate writes; return success.

Workers process one run at a time (or a bounded number per worker). Large runs (e.g., 100k items) may take hours; scaling is achieved by running multiple workers for concurrent runs.

### Aggregation Logic

Aggregation logic computes metrics over stored request data. Responsibilities:

- **Token aggregation** — Sum input and output tokens by prompt version, model version, and application over a specified time range.
- **Latency aggregation** — Compute latency percentiles (p50, p95, p99) by the same dimensions and time range.
- **Query execution** — Execute on-demand over the request store for small windows, or read from precomputed rollups for large windows. Return correct aggregates within documented latency bounds.

Aggregation logic is read-only. It may run in-process with the API or as a separate service; the API invokes it for metrics queries. Lineage (request ID → version IDs) is a direct storage read by the API, not aggregation.

### Rollup Producer

The rollup producer is a periodic job that precomputes metric summaries. Responsibilities:

- **Compute** — At configured intervals (e.g., hourly, daily), aggregate token and latency metrics by application, prompt version, and model version for fixed time windows.
- **Store** — Write rollup records to storage (or a dedicated rollup store). Aggregation logic reads rollups for queries over large windows instead of scanning raw requests.
- **Trigger** — Scheduled (e.g., cron) or event-driven (e.g., after request ingestion batches). Implementation detail.

---

## 4. Data Flow

### Request Logging Flow

1. Application completes an LLM request. It has: input, output, prompt version ID, model version ID, application ID, timestamp, token counts, latency, outcome status, optional error details.
2. Application pushes this to the API (batches or single records).
3. API validates required fields and that prompt/model version IDs exist in the version registry.
4. API writes request record to the request store. Write is durable before response.
5. API returns acknowledgment (e.g., accepted count or request IDs).
6. Retention policies apply; older data is purged per configuration.

**Note:** The platform does not pull logs. Users push. Ingestion is synchronous: client waits for durable write.

### Dataset Creation Flow

1. User prepares inputs (and optionally labels) for evaluation. Source: external upload or extraction from stored requests.
2. User calls API to create a dataset. If extracting: API reads from request store by filter (version, application, time range), assembles dataset, versions it. If uploading: API accepts payload, versions it.
3. API stores dataset in dataset store with a version ID.
4. API returns dataset version ID. User references this when submitting evaluation runs.

### Evaluation Flow

1. User has a dataset version ID and evaluation criteria. Submits evaluation run via API (with optional prompt/model version refs for association).
2. API validates dataset and criteria. Creates run record in run state store (status: pending).
3. API enqueues run ID to job queue. Returns run ID to user immediately.
4. Evaluation worker consumes run ID from queue. Loads run metadata, dataset, and criteria from storage.
5. Worker processes each item: applies criteria to input/output, produces score. Writes all results to results store. Updates run state to completed (or failed with error).
6. User polls API for run status. When completed, user retrieves results via API by run ID.
7. Idempotency: Retry with same idempotency key returns existing run ID; no duplicate enqueue. Duplicate queue delivery: worker detects existing results for run ID and skips duplicate writes.

### Metrics Query Flow

1. User queries API for aggregated metrics (dimensions, time range, metric type).
2. API invokes aggregation logic with query parameters.
3. Aggregation logic: for small windows, reads from request store and computes aggregates; for large windows, reads from rollup store if available.
4. API returns aggregated values to user.
5. Rollup producer runs periodically, computes summaries, writes to rollup store. Queries over rolled-up windows use this data.

### Lineage Lookup Flow

1. User has request ID (e.g., from incident). Queries API with request ID.
2. API reads request record from request store. Extracts prompt version ID and model version ID.
3. API returns version IDs to user. No aggregation logic involved.

---

## 5. Scaling and Reliability Assumptions

### Scaling

- **API** — Stateless. Scale horizontally. Request ingestion and metrics queries can hit different instances.
- **Request ingestion** — Target 1M requests/day. Synchronous writes; storage must sustain write throughput. Batching at the client or API can reduce per-request overhead.
- **Evaluation workers** — Scale by adding workers. Target 10 concurrent runs. Each run may process up to 100k items; long-running runs occupy a worker until completion. Worker count ≥ concurrent run target.
- **Job queue** — Must support at least 10 in-flight messages and burst enqueue. No strict ordering requirement.
- **Storage** — Request store scales with volume and retention (e.g., 90M rows at 1M/day, 90-day retention). Indexing and partitioning by time and dimensions support query and aggregation patterns. Version registry and run state are small; dataset and results stores scale with eval activity.
- **Aggregation** — On-demand aggregation over large windows (e.g., 1 month, all apps) can be slow. Rollup producer precomputes summaries to keep query latency bounded. Rollup cadence and granularity are implementation choices.

### Reliability

- **Request ingestion** — Write is durable before acknowledgment. On storage failure, API returns error; client may retry. No partial writes; request is stored entirely or not at all.
- **Evaluation runs** — Queue provides at-least-once delivery. Workers must handle duplicates (idempotent writes or duplicate detection). On worker failure mid-run: run remains in running state; timeout or heartbeat marks it failed; retry processes from scratch. No partial result persistence.
- **Data durability** — Completed runs and their results must not be lost. Storage backend must provide durability guarantees (e.g., replication, backups).
- **Rollup producer** — Failures delay precomputation; on-demand aggregation still works for small windows. No critical path dependency.
