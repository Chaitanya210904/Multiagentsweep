"""
Data models for the Code Registry and Registry Keeper Agent.
"""

from enum import Enum
import hashlib
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class NodeType(str, Enum):
    FILE = "file"
    MODULE = "module"
    FUNCTION = "function"
    CLASS = "class"
    API = "api"
    TABLE = "table"
    SERVICE = "service"


class NodeStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DELETED = "deleted"


class ChangeAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RENAME = "rename"
    DEPRECATE = "deprecate"


class NodeLocation(BaseModel):
    """Represents the physical or logical location of a registry node."""
    path: str = Field(description="File path or URI where the node resides")
    start_line: Optional[int] = Field(default=None, description="Starting line in the file")
    end_line: Optional[int] = Field(default=None, description="Ending line in the file")
    signature: Optional[str] = Field(default=None, description="Code signature or endpoint route/query")
    service_name: Optional[str] = Field(default=None, description="Parent microservice/system name")
    table_name: Optional[str] = Field(default=None, description="Database table name if applicable")
    endpoint_method: Optional[str] = Field(default=None, description="HTTP method for API nodes (e.g., GET, POST)")
    endpoint_route: Optional[str] = Field(default=None, description="API route/path (e.g., /api/v1/auth)")


class RegistryNode(BaseModel):
    """
    Canonical node representing every tracked code/system element:
    file, module, function, class, API, table, and service.
    """
    id: str = Field(description="Unique canonical identifier (e.g., 'func:src/auth.py:verify_token')")
    name: str = Field(description="Human-readable node name")
    type: NodeType = Field(description="Type of code or architectural entity")
    location: NodeLocation = Field(description="Physical or logical location of the entity")
    hash: str = Field(description="Cryptographic content or signature hash (SHA-256)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata tags, docstrings, parameters")
    status: NodeStatus = Field(default=NodeStatus.ACTIVE, description="Active status of the entity")
    version: int = Field(default=1, description="Version counter incremented on each mutation")
    created_at: float = Field(default_factory=time.time, description="Creation timestamp")
    updated_at: float = Field(default_factory=time.time, description="Last update timestamp")

    @classmethod
    def generate_hash(cls, content: str) -> str:
        """Utility to compute standard SHA-256 hash for content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def build_canonical_id(cls, node_type: NodeType, path: str, identifier: str) -> str:
        """Construct standard canonical ID format."""
        clean_path = path.strip().lstrip("./")
        clean_id = identifier.strip()
        if node_type == NodeType.FILE:
            return f"file:{clean_path}"
        elif node_type == NodeType.MODULE:
            return f"module:{clean_path}"
        elif node_type == NodeType.SERVICE:
            return f"service:{clean_id}"
        elif node_type == NodeType.TABLE:
            return f"table:{clean_id}"
        elif node_type == NodeType.API:
            # clean_id could be "POST /api/v1/login"
            return f"api:{clean_id.replace(' ', ':')}"
        else:
            return f"{node_type.value}:{clean_path}:{clean_id}"


class ChangeLogEntry(BaseModel):
    """Audit log entry capturing every mutation applied to the registry."""
    timestamp: float = Field(default_factory=time.time)
    action: ChangeAction
    node_id: str
    node_type: NodeType
    source_agent: str
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class UpdateProposal(BaseModel):
    """
    Proposed mutation coming from upstream graph agents:
    - Structure Mapper (nodes: files, classes, functions)
    - Relationship Linker (edge verification & unresolved queue)
    - Data & Service Mapper (APIs, tables, services)
    """
    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_agent: str = Field(description="Name/ID of proposing agent")
    action: ChangeAction = Field(default=ChangeAction.CREATE)
    node: Optional[RegistryNode] = Field(default=None, description="Proposed node definition")
    old_id: Optional[str] = Field(default=None, description="Target ID for rename or deletion")
    old_path: Optional[str] = Field(default=None, description="Previous file path for renames")
    new_path: Optional[str] = Field(default=None, description="New file path for renames")
    metadata_update: Optional[Dict[str, Any]] = Field(default=None, description="Delta updates for metadata")
    details: Dict[str, Any] = Field(default_factory=dict)


class GitDiffEntry(BaseModel):
    """Represents a git diff change affecting a file."""
    change_type: str = Field(description="'A' (added), 'M' (modified), 'D' (deleted), 'R' (renamed)")
    path: str = Field(description="Target file path")
    old_path: Optional[str] = Field(default=None, description="Previous file path if renamed")
    patch: Optional[str] = Field(default=None, description="Diff hunk or patch content")


class UnresolvedItem(BaseModel):
    """Represents an item or proposal that could not be resolved or validated."""
    item_id: str
    reason: str
    source_agent: str
    proposal: Optional[Dict[str, Any]] = None
    suggested_action: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class LookupQuery(BaseModel):
    """Query object for looking up entities in the registry."""
    id: Optional[str] = None
    path: Optional[str] = None
    name: Optional[str] = None
    type: Optional[NodeType] = None
    hash: Optional[str] = None


class RegistryKeeperInput(BaseModel):
    """Input payload accepted by the Registry Keeper."""
    update_proposals_from_structure_mapper: List[UpdateProposal] = Field(default_factory=list)
    update_proposals_from_relationship_linker: List[UpdateProposal] = Field(default_factory=list)
    update_proposals_from_data_service_mapper: List[UpdateProposal] = Field(default_factory=list)
    git_diffs: List[GitDiffEntry] = Field(default_factory=list)
    deleted_or_renamed_files: List[Dict[str, Any]] = Field(default_factory=list)
    lookups: List[LookupQuery] = Field(default_factory=list)


class RegistryKeeperOutput(BaseModel):
    """Output payload produced by the Registry Keeper."""
    updated_registry: List[RegistryNode] = Field(default_factory=list)
    lookup_answers: Dict[str, Optional[RegistryNode]] = Field(default_factory=dict)
    unresolved_items_list: List[UnresolvedItem] = Field(default_factory=list)
    change_log: List[ChangeLogEntry] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)
