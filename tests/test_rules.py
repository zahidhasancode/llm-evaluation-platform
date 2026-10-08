"""Rule-based evaluators: length, empty response, JSON / JSON schema."""

from __future__ import annotations

import pytest

from evaluation.base import EvaluationInput
from evaluation.rules import EmptyResponseEvaluator, JsonSchemaEvaluator, LengthEvaluator


def make_input(output: str | None) -> EvaluationInput:
    return EvaluationInput(input_text="prompt", output_text=output)  # type: ignore[arg-type]


# --- LengthEvaluator ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_outcome"),
    [
        ("abcd", "fail"),  # one below min
        ("abcde", "pass"),  # exactly min
        ("abcdefghij", "pass"),  # exactly max
        ("abcdefghijk", "fail"),  # one above max
    ],
)
def test_length_boundaries(text: str, expected_outcome: str) -> None:
    result = LengthEvaluator(min_length=5, max_length=10).evaluate(make_input(text))
    assert result.outcome == expected_outcome
    assert result.score == (1.0 if expected_outcome == "pass" else 0.0)
    assert result.details["length"] == len(text)


def test_length_strips_whitespace_before_measuring() -> None:
    result = LengthEvaluator(min_length=3).evaluate(make_input("  ab  "))
    assert result.outcome == "fail"
    assert result.details["length"] == 2
    assert "below min 3" in result.details["reason"]


def test_length_reports_above_max_reason() -> None:
    result = LengthEvaluator(max_length=2).evaluate(make_input("abc"))
    assert result.outcome == "fail"
    assert "above max 2" in result.details["reason"]


def test_length_without_bounds_always_passes() -> None:
    assert LengthEvaluator().evaluate(make_input("")).outcome == "pass"


def test_length_treats_none_output_as_empty() -> None:
    result = LengthEvaluator(min_length=1).evaluate(make_input(None))
    assert result.outcome == "fail"
    assert result.details["length"] == 0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_length": -1}, "min_length must be non-negative"),
        ({"max_length": -1}, "max_length must be non-negative"),
        ({"min_length": 5, "max_length": 4}, "must not exceed"),
    ],
)
def test_length_rejects_invalid_bounds(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        LengthEvaluator(**kwargs)


# --- EmptyResponseEvaluator --------------------------------------------------


def test_empty_detects_none() -> None:
    result = EmptyResponseEvaluator().evaluate(make_input(None))
    assert (result.score, result.outcome) == (0.0, "fail")
    assert result.details == {"empty": True, "reason": "output is None"}


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_detects_blank_strings(text: str) -> None:
    result = EmptyResponseEvaluator().evaluate(make_input(text))
    assert (result.score, result.outcome) == (0.0, "fail")
    assert result.details["original_length"] == len(text)


def test_empty_passes_non_empty_output() -> None:
    result = EmptyResponseEvaluator().evaluate(make_input("  hi "))
    assert (result.score, result.outcome) == (1.0, "pass")
    assert result.details["length"] == 2


def test_evaluator_name_defaults_to_class_name() -> None:
    assert EmptyResponseEvaluator().name == "EmptyResponseEvaluator"


# --- JsonSchemaEvaluator -----------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["answer"],
}


def test_json_valid_without_schema() -> None:
    result = JsonSchemaEvaluator().evaluate(make_input('{"a": 1}'))
    assert (result.score, result.outcome) == (1.0, "pass")
    assert result.details["schema_validated"] is False


def test_json_rejects_empty_output() -> None:
    result = JsonSchemaEvaluator().evaluate(make_input("   "))
    assert result.outcome == "fail"
    assert result.details["reason"] == "output is empty"


def test_json_reports_parse_position() -> None:
    result = JsonSchemaEvaluator().evaluate(make_input('{"a": }'))
    assert result.outcome == "fail"
    assert result.details["reason"].startswith("invalid JSON")
    assert result.details["line"] == 1
    assert result.details["column"] == 7


def test_json_schema_pass() -> None:
    result = JsonSchemaEvaluator(SCHEMA).evaluate(make_input('{"answer": "yes", "confidence": 0.9}'))
    assert (result.score, result.outcome) == (1.0, "pass")
    assert result.details["schema_validated"] is True


def test_json_schema_rejects_valid_json_that_breaks_schema() -> None:
    result = JsonSchemaEvaluator(SCHEMA).evaluate(make_input('{"answer": "yes", "confidence": "high"}'))
    assert (result.score, result.outcome) == (0.0, "fail")
    assert result.details["path"] == ["confidence"]


def test_json_schema_missing_required_field() -> None:
    result = JsonSchemaEvaluator(SCHEMA).evaluate(make_input("{}"))
    assert result.outcome == "fail"
    assert "'answer' is a required property" in result.details["reason"]


def test_json_schema_invalid_schema_raises() -> None:
    with pytest.raises(ValueError, match="Invalid JSON schema"):
        JsonSchemaEvaluator({"type": "not-a-type"})


@pytest.mark.parametrize(
    "evaluator",
    [LengthEvaluator(1, 3), EmptyResponseEvaluator(), JsonSchemaEvaluator(), JsonSchemaEvaluator(SCHEMA)],
)
@pytest.mark.parametrize("output", [None, "", "x", '{"answer": "a"}', "not json"])
def test_results_always_carry_score_or_outcome(evaluator, output) -> None:
    result = evaluator.evaluate(make_input(output))
    assert result.score is not None or result.outcome is not None
