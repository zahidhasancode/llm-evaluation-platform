"""
LLM-as-judge evaluator for LLM Evaluation & Monitoring Platform.
Uses a strict prompt and rubric to score relevance, completeness, format adherence.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Protocol

from .base import EvaluationInput, EvaluationResult, Evaluator


class LLMClientProtocol(Protocol):
    """Protocol for LLM completion. Implementer provides the actual API call."""

    def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0,
        max_tokens: int = 500,
    ) -> tuple[str, int, int]:
        """
        Run completion. Returns (response_text, input_tokens, output_tokens).
        Raises on API or network failure.
        """
        ...


JUDGE_PROMPT = """You are an evaluator. Score the model's response against the input.

## Input (user prompt)
{input_text}

## Model response
{output_text}

## Rubric
Score each criterion 0-5. Provide a short, factual explanation.

- **Relevance** (0-5): Does the response address the input? 0=off-topic, 5=fully relevant.
- **Completeness** (0-5): Does the response answer the full request? 0=empty/missing, 5=complete.
- **Format adherence** (0-5): Does the response follow required format if specified? 0=wrong format, 5=correct, N/A if no format specified.

## Output format
Return only valid JSON, no other text:

{{
  "relevance": {{"score": <0-5>, "explanation": "<one sentence>"}},
  "completeness": {{"score": <0-5>, "explanation": "<one sentence>"}},
  "format_adherence": {{"score": <0-5>, "explanation": "<one sentence or N/A>"}}
}}
"""


def _build_prompt(inp: EvaluationInput) -> str:
    input_text = inp.input_text or ""
    output_text = inp.output_text or ""
    return JUDGE_PROMPT.format(input_text=input_text, output_text=output_text)


def _parse_response(text: str) -> Optional[dict[str, Any]]:
    """Parse JSON from response. Returns None on failure."""
    text = text.strip()
    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_per_1k: float,
    output_per_1k: float,
) -> str:
    cost = (input_tokens / 1000.0) * input_per_1k + (output_tokens / 1000.0) * output_per_1k
    return f"{cost:.8f}"


_OPTIONAL_CRITERIA = frozenset({"format_adherence"})


def _is_not_applicable(score: Any) -> bool:
    return score is None or (isinstance(score, str) and score.strip().upper() == "N/A")


def _validate_scores(data: dict[str, Any]) -> Optional[tuple[float, dict[str, Any]]]:
    """
    Validate parsed data and extract scores. Returns (overall_score, details) or None.
    Overall score is average of criteria (0-5 scale).

    The rubric allows format_adherence to be N/A when the input specifies no
    format. A score of "N/A" or null for that criterion is recorded as None and
    left out of the average.
    """
    criteria = ("relevance", "completeness", "format_adherence")
    scores = []
    details: dict[str, Any] = {}

    for c in criteria:
        val = data.get(c)
        if not isinstance(val, dict):
            return None
        s = val.get("score")
        exp = val.get("explanation", "")
        if c in _OPTIONAL_CRITERIA and _is_not_applicable(s):
            details[c] = {"score": None, "explanation": str(exp)[:200]}
            continue
        # bool is a subclass of int; true/false is not a rubric score.
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not (0 <= s <= 5):
            return None
        scores.append(float(s))
        details[c] = {"score": s, "explanation": str(exp)[:200]}

    overall = sum(scores) / len(scores)
    return (overall, details)


class LLMJudgeEvaluator(Evaluator):
    """
    LLM-as-judge evaluator. Scores relevance, completeness, format adherence.
    Uses temperature=0 for determinism. Tracks token usage and estimated cost.
    """

    def __init__(
        self,
        client: LLMClientProtocol,
        *,
        input_cost_per_1k: float = 0.0,
        output_cost_per_1k: float = 0.0,
        max_tokens: int = 500,
    ) -> None:
        self._client = client
        self._input_cost_per_1k = input_cost_per_1k
        self._output_cost_per_1k = output_cost_per_1k
        self._max_tokens = max_tokens

    def evaluate(self, inp: EvaluationInput) -> EvaluationResult:
        prompt = _build_prompt(inp)

        try:
            response_text, input_tokens, output_tokens = self._client.complete(
                prompt,
                temperature=0,
                max_tokens=self._max_tokens,
            )
        except Exception as e:
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "error": "llm_call_failed",
                    "message": str(e),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost_usd": "0.00000000",
                },
            )

        parsed = _parse_response(response_text)
        if parsed is None:
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "error": "parse_failed",
                    "message": "Judge response was not valid JSON",
                    "raw_preview": response_text[:500] if response_text else "",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "estimated_cost_usd": _estimate_cost(
                        input_tokens, output_tokens,
                        self._input_cost_per_1k, self._output_cost_per_1k,
                    ),
                },
            )

        validated = _validate_scores(parsed)
        if validated is None:
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "error": "invalid_schema",
                    "message": "Judge response did not match expected rubric schema",
                    "parsed": parsed,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "estimated_cost_usd": _estimate_cost(
                        input_tokens, output_tokens,
                        self._input_cost_per_1k, self._output_cost_per_1k,
                    ),
                },
            )

        overall_score, criterion_details = validated

        return EvaluationResult(
            score=overall_score,
            outcome="pass",
            details={
                "criteria": criterion_details,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_usd": _estimate_cost(
                    input_tokens, output_tokens,
                    self._input_cost_per_1k, self._output_cost_per_1k,
                ),
            },
        )
