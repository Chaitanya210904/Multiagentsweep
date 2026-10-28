"""
Control Layer:
- Orchestrator Agent (Master Coordinator & Planner)
- Result Aggregator & Critic Agent (Consolidator & Quality Gate)
"""

from .orchestrator import (
    ORCHESTRATOR_METADATA,
    OrchestratorAgent,
    Orchestrator,
)
from .critic import (
    CRITIC_METADATA,
    ResultAggregatorCriticAgent,
    ResultAggregatorCritic,
)

__all__ = [
    "ORCHESTRATOR_METADATA",
    "OrchestratorAgent",
    "Orchestrator",
    "CRITIC_METADATA",
    "ResultAggregatorCriticAgent",
    "ResultAggregatorCritic",
]
