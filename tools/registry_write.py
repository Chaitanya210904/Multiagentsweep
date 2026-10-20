"""
Tool: registry.write
Exclusive write tool for the single source of truth Code Registry.
Only agents with 'registry-write' access (the Registry Keeper) are authorized to execute mutations.
"""

from typing import Any, Dict, List, Optional, Tuple
from core.exceptions import UnauthorizedAccessError
from models.registry import ChangeLogEntry, RegistryNode
from storage.registry_store import CodeRegistryStore


class RegistryWriteTool:
    """Write interface for the Code Registry."""

    name = "registry.write"
    description = (
        "Write, update, delete, or rename nodes in the Code Registry. "
        "Strictly restricted to agents with 'registry-write' access."
    )

    def __init__(self, store: CodeRegistryStore, caller_access: str, caller_agent_id: str):
        self._store = store
        self._caller_access = caller_access
        self._caller_agent_id = caller_agent_id

    def write_node(
        self,
        node: RegistryNode,
        details: Optional[Dict[str, Any]] = None,
    ) -> Tuple[RegistryNode, Optional[ChangeLogEntry]]:
        """Register or update a node in the registry."""
        return self._store.write_node(
            node=node,
            access_token=self._caller_access,
            source_agent=self._caller_agent_id,
            details=details,
        )

    def delete_node(self, node_id: str, reason: str = "") -> ChangeLogEntry:
        """Mark a single node as deleted."""
        return self._store.delete_node(
            node_id=node_id,
            access_token=self._caller_access,
            source_agent=self._caller_agent_id,
            reason=reason,
        )

    def delete_by_path(self, path: str, reason: str = "File removed") -> List[ChangeLogEntry]:
        """Delete all nodes belonging to a deleted file."""
        return self._store.delete_by_path(
            path=path,
            access_token=self._caller_access,
            source_agent=self._caller_agent_id,
            reason=reason,
        )

    def rename_path(self, old_path: str, new_path: str) -> List[ChangeLogEntry]:
        """Rename all nodes belonging to a moved or renamed file."""
        return self._store.rename_path(
            old_path=old_path,
            new_path=new_path,
            access_token=self._caller_access,
            source_agent=self._caller_agent_id,
        )
