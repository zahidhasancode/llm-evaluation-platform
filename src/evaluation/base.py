"""
Base evaluation interface for LLM Evaluation & Monitoring Platform.
Defines the contract for evaluators; no implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class EvaluationInput:
    """
    Input to an evaluator: LLM output plus context and metadata.

    Attributes:
        input_text: The prompt or input sent to the model.
        output_text: The model response to evaluate.
        expected_output: Optional reference answer for reference-based evaluation.
        metadata: Optional context (prompt_name, prompt_version, model_name, etc.).
    """

    input_text: str
    output_text: str
    expected_output: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class EvaluationResult:
    """
    Output of an evaluator: score, outcome, and optional details.

    Contract: at least one of score or outcome must be set.
    """

    score: Optional[float] = None
    outcome: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class Evaluator(ABC):
    """
    Abstract base for evaluators. Rule-based and LLM-based evaluators
    implement this interface.
    """

    @property
    def name(self) -> str:
        """Identifier for this evaluator (e.g. criterion name)."""
        return self.__class__.__name__

    @abstractmethod
    def evaluate(self, inp: EvaluationInput) -> EvaluationResult:
        """
        Evaluate the model output.

        Args:
            inp: Evaluation input (prompt, output, optional reference, metadata).

        Returns:
            Evaluation result with score and/or outcome, and optional details.
        """
        ...
