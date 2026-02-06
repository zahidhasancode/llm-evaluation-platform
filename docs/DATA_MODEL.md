-- =============================================================================
-- LLM Evaluation & Monitoring Platform - PostgreSQL Schema
-- =============================================================================
-- Internal production platform. Tracks LLM requests, responses, and evaluation
-- results. Supports version-based and time-based querying for metrics and lineage.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. llm_requests
-- -----------------------------------------------------------------------------
-- Captures the request context: prompt, model, application, and input.
-- One row per LLM invocation. Response data stored separately in llm_responses.
-- -----------------------------------------------------------------------------

CREATE TABLE llm_requests (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_name         VARCHAR(255) NOT NULL,
    prompt_version      VARCHAR(128) NOT NULL,
    model_name          VARCHAR(255) NOT NULL,
    model_version       VARCHAR(128) NOT NULL,
    application_id      VARCHAR(128) NOT NULL,
    input_text          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata            JSONB
);

-- Index: time-based querying (metrics, retention, incident lookup)
CREATE INDEX idx_llm_requests_created_at
    ON llm_requests (created_at);

-- Index: filter by application and time (cost/latency attribution by app)
CREATE INDEX idx_llm_requests_application_created_at
    ON llm_requests (application_id, created_at);

-- Index: filter by prompt version and time (compare prompt versions over time)
CREATE INDEX idx_llm_requests_prompt_version_created_at
    ON llm_requests (prompt_name, prompt_version, created_at);

-- Index: filter by model version and time (compare model versions over time)
CREATE INDEX idx_llm_requests_model_version_created_at
    ON llm_requests (model_name, model_version, created_at);

-- Index: composite for metrics aggregation (app + prompt + model + time)
CREATE INDEX idx_llm_requests_aggregation
    ON llm_requests (application_id, prompt_name, prompt_version, model_name, model_version, created_at);

COMMENT ON TABLE llm_requests IS 'Request context for LLM invocations. Joins to llm_responses for output, tokens, latency, cost.';
COMMENT ON COLUMN llm_requests.prompt_name IS 'Human-readable prompt identifier. With prompt_version, identifies the prompt template used.';
COMMENT ON COLUMN llm_requests.prompt_version IS 'Version of the prompt (e.g. git sha, semantic version). Enables version-based comparison.';
COMMENT ON COLUMN llm_requests.model_name IS 'Model identifier (e.g. provider name, model family).';
COMMENT ON COLUMN llm_requests.model_version IS 'Model version (e.g. gpt-4-2024-01, model checkpoint).';
COMMENT ON COLUMN llm_requests.application_id IS 'Application or service that made the request. Used for cost attribution and filtering.';
COMMENT ON COLUMN llm_requests.metadata IS 'Optional extensible metadata. Do not store PII in plaintext.';

-- -----------------------------------------------------------------------------
-- 2. llm_responses
-- -----------------------------------------------------------------------------
-- Captures the response: output, token counts, latency, cost, status.
-- One-to-one with llm_requests. Token and latency data support metrics aggregation.
-- -----------------------------------------------------------------------------

CREATE TABLE llm_responses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id          UUID NOT NULL REFERENCES llm_requests (id) ON DELETE RESTRICT,
    output_text         TEXT,
    input_token_count   INT,
    output_token_count  INT,
    latency_ms          BIGINT,
    cost_usd            DECIMAL(18, 8),
    status              VARCHAR(64) NOT NULL,
    error_type          VARCHAR(128),
    error_code          VARCHAR(64),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata            JSONB,
    CONSTRAINT chk_status CHECK (status IN ('success', 'partial_failure', 'timeout', 'error'))
);

-- Index: join from requests (1:1 lookup)
CREATE UNIQUE INDEX idx_llm_responses_request_id
    ON llm_responses (request_id);

-- Index: time-based querying (e.g. responses in last N hours)
CREATE INDEX idx_llm_responses_created_at
    ON llm_responses (created_at);

COMMENT ON TABLE llm_responses IS 'Response data for LLM invocations. Links to llm_requests via request_id. Token counts and latency support metrics aggregation.';
COMMENT ON COLUMN llm_responses.status IS 'success | partial_failure | timeout | error. Enables reliability and failure visibility.';
COMMENT ON COLUMN llm_responses.cost_usd IS 'Cost in USD for this response. Aggregated by app/version for cost attribution.';
COMMENT ON COLUMN llm_responses.metadata IS 'Optional extensible metadata. Do not store PII in plaintext.';

-- -----------------------------------------------------------------------------
-- 3. llm_evaluations
-- -----------------------------------------------------------------------------
-- Stores evaluation results per response. Each row is one criterion applied to
-- one response. evaluation_run_id groups results from the same evaluation run.
-- -----------------------------------------------------------------------------

CREATE TABLE llm_evaluations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    response_id         UUID NOT NULL REFERENCES llm_responses (id) ON DELETE CASCADE,
    evaluation_run_id   UUID NOT NULL,
    criterion_name      VARCHAR(255) NOT NULL,
    criterion_version   VARCHAR(128),
    score               DECIMAL(18, 6),
    outcome             VARCHAR(64),
    result_metadata     JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_eval_result CHECK (score IS NOT NULL OR outcome IS NOT NULL)
);

-- Index: lookup evaluations for a response (lineage, debugging)
CREATE INDEX idx_llm_evaluations_response_id
    ON llm_evaluations (response_id);

-- Index: group results by evaluation run (retrieve all results for a run)
CREATE INDEX idx_llm_evaluations_run_id
    ON llm_evaluations (evaluation_run_id);

-- Index: filter by criterion (compare runs using same criterion)
CREATE INDEX idx_llm_evaluations_criterion
    ON llm_evaluations (criterion_name, criterion_version);

-- Index: time-based querying (e.g. evals created in date range)
CREATE INDEX idx_llm_evaluations_created_at
    ON llm_evaluations (created_at);

COMMENT ON TABLE llm_evaluations IS 'Per-response evaluation results. One row per (response, criterion). evaluation_run_id groups results from same run.';
COMMENT ON COLUMN llm_evaluations.evaluation_run_id IS 'Groups all results from one evaluation run. No FK; run metadata stored elsewhere.';
COMMENT ON COLUMN llm_evaluations.score IS 'Numeric score when criterion produces a number.';
COMMENT ON COLUMN llm_evaluations.outcome IS 'Categorical outcome (e.g. pass, fail) when criterion produces discrete result.';
COMMENT ON COLUMN llm_evaluations.result_metadata IS 'Optional per-item result details. Structure depends on criterion type.';
