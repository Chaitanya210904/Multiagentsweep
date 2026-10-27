"""
Data models for the Relationship Linker Agent (Layer: Graph).
Defines code edge types, verified edges, unresolved link queue entries, and linker payloads.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from models.registry import RegistryNode, UpdateProposal


class EdgeType(str, Enum):
    """Categorization of code relationships."""
    CALLS = "calls"
    IMPORTS = "imports"
    INHERITANCE = "inheritance"
    TEST_TO_CODE = "test_to_code"


class CodeEdge(BaseModel):
    """
    Represents a verified relationship edge between two nodes that both exist in the Code Registry.
    """
    id: str = Field(description="Unique edge identifier, e.g. 'edge:calls:func:A->func:B'")
    source_id: str = Field(description="Canonical ID of the originating node in the registry")
    target_id: str = Field(description="Canonical ID of the destination node in the registry")
    type: EdgeType = Field(description="Type of code relationship: calls, imports, inheritance, test_to_code")
    line_number: Optional[int] = Field(default=None, description="Line number where relationship occurs")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Verification confidence score")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Detailed relationship context")

    @classmethod
    def create(
        cls,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        line_number: Optional[int] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "CodeEdge":
        edge_id = f"edge:{edge_type.value}:{source_id}->{target_id}"
        return cls(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            type=edge_type,
            line_number=line_number,
            confidence=confidence,
            metadata=metadata or {},
        )


class UnresolvedLink(BaseModel):
    """
    Represents a potential link whose endpoint(s) could not be verified in the registry.
    As per architecture specifications: missing endpoints go to the unresolved queue, never guessed.
    """
    link_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: Optional[str] = Field(default=None, description="Source node ID if found")
    source_path: str = Field(description="File path where reference was detected")
    raw_target: str = Field(description="Unresolved raw target symbol, import string, or identifier")
    edge_type: EdgeType = Field(description="Intended relationship type")
    line_number: Optional[int] = Field(default=None, description="Line number where reference occurs")
    reason: str = Field(description="Explicit explanation why endpoint could not be verified")
    candidate_matches: List[str] = Field(
        default_factory=list,
        description="Possible candidate node IDs if partial matches exist",
    )


class RelationshipLinkerInput(BaseModel):
    """Input payload accepted by the Relationship Linker Agent."""
    nodes_from_structure_mapper: Optional[List[RegistryNode]] = Field(
        default=None,
        description="Explicit nodes from Structure Mapper. If omitted, all active nodes from registry are used.",
    )
    repo_root: Optional[str] = Field(default=None, description="Path to repository root for AST analysis")
    shard_path: Optional[str] = Field(default=None, description="Optional relative path to scope edge analysis")
    edge_types: Optional[List[EdgeType]] = Field(
        default=None,
        description="Types of edges to extract (defaults to calls, imports, inheritance, test_to_code)",
    )


class RelationshipLinkerOutput(BaseModel):
    """Output payload produced by the Relationship Linker Agent."""
    verified_edges: List[CodeEdge] = Field(
        default_factory=list,
        description="All edges verified against the registry where both endpoints exist",
    )
    unresolved_link_queue: List[UnresolvedLink] = Field(
        default_factory=list,
        description="Unresolved links where one or both endpoints could not be verified in registry (never guessed)",
    )
    registry_update_proposals: List[UpdateProposal] = Field(
        default_factory=list,
        description="Formulated proposals packaged for Registry Keeper to persist edges",
    )
    stats: Dict[str, Any] = Field(default_factory=dict, description="Linker execution statistics")
