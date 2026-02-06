# Success Metrics

## 1. Goals of Measurement

Success metrics for this platform serve three purposes:

- **Justify continued investment.** The platform consumes engineering and infrastructure resources. Stakeholders need evidence that it reduces operational risk, accelerates decision-making, or lowers cost—not just that it exists.

- **Guide prioritization.** Not all capabilities deliver equal value. Metrics help identify what matters most (e.g., regression detection vs. cost attribution) and where to invest next.

- **Detect misalignment.** If adoption is low or usage patterns diverge from assumptions, metrics surface that early. Teams can correct course before the platform becomes shelfware.

These metrics are intended for internal review by platform leads, engineering managers, and ML teams. They are not for external reporting or marketing.

---

## 2. Primary Success Metrics

Primary success metrics indicate that the platform is enabling better decisions and outcomes. Each metric is tied to a concrete decision or outcome.

### Proportion of Changes Evaluated Before Rollout

- **Metric:** For each prompt or model change that reaches production, was an evaluation run executed (using the platform) before the change affected the majority of traffic? Count: (changes with prior eval) / (total changes).
- **Decision enabled:** "Do we ship this change?" and "Should we roll back?"
- **Target:** Establish baseline in first quarter (e.g., survey or manual count). Target: increase by at least 30 percentage points within 12 months (e.g., 20% → 50%).
- **Interpretation:** Higher proportion = more changes validated before user impact.

### Time to Compare Versions

- **Metric:** For a comparison of two prompt versions or two model versions on the same dataset: time from submission of the evaluation run(s) to availability of comparable results.
- **Decision enabled:** "Which prompt or model should we use?" and "Should we roll back?"
- **Target:** p95 within 4 hours for runs of ≤10,000 items. (Longer runs may have relaxed targets.)
- **Interpretation:** Lower time = faster iteration and rollback decisions.

### Cost Attribution Coverage

- **Metric:** Proportion of total LLM spend (by dollar) that can be attributed to at least one of: application, prompt version, or model version. Unallocated = spend for requests missing these identifiers.
- **Decision enabled:** "What is our spend by product?" and "Where should we optimize?"
- **Target:** >80% of spend attributable within 6 months of full adoption. Baseline = current unallocated proportion (from provider bills or pre-platform estimate).
- **Interpretation:** Higher coverage = more actionable cost visibility for forecasting and optimization.

### Traceability of Incidents to Prompt/Model Version

- **Metric:** When a production incident involves LLM quality or behavior, can the team identify the prompt version and model version for affected requests using platform data? Binary per incident: traceable or not.
- **Decision enabled:** "What caused this incident?" and "Should we roll back?"
- **Target:** 100% of LLM-related incidents traceable (assuming request data was sent to the platform for the affected time range). Establish baseline: count of incidents that were traceable pre-platform (likely 0).
- **Interpretation:** Traceable incidents enable faster root cause analysis and targeted rollback.

### Time to Identify Root Cause for LLM Incidents

- **Metric:** For incidents that are traceable: time from incident detection (e.g., alert or user report) to identification of the prompt version and model version implicated.
- **Decision enabled:** "What do we roll back?" and "What do we fix?"
- **Target:** Establish baseline after first quarter of incidents. Target: reduce median time by at least 50% vs. pre-platform baseline (or vs. incidents where traceability was not available).
- **Interpretation:** Faster identification = faster remediation and less blast radius.

---

## 3. Secondary Success Metrics

Secondary metrics indicate adoption breadth and that the platform is embedded in team workflows. They support—but do not replace—primary metrics.

### Teams with Sustained Usage

- **Metric:** Number of distinct teams that have submitted at least one evaluation run and queried results at least once in each of the last two 30-day periods.
- **Outcome:** Indicates the platform is part of routine workflow, not one-off experimentation.
- **Target:** Growth in sustaining teams over 6–12 months. Define "team" (e.g., product team, application owner).
- **Interpretation:** Sustained usage > one-off usage as an adoption signal.

### Changes with Platform Evaluation

- **Metric:** Proportion of prompt/model changes that have at least one associated evaluation run in the platform (before or after rollout).
- **Decision enabled:** "Do we have data to support this change?"
- **Target:** Increase over time; complementary to "proportion evaluated before rollout" (this counts any eval, not just pre-rollout).
- **Interpretation:** Higher proportion = evaluation is standard practice for changes.

### Time to Produce Cost Report

- **Metric:** Time from "we need spend by application for last month" to having the report (using platform data).
- **Decision enabled:** "What did we spend?" and "How do we forecast?"
- **Target:** < 1 hour for a single analyst, for standard dimensions (application, model, prompt version) over a 30-day window.
- **Interpretation:** Lower time = cost visibility supports operational and planning decisions.

---

## 4. Operational Signals

Operational signals indicate platform health and reliability. They do not directly measure success but must be adequate for the platform to be usable and trusted.

