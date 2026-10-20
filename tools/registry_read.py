"""
Tool: registry.read
Provides safe, read-only access to the Code Registry.
Callable by any agent in the multi-agent system.
"""

from typing import Any, Dict, List, Optional
from models.registry import NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore


class RegistryReadTool:
    """Read interface for the Code Registry."""

    name = "registry.read"
    description = "Read, lookup, and search nodes from the single source of truth Code Registry."

    def __init__(self, store: CodeRegistryStore):
        self._store = store

    def get(self, node_id: str) -> Optional[RegistryNode]:
        """Fetch node by canonical ID."""
        return self._store.get(node_id)

    def lookup(
        self,
        node_id: Optional[str] = None,
        path: Optional[str] = None,
        name: Optional[str] = None,
        node_type: Optional[NodeType] = None,
        content_hash: Optional[str] = None,
    ) -> List[RegistryNode]:
        """Lookup nodes using flexible search filters."""
        return self._store.search(
            node_id=node_id,
            path=path,
            name=name,
            node_type=node_type,
            content_hash=content_hash,
            include_deleted=False,
        )

    def get_by_path(self, path: str) -> List[RegistryNode]:
        """Fetch all active nodes defined in a specific file path."""
        return self._store.get_by_path(path, include_deleted=False)

    def get_by_type(self, node_type: NodeType) -> List[RegistryNode]:
        """Fetch all active nodes of a given type (file, class, function, api, table, service)."""
        return self._store.get_by_type(node_type, include_deleted=False)

    def list_all(self) -> List[RegistryNode]:
        """List all active nodes in the registry."""
        return self._store.list_all(include_deleted=False)

    def exists(self, node_id: str) -> bool:
        """Check whether a node ID currently exists and is active."""
        return self._store.get(node_id) is not None
