"""
Data models for the Architecture Review Agent (Layer: Quality).
Defines architectural violations, package coupling metrics, and Architecture Decision Records (ADRs).
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from models.registry import RegistryNode


class ArchitectureViolationType(str, Enum):
    """Categorical classification of architectural anti-patterns and rule violations."""
    LAYER_INVERSION = "layer_inversion"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    SERVICE_BOUNDARY_LEAK = "service_boundary_leak"
    EXCESSIVE_COUPLING = "excessive_coupling"
    FORBIDDEN_DEPENDENCY = "forbidden_dependency"


class ViolationSeverity(str, Enum):
    """Severity classification for architectural violations."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ArchitecturalViolation(BaseModel):
    """A detected breach of architectural rules, layer boundaries, or coupling limits."""
    id: str = Field(description="Unique violation identifier")
    type: ArchitectureViolationType
    severity: ViolationSeverity
    source_node_id: str = Field(description="Node originating the invalid dependency")
    target_node_id: Optional[str] = Field(default=None, description="Target node being accessed")
    rule_name: str = Field(description="Name of the architectural rule that was violated")
    message: str = Field(description="Detailed explanation of the architectural violation")
    cycle_path: Optional[List[str]] = Field(default=None, description="Dependency cycle chain if circular dependency")
    remediation: str = Field(description="Actionable guidance on how to refactor and resolve this violation")


class CouplingMetric(BaseModel):
    """
    Robert C. Martin's Package Coupling Metrics.
    - Afferent Coupling (Ca): Number of external entities that depend on this entity (incoming callers).
    - Efferent Coupling (Ce): Number of external entities this entity depends on (outgoing dependencies).
    - Instability (I): Ce / (Ca + Ce). Range [0.0 (maximally stable) to 1.0 (maximally unstable)].
    """
    entity_id: str = Field(description="File, class, or module identifier")
    afferent_coupling: int = Field(ge=0, description="Incoming dependencies (Ca)")
    efferent_coupling: int = Field(ge=0, description="Outgoing dependencies (Ce)")
    instability: float = Field(ge=0.0, le=1.0, description="Instability metric I = Ce / (Ca + Ce)")
    is_hotspot: bool = Field(default=False, description="True if coupling exceeds safety thresholds")
    risk_level: str = Field(default="low", description="'low', 'medium', or 'high'")


class ADRStatus(str, Enum):
    """Status lifecycle of an Architecture Decision Record."""
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


class ADRRecord(BaseModel):
    """
    Architecture Decision Record (ADR) following Michael Nygard's standard template:
    Title, Status, Context, Decision, Consequences, Affected Nodes.
    """
    id: str = Field(description="Canonical ADR ID, e.g. 'ADR-001'")
    title: str = Field(description="Concise description of the architectural decision")
    status: ADRStatus = Field(default=ADRStatus.PROPOSED)
    date: str = Field(description="ISO-8601 date of the decision")
    context: str = Field(description="The architectural problem, forces, and context prompting this decision")
    decision: str = Field(description="The change or rule being established")
    consequences: List[str] = Field(default_factory=list, description="Positive and negative trade-offs")
    affected_nodes: List[str] = Field(default_factory=list, description="Registry node IDs subject to this decision")
    source_path: Optional[str] = Field(default=None, description="Path to file where ADR is stored, if on disk")


class ArchitectureReviewInput(BaseModel):
    """Input payload accepted by the Architecture Review Agent."""
    graph_slice: Optional[List[Union[str, RegistryNode]]] = Field(
        default=None,
        description="List of node IDs or RegistryNodes in scope. If None or empty, reviews entire active graph.",
    )
    existing_adrs: List[Union[str, Path, ADRRecord, Dict[str, Any]]] = Field(
        default_factory=list,
        description="Existing ADR objects, markdown file paths, or directory containing ADRs.",
    )
    layer_hierarchy: Optional[List[str]] = Field(
        default=None,
        description="Ordered list of layer names from low-level to high-level. Lower layers cannot depend on higher layers.",
    )
    max_coupling_threshold: int = Field(
        default=15,
        ge=1,
        description="Efferent coupling threshold (Ce) above which an entity is flagged as a coupling hotspot.",
    )
    check_cycles: bool = Field(
        default=True,
        description="Whether to perform cycle detection algorithms on dependencies.",
    )


class ArchitectureReviewOutput(BaseModel):
    """Output payload produced by the Architecture Review Agent."""
    violations: List[ArchitecturalViolation] = Field(
        default_factory=list,
        description="All detected layer inversions, circular dependencies, boundary leaks, and excessive coupling.",
    )
    coupling_metrics: List[CouplingMetric] = Field(
        default_factory=list,
        description="Coupling and instability metrics computed across the graph slice.",
    )
    draft_adrs: List[ADRRecord] = Field(
        default_factory=list,
        description="Generated Architecture Decision Records addressing observed anti-patterns or structural changes.",
    )
    clean_architecture_score: float = Field(
        ge=0.0,
        le=100.0,
        description="Architectural health score from 0.0 (severe degradation) to 100.0 (pristine decoupling).",
    )
    summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Summary statistics of the architecture review.",
    )
