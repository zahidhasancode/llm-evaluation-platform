"""LLM-as-judge evaluator with a fake client (no network, no API keys)."""

from __future__ import annotations

import json

import pytest

from evaluation.base import EvaluationInput
from evaluation.llm_judge import LLMJudgeEvaluator


class FakeClient:
    """Stands in for a real LLM client; records calls and returns a canned reply."""

    def __init__(self, reply: str = "", input_tokens: int = 0, output_tokens: int = 0,
                 error: Exception | None = None) -> None:
        self.reply = reply
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.error = error
        self.calls: list[dict] = []

    def complete(self, prompt: str, *, temperature: float = 0, max_tokens: int = 500):
        self.calls.append({"prompt": prompt, "temperature": temperature, "max_tokens": max_tokens})
        if self.error is not None:
            raise self.error
        return self.reply, self.input_tokens, self.output_tokens


def rubric(relevance=5, completeness=4, format_adherence=3) -> str:
    return json.dumps(
        {
            "relevance": {"score": relevance, "explanation": "on topic"},
            "completeness": {"score": completeness, "explanation": "mostly complete"},
            "format_adherence": {"score": format_adherence, "explanation": "ok"},
        }
    )


INPUT = EvaluationInput(input_text="Summarise the report", output_text="The report says X.")


def test_valid_judgement_is_averaged_and_costed() -> None:
    client = FakeClient(rubric(5, 4, 3), input_tokens=1000, output_tokens=500)
    judge = LLMJudgeEvaluator(
        client, input_cost_per_1k=0.01, output_cost_per_1k=0.03, max_tokens=256
    )

    result = judge.evaluate(INPUT)

    assert result.outcome == "pass"
    assert result.score == pytest.approx(4.0)
    assert result.details["criteria"]["relevance"] == {"score": 5, "explanation": "on topic"}
    assert result.details["input_tokens"] == 1000
    assert result.details["output_tokens"] == 500
    # 1000/1000 * 0.01 + 500/1000 * 0.03 = 0.025
    assert result.details["estimated_cost_usd"] == "0.02500000"


def test_judge_is_called_deterministically_with_both_texts() -> None:
    client = FakeClient(rubric())
    LLMJudgeEvaluator(client, max_tokens=256).evaluate(INPUT)

    (call,) = client.calls
    assert call["temperature"] == 0
    assert call["max_tokens"] == 256
    assert "Summarise the report" in call["prompt"]
    assert "The report says X." in call["prompt"]


def test_braces_in_texts_do_not_break_prompt_formatting() -> None:
    client = FakeClient(rubric())
    inp = EvaluationInput(input_text="Return {json}", output_text='{"a": 1}')
    assert LLMJudgeEvaluator(client).evaluate(inp).outcome == "pass"
    assert '{"a": 1}' in client.calls[0]["prompt"]


def test_markdown_fenced_json_is_accepted() -> None:
    client = FakeClient("```json\n" + rubric(4, 4, 4) + "\n```")
    result = LLMJudgeEvaluator(client).evaluate(INPUT)
    assert result.outcome == "pass"
    assert result.score == pytest.approx(4.0)


def test_non_json_reply_is_parse_failure() -> None:
    client = FakeClient("I think it is good.", input_tokens=10, output_tokens=5)
    result = LLMJudgeEvaluator(client).evaluate(INPUT)
    assert (result.score, result.outcome) == (0.0, "fail")
    assert result.details["error"] == "parse_failed"
    assert result.details["raw_preview"] == "I think it is good."
    assert result.details["input_tokens"] == 10


@pytest.mark.parametrize(
    "reply",
    [
        rubric(relevance=6),  # out of range
        rubric(completeness=-1),  # out of range
        json.dumps({"relevance": {"score": 5}, "completeness": {"score": 5}}),  # missing criterion
        json.dumps({"relevance": 5, "completeness": 5, "format_adherence": 5}),  # wrong shape
    ],
)
def test_schema_violations_are_reported(reply: str) -> None:
    result = LLMJudgeEvaluator(FakeClient(reply)).evaluate(INPUT)
    assert (result.score, result.outcome) == (0.0, "fail")
    assert result.details["error"] == "invalid_schema"


def test_client_exception_is_captured() -> None:
    client = FakeClient(error=TimeoutError("judge timed out"))
    result = LLMJudgeEvaluator(client).evaluate(INPUT)
    assert (result.score, result.outcome) == (0.0, "fail")
    assert result.details["error"] == "llm_call_failed"
    assert result.details["message"] == "judge timed out"
    assert result.details["estimated_cost_usd"] == "0.00000000"


def test_explanations_are_truncated() -> None:
    reply = json.dumps(
        {
            "relevance": {"score": 5, "explanation": "x" * 500},
            "completeness": {"score": 5, "explanation": ""},
            "format_adherence": {"score": 5, "explanation": ""},
        }
    )
    result = LLMJudgeEvaluator(FakeClient(reply)).evaluate(INPUT)
    assert len(result.details["criteria"]["relevance"]["explanation"]) == 200


@pytest.mark.parametrize("na_score", ["N/A", "n/a", None])
def test_format_adherence_not_applicable_is_left_out_of_average(na_score) -> None:
    # The rubric tells the judge to answer N/A when the input asks for no format.
    reply = json.dumps(
        {
            "relevance": {"score": 5, "explanation": "on topic"},
            "completeness": {"score": 3, "explanation": "partial"},
            "format_adherence": {"score": na_score, "explanation": "N/A"},
        }
    )
    result = LLMJudgeEvaluator(FakeClient(reply)).evaluate(INPUT)
    assert result.outcome == "pass"
    assert result.score == pytest.approx(4.0)
    assert result.details["criteria"]["format_adherence"]["score"] is None


@pytest.mark.parametrize("criterion", ["relevance", "completeness"])
def test_only_format_adherence_may_be_not_applicable(criterion: str) -> None:
    data = json.loads(rubric())
    data[criterion]["score"] = "N/A"
    result = LLMJudgeEvaluator(FakeClient(json.dumps(data))).evaluate(INPUT)
    assert result.details["error"] == "invalid_schema"


def test_boolean_scores_are_rejected() -> None:
    data = json.loads(rubric())
    data["relevance"]["score"] = True
    result = LLMJudgeEvaluator(FakeClient(json.dumps(data))).evaluate(INPUT)
    assert result.details["error"] == "invalid_schema"
