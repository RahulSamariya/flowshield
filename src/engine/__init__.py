"""FlowShield engine package."""

from src.engine.engine import SituationEngine
from src.engine.history import EngineRecord, HistoryStore
from src.engine.normalizer import EventNormalizer, NormalizationError
from src.engine.optimizer import GreedyResourceOptimizer, ResourceOptimizer
from src.engine.optimizer_request import (
    DEFAULT_CAPABILITIES,
    OptimizationRequest,
    ResourceCapability,
)
from src.engine.optimizer_result import (
    Assignment,
    OptimizationResult,
    UnassignedIncident,
)
from src.engine.priority_config import DEFAULT_CONFIG, PriorityConfig
from src.engine.priority_context import IncidentContext
from src.engine.priority_engine import IncidentPriorityEngine
from src.engine.priority_result import FactorScore, PriorityLevel, PriorityResult

__all__ = [
    "SituationEngine",
    "EngineRecord",
    "HistoryStore",
    "EventNormalizer",
    "NormalizationError",
    # optimizer
    "ResourceOptimizer",
    "GreedyResourceOptimizer",
    "OptimizationRequest",
    "OptimizationResult",
    "ResourceCapability",
    "DEFAULT_CAPABILITIES",
    "Assignment",
    "UnassignedIncident",
    # priority
    "PriorityConfig",
    "DEFAULT_CONFIG",
    "IncidentContext",
    "IncidentPriorityEngine",
    "PriorityLevel",
    "PriorityResult",
    "FactorScore",
]
