# Problem Statement

This document describes the operational and evaluation challenges faced by ML and platform teams when deploying LLM-powered systems in production. It focuses on internal applications and services that call LLM APIs or self-hosted models.

---

**Output quality is difficult to measure and track.** LLMs produce free-form text. Quality is subjective, context-dependent, and often requires human judgment. Teams cannot reliably answer: Is this model performing better than the last? Did the latest change degrade outputs for a subset of requests? Which use cases or user segments are underperforming? Production systems lack feedback that can be consistently collected and analyzed. Standard regression and classification metrics do not apply.

**Regressions ship silently.** Changes to prompts, models, or supporting infrastructure can introduce degradations that go undetected. A/B tests and offline evaluations rarely cover the full production traffic distribution. Subtle issues—weaker reasoning, occasional hallucinations, or worse formatting—can reach users and persist for days or weeks before being reported. By then, the affected traffic volume and user base may be large, and the root cause hard to isolate from other concurrent changes.

**Prompt and model versioning is not traceable.** Prompts evolve; models are upgraded or rolled back. Teams typically do not maintain a versioned record of what was running when and how it performed. As a result, performance changes cannot be reliably attributed to specific prompt edits or model swaps. Debugging and retrospective analysis are unreliable. Decisions about whether to roll back or to iterate on a prompt lack supporting data.

**Latency is unpredictable.** LLM APIs and self-hosted deployments exhibit high variance in response time. p99 latency can vary by an order of magnitude across days or providers. Rate limits and retries add further variation. Operational tooling does not expose request-level, LLM-specific metrics. Teams struggle to detect latency anomalies in real time or to correlate quality issues with infrastructure behavior.

**Cost is difficult to forecast and attribute.** Token usage scales with input and output length. Cost per request varies widely across use cases. Without granular visibility into token consumption by prompt, model, and application, teams cannot accurately forecast spend, attribute cost to products, or justify optimization efforts. Budget overruns and surprise bills are common.

**Reliability and failure modes are opaque.** Retries, fallbacks, and partial failures obscure true failure rates. When a model returns an empty or malformed response, it may be counted as success by downstream systems. Rate limit errors, timeouts, and provider outages are not always surfaced in a way that supports root cause analysis. Correlation between infrastructure incidents and user-reported quality issues is weak.

**Traditional ML evaluation and monitoring tooling does not fit.** Conventional ML tooling assumes structured inputs and outputs, fixed schemas, and batch-oriented evaluation. LLM workloads are interactive, dynamic, and non-deterministic. Observability stacks built for typical services do not handle token counts, prompt templates, model versions, or multi-turn conversations. Teams patch together manual eval scripts, spreadsheets, and one-off dashboards. These approaches do not scale and are not reproducible across teams or over time.

**Evaluation at scale is costly and slow.** Running evaluation on production logs requires sampling, rerunning models, and storing outputs. The compute and API cost of large-scale evals is high. Teams cannot iterate quickly on eval design because each run is expensive. Sampling strategies are ad hoc; coverage of edge cases and long-tail traffic is inconsistent.

**Labeling and ground truth are sparse.** Golden sets are small or outdated. Definitions of "correct" change as product requirements evolve. Human labels are expensive and may be inconsistent. Without reliable ground truth, teams cannot confidently compare model or prompt variants. Decisions about upgrades and rollbacks rest on limited data.

**Safety and compliance risks are hard to quantify.** Toxicity, PII leakage, jailbreaks, and harmful outputs are difficult to detect at scale. Compliance and audit requirements demand traceability of prompts, models, and outputs. Current practices do not support systematic checks or audit trails for these concerns.

---

**Impact.** These gaps slow release cycles, increase the risk of user-facing quality issues, and complicate decisions about model selection, prompt changes, and infrastructure spend. Rollbacks are reactive rather than data-driven. Cost and capacity planning remain approximate.