### Run Completion Rate

- **Metric:** Proportion of evaluation runs that reach a terminal success state (completed) vs. failed or timed out. Exclude runs that exceed documented size limits.
- **Target:** >95% success rate.
- **Interpretation:** Low completion rate erodes trust and discourages usage.

### Time from Run Submission to Results

- **Metric:** Time from acceptance of an evaluation run to availability of results for retrieval.
- **Target:** p95 < 4 hours for runs of ≤10,000 items.
- **Interpretation:** Slow results reduce the value of evaluation for iteration.

### Ingestion Lag

- **Metric:** For request data pushed to the platform: p95 delay from request timestamp to data being available for query.
- **Target:** < 24 hours for batch ingestion; document expectations for near-real-time if supported.
- **Interpretation:** High lag limits usefulness for incident investigation and recent-period analysis.

### Repeatability for Deterministic Criteria

- **Metric:** For evaluation criteria that are deterministic (e.g., exact match, regex, length check): when the same dataset and criteria are run twice, results are identical.
- **Target:** 100% repeatability for deterministic criteria.
- **Interpretation:** Non-repeatable results undermine confidence in comparisons.

### Data Durability

- **Metric:** Count of evaluation runs or request batches for which data was lost (e.g., corruption, failed recovery).
- **Target:** Zero data loss for completed runs.
- **Interpretation:** Data loss is unacceptable for a platform that stores evaluation history.

---

## 5. Risk-Related Metrics

These metrics track reduction of operational risk. They are success-oriented but may be harder to measure until sufficient incident history exists.

### Mean Time to Detect Regression (Post-Ship)

- **Metric:** When a regression is detected after a change has shipped: time from when the change reached production to when the regression was identified (via platform data, user report, or monitoring).
- **Decision enabled:** "How quickly do we find problems?"
- **Target:** Establish baseline after incidents occur. Target: reduce over time as evaluation and monitoring improve.
- **Interpretation:** Faster detection = smaller blast radius and less user impact.

### Rollback Decision Time

- **Metric:** For incidents where rollback was the remedy: time from incident detection to decision to roll back (or rollback execution).
- **Decision enabled:** "How quickly do we act?"
- **Target:** Establish baseline. Target: reduce when platform data (traceability, comparison) supports faster root cause identification.
- **Interpretation:** Platform value includes enabling faster, data-driven rollback decisions.

---

## 6. Anti-Metrics

The following should **not** be used to judge platform success. They can be misleading or incentivize the wrong behavior.

### Raw Usage Volume

- **Do not use:** Total number of API calls, evaluation runs, or requests stored as a primary success indicator.
- **Why:** High volume can reflect inefficiency (e.g., repeated failed runs), a single heavy user, or misconfigured pipelines. Volume does not imply value.

### Evaluation Run Count in Isolation

- **Do not use:** Number of evaluation runs per month as a standalone success metric.
- **Why:** Can incentivize running redundant or low-value evals. Prefer "proportion of changes evaluated" or "changes with associated eval" as decision-linked metrics.

### Number of Adopting Teams Without Usage Depth

- **Do not use:** Raw count of teams that have ever used the platform.
- **Why:** One-off usage does not indicate sustained value. Prefer "teams with sustained usage" (runs and queries in consecutive periods).

### Lines of Code or Feature Count

- **Do not use:** Lines of code, number of endpoints, or count of features as success metrics.
- **Why:** Platform value comes from outcomes (better decisions, faster iteration), not code size or feature count.

### Number of Dashboards or Reports

- **Do not use:** Count of dashboards, visualizations, or reports built on top of the platform.
- **Why:** v1 has no dashboards; even with future UI, more dashboards do not equal more value. Focus on decisions enabled.

### Uptime or Availability in Isolation

- **Do not use:** Uptime percentage as a primary success metric without context.
- **Why:** High uptime is a baseline expectation. It does not indicate whether the platform is used or improves outcomes. Use operational signals (run completion rate, ingestion lag) instead.

### User Satisfaction Surveys as the Sole Measure

- **Do not use:** NPS or satisfaction scores as the primary indicator of success without correlating with usage and outcomes.
- **Why:** Satisfaction can be high even when usage is low or impact is minimal. Combine with adoption and outcome metrics.

### Cost Savings Without Baseline or Attribution

- **Do not use:** "We saved $X by optimizing LLM spend" without a clear baseline and attribution to platform-enabled decisions.
- **Why:** Savings are hard to attribute. Avoid claiming credit for optimizations that might have happened without the platform. Prefer cost attribution coverage and time to produce cost report.

### Number of Regressions Detected

- **Do not use:** Count of regressions detected by the platform as a success metric.
- **Why:** Can incentivize detecting more regressions (including false positives) rather than preventing user impact. Prefer "proportion of changes evaluated before rollout" as the direction of improvement.
