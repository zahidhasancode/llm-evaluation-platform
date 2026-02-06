# Deployment

This document describes how to deploy the LLM Evaluation & Monitoring Platform. It covers system requirements, configuration, database setup, running the API and workers, and rollback.

---

## 1. System Requirements

### Runtime

| Requirement | Minimum |
|-------------|---------|
| **Python** | 3.10+ |
| **PostgreSQL** | 14+ (for JSONB, gen_random_uuid, percentile_cont) |
| **CPU** | 2 vCPU for API; 1+ vCPU per worker |
| **Memory** | 2 GB for API; 1 GB per worker (more for large eval runs) |
| **Disk** | Depends on retention; plan for ~1 GB per 1M request records |

### Dependencies

- SQLAlchemy 2.x
- FastAPI, Uvicorn
- psycopg2 or asyncpg (PostgreSQL driver)
- Pydantic 2.x

### Network

- API must be reachable by applications that push logs and by users querying metrics.
- Workers must reach the database and the job queue.
- If using an LLM-as-judge evaluator, workers must reach the LLM provider API.

---

## 2. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string. Format: `postgresql://user:password@host:port/dbname`. Use `?sslmode=require` for TLS. |
| `QUEUE_URL` | If workers used | Job queue connection (e.g. Redis URL, RabbitMQ, SQS). Omit if evaluation workers are not deployed. |
| `LOG_LEVEL` | No | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`. Default: `INFO`. |
| `API_HOST` | No | Bind address for API. Default: `0.0.0.0`. |
| `API_PORT` | No | Port for API. Default: `8000`. |

### Optional (LLM Judge)

| Variable | Required | Description |
|----------|----------|-------------|
| `LLM_JUDGE_MODEL` | No | Model identifier for judge (e.g. `gpt-4`, `claude-3-sonnet`). |
| `LLM_JUDGE_API_KEY` | No | API key for LLM provider. Passed to the judge client implementation. |
| `LLM_JUDGE_TIMEOUT_SEC` | No | Timeout for judge API calls. Default: `60`. |

### Security

- Do not commit `DATABASE_URL`, `LLM_JUDGE_API_KEY`, or `QUEUE_URL` to source control.
- Use a secrets manager or environment injection (e.g. Kubernetes secrets, Vault) in production.

---

## 3. Database Setup

### Create Database

```bash
createdb llm_eval_platform
```

Or via your cloud provider’s PostgreSQL service.

### Run Schema

Apply the DDL from `docs/DATA_MODEL.md`:

```bash
psql $DATABASE_URL -f docs/DATA_MODEL.md
```

If the schema is in a SQL file (e.g. `migrations/001_initial.sql`):

```bash
psql $DATABASE_URL -f migrations/001_initial.sql
```

### Migrations

For iterative changes, use a migration tool (e.g. Alembic) or versioned SQL files. Apply migrations in order before deploying a new version of the application.

### Permissions

- Create a dedicated database user for the application.
- Grant `SELECT`, `INSERT`, `UPDATE`, `DELETE` on application tables.
- Restrict access to migration/admin tables.

### Retention

Configure retention (e.g. via pg_cron, external job, or application logic):

- **Request store:** Default 90 days. Adjust based on storage and compliance.
- **Evaluation results:** Default 1 year.
- **Run state:** Retain long enough for debugging; 1 year is typical.

---

## 4. Running the API

### Application Entry Point

The API is a FastAPI application. Wire routers in the main app:

```python
# main.py or app.py
from fastapi import FastAPI
from api.logs import router as logs_router
from api.metrics import router as metrics_router

app = FastAPI(title="LLM Evaluation Platform", version="1.0.0")
app.include_router(logs_router)
app.include_router(metrics_router)
```

### Development

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/llm_eval_platform"
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

- Use `--workers` for multiple processes. Each worker has its own connection pool.
- Run behind a reverse proxy (nginx, Envoy) for TLS termination and load balancing.
- Configure the proxy to set `X-Forwarded-For` and `X-Forwarded-Proto` if needed.

### Health Checks

- **Liveness:** `GET /health` or `GET /` (if defined). Returns 200 when the process is running.
- **Readiness:** Should verify database connectivity. Return 503 if the database is unreachable.

Implement health endpoints if not present. Example:

```python
@app.get("/health")
def health():
    return {"status": "ok"}
```

### Scaling

- The API is stateless. Scale horizontally by adding more instances behind a load balancer.
- Connection pool size: default 5–10 per worker. Total connections ≈ workers × pool size. Stay under the database `max_connections` limit.

---

## 5. Running Evaluation Workers

### Prerequisites

- Job queue (Redis, RabbitMQ, SQS, etc.) configured and reachable.
- Database accessible.
- Worker process can load evaluation criteria and datasets from storage.

### Worker Process

Workers consume run IDs from the queue, load run metadata and datasets, execute evaluation logic, and write results. The exact command depends on the worker implementation:

```bash
export DATABASE_URL="..."
export QUEUE_URL="..."
python -m workers.run
```

Or via a process manager (systemd, supervisord, Kubernetes Job):

```ini
[program:llm-eval-worker]
command=python -m workers.run
environment=DATABASE_URL="...",QUEUE_URL="..."
autostart=true
autorestart=true
```

### Scaling

- Run multiple worker instances for parallel evaluation runs.
- Target: at least 10 workers for 10 concurrent runs (per requirements).
- Monitor queue depth. Scale workers up if the backlog grows.

### Resource Limits

- Large runs (e.g. 100k items) may use significant memory. Set memory limits per worker (e.g. 4 GB).
- CPU: evaluation logic is CPU-bound for rule-based evaluators. LLM-as-judge is I/O-bound; more workers help more than more CPU per worker.

### Deployment Order

1. Deploy database and schema.
2. Deploy queue (if used).
3. Deploy API.
4. Deploy workers.

Workers can be scaled independently of the API.

---

## 6. Rollback Considerations

### Application Rollback

- **Stateless API:** Rolling back to a previous image or version is straightforward. Terminate old processes, start new ones. No in-process state is lost.
- **Workers:** In-flight runs may be interrupted. Runs remain in "running" state until a timeout or manual intervention. Document how to mark stuck runs as failed.

### Database Rollback

- **Schema downgrades:** Avoid if possible. Downgrades that drop columns or tables can cause data loss. Prefer forward-only migrations when feasible.
- **If a migration must be reverted:** Run the downgrade migration. Ensure the application version is compatible with the reverted schema before deploying.
- **Data:** Application rollback does not revert data. Deleted or modified records are not restored unless you have backups and a restore procedure.

### Deployment Strategy

- **Blue-green or canary:** Deploy new API version alongside old. Shift traffic gradually. Roll back by shifting traffic back to the old version.
- **Database migrations:** Run migrations before or during deployment. Ensure backward compatibility: the old application must work with the new schema, or migrations run in a maintenance window when traffic is stopped.

### Pre-Rollback Checklist

- [ ] Identify the last known good version or commit.
- [ ] Confirm database migration state (which migrations have been applied).
- [ ] Plan for in-flight evaluation runs (mark as failed or allow to complete).
- [ ] Notify dependent teams if the API contract or behavior changes.

### Post-Rollback

- Verify health checks pass.
- Spot-check critical paths: POST /logs, GET /metrics.
- Monitor error rates and latency for 15–30 minutes.
- Document the incident and root cause.
