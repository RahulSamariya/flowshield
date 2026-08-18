"""ReasoningResult — the typed output of every GraniteReasoningLayer method.

A ReasoningResult always contains:
- ``text``       Human-readable explanation for operators.
- ``structured`` Parsed JSON dict extracted from the response (may be empty).
- ``source``     "granite" if produced by the LLM, "fallback" if deterministic.
- ``task``       Which reasoning task produced this result.

The ``source`` field is critical for auditability: operators can always see
whether an explanation came from Granite or from the deterministic fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ReasoningTask(StrEnum):
    """Identifies which task a ReasoningResult came from."""

    SITUATION_SUMMARY     = "situation_summary"
    PRIORITY_EXPLANATION  = "priority_explanation"
    ASSIGNMENT_EXPLANATION = "assignment_explanation"
    RESPONSE_PLAN         = "response_plan"
    MISSING_INFORMATION   = "missing_information"


class ReasoningSource(StrEnum):
    """Indicates whether the result came from Granite or the fallback."""

    GRANITE  = "granite"
    FALLBACK = "fallback"


@dataclass
class ReasoningResult:
    """The output of one GraniteReasoningLayer call.

    Attributes
    ----------
    task
        Which reasoning task this result answers.
    source
        "granite" = produced by IBM Granite.
        "fallback" = produced deterministically (Granite unavailable).
    text
        Human-readable explanation suitable for operator display.
    structured
        Parsed JSON extracted from the LLM response.
        Empty dict if parsing failed or the task returns plain text only.
    warnings
        Non-fatal issues noticed during reasoning (e.g. missing data fields).
    """

    task: ReasoningTask
    source: ReasoningSource
    text: str
    structured: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
