"""PolicyConfig — municipal response policy rules for the ResponsePlanningAgent.

Encodes the human-authored rules that the planner must follow.
All values are configurable; the DEFAULT_POLICY covers a typical Gujarat
urban-flood scenario.

Approval rules
--------------
Actions above ``approval_required_above_priority_score`` are flagged
PENDING_APPROVAL.  The threshold is in the same [0, 1] space as
PriorityResult.score so both systems share units.

``approval_required_for_types`` is a set of resource type strings that
always need human sign-off regardless of score (e.g. "rescue_team" when
mass evacuation is implied).

Response time targets (minutes)
--------------------------------
Keyed by PriorityLevel string: "critical", "high", "medium", "low".
Used to populate the ``target_response_minutes`` field in each PlanAction.

Responsible unit mapping
------------------------
``unit_for_resource_type`` maps ResourceType string → unit name string.
The agent looks up the resource's type and fills in the responsible unit.
If the resource type is not in the map the fallback is "Municipal EOC".
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PolicyConfig:
    """Immutable municipal response policy.

    Parameters
    ----------
    response_time_targets
        Dict mapping priority level → target response minutes.
        All four levels (critical, high, medium, low) should be present.
    unit_for_resource_type
        Dict mapping ResourceType string → responsible unit name.
    approval_required_above_priority_score
        PlanActions whose PriorityResult.score exceeds this threshold are
        flagged ``ApprovalState.REQUIRED``.  Set to 1.0 to disable.
    approval_required_for_resource_types
        Resource type strings that always require approval regardless of score.
    max_actions_per_incident
        Hard upper limit on proposed actions per incident.
        The agent emits a warning if the optimizer already respected this,
        but enforces it as a cap when building the plan.
    """

    response_time_targets: dict[str, int] = field(
        default_factory=lambda: {
            "critical": 15,
            "high":     30,
            "medium":   60,
            "low":     120,
        }
    )
    unit_for_resource_type: dict[str, str] = field(
        default_factory=lambda: {
            "pump":         "AMC Drainage Department",
            "rescue_team":  "NDRF / State SDRF",
            "vehicle":      "AMC Transport Wing",
            "shelter":      "Revenue Department",
            "medical":      "EMRI / Civil Hospital",
            "other":        "Municipal EOC",
        }
    )
    approval_required_above_priority_score: float = 0.75
    approval_required_for_resource_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"rescue_team"})
    )
    max_actions_per_incident: int = 3

    def target_minutes(self, priority_level: str) -> int:
        """Return target response minutes for a PriorityLevel string."""
        return self.response_time_targets.get(priority_level.lower(), 60)

    def responsible_unit(self, resource_type: str) -> str:
        """Return the responsible municipal unit for a resource type string."""
        return self.unit_for_resource_type.get(resource_type.lower(), "Municipal EOC")

    def requires_approval(self, priority_score: float, resource_type: str) -> bool:
        """Return True if human approval is required for this action."""
        if resource_type.lower() in self.approval_required_for_resource_types:
            return True
        return priority_score > self.approval_required_above_priority_score


#: Default policy — suitable for Ahmedabad / Surat urban flood response.
DEFAULT_POLICY = PolicyConfig()
