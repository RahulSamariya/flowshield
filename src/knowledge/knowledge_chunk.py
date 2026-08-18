"""KnowledgeChunk — the atomic unit of the FlowShield knowledge base.

A chunk is a single, self-contained policy or procedure fragment.
Chunks are immutable; the knowledge base is built from a fixed corpus.

Design constraints
------------------
- Chunks contain ONLY policy/procedure/SOP text.
- Chunks MUST NOT contain live numeric sensor data, resource availability,
  or real-time incident information.  Those live in the engine models.
- Every chunk carries a ``source_ref`` so citations can be generated.
- ``tags`` drive keyword retrieval when the chunk title/text alone is ambiguous.

KnowledgeCategory vocabulary
-----------------------------
SOP                 Standard operating procedure for a specific incident type
DRAINAGE            Drainage infrastructure maintenance and dewatering guidance
ESCALATION          Rules for escalating to higher authority or mutual aid
APPROVAL_POLICY     Human-approval requirements and sign-off thresholds
COMMUNICATION       Public/inter-agency communication templates
SAFETY              Responder safety rules and no-go conditions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class KnowledgeCategory(StrEnum):
    """Controlled vocabulary for chunk categories."""

    SOP              = "sop"
    DRAINAGE         = "drainage"
    ESCALATION       = "escalation"
    APPROVAL_POLICY  = "approval_policy"
    COMMUNICATION    = "communication"
    SAFETY           = "safety"


@dataclass(frozen=True)
class KnowledgeChunk:
    """A single policy/procedure fragment in the knowledge base.

    Attributes
    ----------
    id
        Stable, unique identifier (slug).  Never reassigned.
    category
        ``KnowledgeCategory`` — used for filtered retrieval.
    title
        Short human-readable label, shown in citations.
    text
        Full policy/procedure text.  Plain prose — no JSON, no tables.
    tags
        Extra keyword hints that improve retrieval coverage.
        Use for synonyms, acronyms, and alternate phrasings.
    source_ref
        Formal reference: document name + section, e.g.
        "AMC Flood SOP 2023, Section 4.2".  Shown verbatim in citations.

    Example::

        chunk = KnowledgeChunk(
            id="sop-waterlogging-response",
            category=KnowledgeCategory.SOP,
            title="Waterlogging First Response SOP",
            text="On detection of waterlogging above 0.3 m...",
            tags=["waterlogging", "dewatering", "pump deployment"],
            source_ref="AMC Flood SOP 2023, Sec 3.1",
        )
    """

    id: str
    category: KnowledgeCategory
    title: str
    text: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    source_ref: str = ""
