"""
Data models for the Data & Service Mapper Agent (Layer: Graph).
Defines system edge types, system edges, unresolved queue entries, and mapper payloads.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from models.registry import RegistryNode, UpdateProposal


class SystemEdgeType(str, Enum):
    """Categorization of system-level relationships."""
    API_TO_CODE = "api_to_code"
    CODE_TO_TABLE = "code_to_table"
    SERVICE_TO_SERVICE = "service_to_service"


class SystemEdge(BaseModel):
    """
    Represents a verified system-level edge connecting APIs to code, code to tables,
    or services to external services/queues.
    """
    id: str = Field(description="Unique system edge identifier, e.g. 'edge:api_to_code:api:...->func:...'")
    source_id: str = Field(description="Originating node ID in registry")
    target_id: str = Field(description="Destination node ID in registry")
    type: SystemEdgeType = Field(description="Type of system relationship")
    operation: Optional[str] = Field(default=None, description="HTTP method, SQL operation (SELECT/INSERT), or protocol")
    line_number: Optional[int] = Field(default=None, description="Line number in source file")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Contextual metadata")

    @classmethod
    def create(
        cls,
        source_id: str,
        target_id: str,
        edge_type: SystemEdgeType,
        operation: Optional[str] = None,
        line_number: Optional[int] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SystemEdge":
        edge_id = f"edge:{edge_type.value}:{source_id}->{target_id}"
        return cls(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            type=edge_type,
            operation=operation,
            line_number=line_number,
            confidence=confidence,
            metadata=metadata or {},
        )


class UnresolvedSystemLink(BaseModel):
    """
    Represents an unresolved system dependency (missing DB table, unregistered service, or unmapped handler).
    As per architecture specifications: checks registry before linking, missing endpoints never guessed.
    """
    link_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: Optional[str] = Field(default=None)
    source_path: str = Field(description="File where reference occurred")
    raw_target: str = Field(description="Target route, table name, or service name")
    edge_type: SystemEdgeType = Field(description="Intended system edge type")
    line_number: Optional[int] = Field(default=None)
    reason: str = Field(description="Explicit explanation why endpoint could not be verified in registry")


class DataServiceMapperInput(BaseModel):
    """Input payload accepted by the Data & Service Mapper Agent."""
    api_specs: Optional[List[str]] = Field(default=None, description="Paths to API spec files or folders")
    migrations: Optional[List[str]] = Field(default=None, description="Paths to SQL or ORM migration files")
    query_code: Optional[List[str]] = Field(default=None, description="Paths to source files containing database queries")
    config_files: Optional[List[str]] = Field(default=None, description="Paths to configuration or env files")
    repo_root: Optional[str] = Field(default=None, description="Repository root path")
    shard_path: Optional[str] = Field(default=None, description="Optional path to scope scanning")


class DataServiceMapperOutput(BaseModel):
    """Output payload produced by the Data & Service Mapper Agent."""
    api_nodes: List[RegistryNode] = Field(default_factory=list, description="Extracted API endpoint nodes")
    table_nodes: List[RegistryNode] = Field(default_factory=list, description="Extracted database table nodes")
    service_nodes: List[RegistryNode] = Field(default_factory=list, description="Extracted external service/queue nodes")
    api_to_code_edges: List[SystemEdge] = Field(default_factory=list, description="Verified edges from APIs to code handlers")
    code_to_table_edges: List[SystemEdge] = Field(default_factory=list, description="Verified edges from code to DB tables")
    service_to_service_edges: List[SystemEdge] = Field(default_factory=list, description="Verified edges to external services/queues")
    unresolved_queue: List[UnresolvedSystemLink] = Field(default_factory=list, description="Missing endpoints queue")
    registry_update_proposals: List[UpdateProposal] = Field(default_factory=list, description="Update proposals for Registry Keeper")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Processing metrics and counts")
