"""
Rule-based evaluators for LLM Evaluation & Monitoring Platform.
Deterministic, no external calls.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .base import EvaluationInput, EvaluationResult, Evaluator


def _safe_output(inp: EvaluationInput) -> str:
    """Return output_text, treating None as empty string."""
    out = inp.output_text
    return "" if out is None else str(out).strip()


class LengthEvaluator(Evaluator):
    """
    Validates response length against min and max bounds.
    Score 1.0 if within range, 0.0 otherwise.
    """

    def __init__(
        self,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
    ) -> None:
        if min_length is not None and min_length < 0:
            raise ValueError("min_length must be non-negative")
        if max_length is not None and max_length < 0:
            raise ValueError("max_length must be non-negative")
        if min_length is not None and max_length is not None and min_length > max_length:
            raise ValueError("min_length must not exceed max_length")
        self._min_length = min_length
        self._max_length = max_length

    def evaluate(self, inp: EvaluationInput) -> EvaluationResult:
        output = _safe_output(inp)
        length = len(output)

        if self._min_length is not None and length < self._min_length:
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "length": length,
                    "min_length": self._min_length,
                    "max_length": self._max_length,
                    "reason": f"length {length} below min {self._min_length}",
                },
            )
        if self._max_length is not None and length > self._max_length:
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "length": length,
                    "min_length": self._min_length,
                    "max_length": self._max_length,
                    "reason": f"length {length} above max {self._max_length}",
                },
            )

        return EvaluationResult(
            score=1.0,
            outcome="pass",
            details={
                "length": length,
                "min_length": self._min_length,
                "max_length": self._max_length,
                "reason": "length within bounds",
            },
        )


class EmptyResponseEvaluator(Evaluator):
    """
    Detects empty or null-like responses.
    Score 1.0 if non-empty, 0.0 if empty or whitespace-only.
    """

    def evaluate(self, inp: EvaluationInput) -> EvaluationResult:
        output = inp.output_text
        if output is None:
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={"empty": True, "reason": "output is None"},
            )

        stripped = str(output).strip()
        if stripped == "":
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "empty": True,
                    "reason": "output is empty or whitespace-only",
                    "original_length": len(output),
                },
            )

        return EvaluationResult(
            score=1.0,
            outcome="pass",
            details={
                "empty": False,
                "reason": "output is non-empty",
                "length": len(stripped),
            },
        )


class JsonSchemaEvaluator(Evaluator):
    """
    Validates that output is parseable JSON and, when a schema is provided,
    conforms to that schema. Score 1.0 if valid, 0.0 otherwise.
    """

    def __init__(self, schema: Optional[dict[str, Any]] = None) -> None:
        self._schema = schema
        if schema is not None:
            try:
                import jsonschema
            except ImportError:
                raise ImportError(
                    "jsonschema is required for schema validation. "
                    "Install with: pip install jsonschema"
                )
            try:
                jsonschema.Draft7Validator.check_schema(schema)
            except jsonschema.SchemaError as e:
                raise ValueError(f"Invalid JSON schema: {e}") from e

    def evaluate(self, inp: EvaluationInput) -> EvaluationResult:
        output = _safe_output(inp)

        if output == "":
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "valid": False,
                    "reason": "output is empty",
                    "schema_validated": self._schema is not None,
                },
            )

        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as e:
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "valid": False,
                    "reason": f"invalid JSON: {e.msg}",
                    "position": e.pos,
                    "line": e.lineno,
                    "column": e.colno,
                    "schema_validated": False,
                },
            )

        if self._schema is None:
            return EvaluationResult(
                score=1.0,
                outcome="pass",
                details={
                    "valid": True,
                    "reason": "valid JSON",
                    "schema_validated": False,
                },
            )

        try:
            import jsonschema
            from jsonschema import ValidationError

            jsonschema.validate(parsed, self._schema)
            return EvaluationResult(
                score=1.0,
                outcome="pass",
                details={
                    "valid": True,
                    "reason": "valid JSON and conforms to schema",
                    "schema_validated": True,
                },
            )
        except ValidationError as e:
            path = list(e.absolute_path) if hasattr(e, "absolute_path") else []
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "valid": False,
                    "reason": str(e),
                    "path": path,
                    "schema_validated": True,
                },
            )
        except Exception as e:
            return EvaluationResult(
                score=0.0,
                outcome="fail",
                details={
                    "valid": False,
                    "reason": str(e),
                    "schema_validated": True,
                },
            )
