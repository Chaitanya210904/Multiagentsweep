"""
Tool: registry.lookup
Read-only lookup interface used by Structure Mapper and other graph agents
to verify if nodes exist in the registry and compare hashes.
"""

from typing import Dict, List, Optional
from models.registry import NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore


class RegistryLookupTool:
    """Read-only lookup interface to query the single source of truth Code Registry."""

    name = "registry.lookup"
    description = "Lookup nodes in the registry by ID, path, or type, and compare hashes."

    def __init__(self, store: CodeRegistryStore):
        self._store = store

    def get(self, node_id: str) -> Optional[RegistryNode]:
        """Fetch node by canonical ID."""
        return self._store.get(node_id)

    def get_by_id(self, node_id: str) -> Optional[RegistryNode]:
        """Alias for get()."""
        return self.get(node_id)

    def get_by_path(self, path: str) -> List[RegistryNode]:
        """Fetch all active nodes defined in a specific file path."""
        return self._store.get_by_path(path, include_deleted=False)

    def get_by_type(self, node_type: NodeType) -> List[RegistryNode]:
        """Fetch all active nodes of a specific type (e.g. all classes, all functions)."""
        return self._store.get_by_type(node_type, include_deleted=False)

    def find_by_type(self, node_type: NodeType) -> List[RegistryNode]:
        """Alias for get_by_type."""
        return self.get_by_type(node_type)

    def search(
        self,
        node_id: Optional[str] = None,
        path: Optional[str] = None,
        name: Optional[str] = None,
        node_type: Optional[NodeType] = None,
    ) -> List[RegistryNode]:
        """Search nodes matching specific criteria."""
        return self._store.search(
            node_id=node_id,
            path=path,
            name=name,
            node_type=node_type,
            include_deleted=False,
        )

    def is_node_modified(self, node_id: str, new_hash: str) -> bool:
        """
        Returns True if node exists and has a different hash,
        or False if node is not found or has identical hash.
        """
        existing = self.get(node_id)
        if not existing:
            return False
        return existing.hash != new_hash

    def exists(self, node_id: str) -> bool:
        """Checks if a node currently exists and is active."""
        return self._store.get(node_id) is not None
