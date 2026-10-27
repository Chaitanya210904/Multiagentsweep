"""
Data models for the Impact Analyzer Agent (Layer: Understanding).
Defines blast radius metrics, affected entities, propagation paths, and wake directives.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from models.registry import NodeType, RegistryNode


class ImpactSeverity(str, Enum):
    """Categorical classification of change blast radius."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TraversalStep(BaseModel):
    """A single hop in a dependency propagation chain."""
    source_id: str
    target_id: str
    edge_type: str
    direction: str = Field(description="'upstream' or 'downstream'")
    depth: int


class PropagationPath(BaseModel):
    """A complete path from a root changed node to an affected leaf node."""
    root_node_id: str
    leaf_node_id: str
    length: int
    steps: List[TraversalStep] = Field(default_factory=list)


class AffectedEntities(BaseModel):
    """Comprehensive categorization of all entities affected by a change."""
    changed_roots: List[str] = Field(description="Root changed nodes where analysis began")
    all_affected_node_ids: List[str] = Field(description="All distinct impacted node IDs")
    callers: List[str] = Field(default_factory=list, description="Direct and transitive upstream callers")
    callees: List[str] = Field(default_factory=list, description="Direct and transitive downstream callees")
    affected_apis: List[str] = Field(default_factory=list, description="Affected API endpoint nodes")
    affected_tables: List[str] = Field(default_factory=list, description="Affected database table nodes")
    affected_services: List[str] = Field(default_factory=list, description="Affected external microservices/queues")
    tests_to_run: List[str] = Field(default_factory=list, description="Test suites/functions that cover affected code")
    untested_nodes: List[str] = Field(default_factory=list, description="Affected nodes that lack test coverage")
    max_propagation_depth: int = Field(default=0, description="Deepest dependency chain discovered")
    paths: List[PropagationPath] = Field(default_factory=list, description="Representative traversal paths")


class WakeDirective(BaseModel):
    """Directive instructing an agent to wake up with specific task parameters."""
    agent_id: str
    layer: str
    priority: str = Field(description="'high', 'medium', or 'low'")
    reason: str = Field(description="Rationale explaining why this agent was selected to wake")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Targeted inputs for the awakened agent")


class ImpactAnalyzerInput(BaseModel):
    """Input payload accepted by the Impact Analyzer Agent."""
    changed_nodes: List[Union[str, RegistryNode]] = Field(
        description="List of node IDs or RegistryNodes that were added, modified, or deleted",
    )
    max_depth: int = Field(default=6, ge=1, le=20, description="Maximum traversal depth for blast radius exploration")
    edge_types: Optional[List[str]] = Field(
        default=None,
        description="Filter specific edge types to follow (defaults to all)",
    )
    include_paths: bool = Field(default=True, description="Whether to include full propagation paths")


class ImpactAnalyzerOutput(BaseModel):
    """Output payload produced by the Impact Analyzer Agent."""
    blast_radius_score: float = Field(
        ge=0.0,
        le=100.0,
        description="Numerical impact score from 0.0 (minimal) to 100.0 (catastrophic)",
    )
    severity: ImpactSeverity = Field(description="Severity tier: low, medium, high, critical")
    affected_nodes_and_services: AffectedEntities = Field(
        description="Detailed breakdown of affected callers, callees, APIs, tables, and services",
    )
    agents_to_wake: List[WakeDirective] = Field(
        description="List of targeted agents to awaken based on the blast radius profile",
    )
    stats: Dict[str, Any] = Field(default_factory=dict, description="Analysis metrics and timing")
