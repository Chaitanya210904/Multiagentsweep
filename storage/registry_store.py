"""
Single source of truth storage engine for the Code Registry.
Enforces the invariant: Only an agent with 'registry-write' permission can mutate the registry.
"""

from collections import defaultdict
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from core.exceptions import (
    RegistryDuplicateError,
    RegistryNotFoundError,
    UnauthorizedAccessError,
    ValidationError,
)
from models.registry import (
    ChangeAction,
    ChangeLogEntry,
    NodeLocation,
    NodeStatus,
    NodeType,
    RegistryNode,
)


class CodeRegistryStore:
    """
    Central in-memory & file-backed store for code and system entities.
    Strictly verifies permissions before any write/mutation operation.
    """

    ALLOWED_WRITE_PERMISSION = "registry-write"

    def __init__(self, persistence_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._persistence_path = Path(persistence_path) if persistence_path else None
        
        # Primary lookup by unique canonical ID
        self._nodes_by_id: Dict[str, RegistryNode] = {}
        
        # Secondary indexes
        self._ids_by_path: Dict[str, Set[str]] = defaultdict(set)
        self._ids_by_type: Dict[NodeType, Set[str]] = defaultdict(set)
        self._ids_by_hash: Dict[str, Set[str]] = defaultdict(set)
        
        # Complete historical audit log
        self._change_log: List[ChangeLogEntry] = []

        if self._persistence_path and self._persistence_path.exists():
            self.load()

    def _verify_write_access(self, access_token: str, agent_id: str = "unknown") -> None:
        """Enforces that only authorized agents with 'registry-write' can mutate the registry."""
        if access_token != self.ALLOWED_WRITE_PERMISSION:
            raise UnauthorizedAccessError(
                f"Access denied for agent '{agent_id}'. Only agents with '{self.ALLOWED_WRITE_PERMISSION}' "
                f"access (Registry Keeper) are permitted to write to the registry."
            )

    # --------------------------------------------------------------------------
    # Read APIs (Open to all agents)
    # --------------------------------------------------------------------------

    def get(self, node_id: str) -> Optional[RegistryNode]:
        """Fetch a single node by canonical ID."""
        with self._lock:
            node = self._nodes_by_id.get(node_id)
            if node and node.status != NodeStatus.DELETED:
                return node
            return None

    def get_any_status(self, node_id: str) -> Optional[RegistryNode]:
        """Fetch a node by ID regardless of status (including deleted)."""
        with self._lock:
            return self._nodes_by_id.get(node_id)

    def get_by_path(self, path: str, include_deleted: bool = False) -> List[RegistryNode]:
        """Fetch all nodes associated with a file path."""
        with self._lock:
            clean_path = path.strip().lstrip("./")
            node_ids = self._ids_by_path.get(clean_path, set())
            results = []
            for nid in node_ids:
                node = self._nodes_by_id.get(nid)
                if node and (include_deleted or node.status != NodeStatus.DELETED):
                    results.append(node)
            return results

    def get_by_type(self, node_type: NodeType, include_deleted: bool = False) -> List[RegistryNode]:
        """Fetch all nodes of a specific type (e.g., all functions, all APIs)."""
        with self._lock:
            node_ids = self._ids_by_type.get(node_type, set())
            results = []
            for nid in node_ids:
                node = self._nodes_by_id.get(nid)
                if node and (include_deleted or node.status != NodeStatus.DELETED):
                    results.append(node)
            return results

    def get_by_hash(self, content_hash: str) -> List[RegistryNode]:
        """Find nodes matching a specific hash."""
        with self._lock:
            node_ids = self._ids_by_hash.get(content_hash, set())
            return [self._nodes_by_id[nid] for nid in node_ids if self._nodes_by_id[nid].status != NodeStatus.DELETED]

    def search(
        self,
        node_id: Optional[str] = None,
        path: Optional[str] = None,
        name: Optional[str] = None,
        node_type: Optional[NodeType] = None,
        content_hash: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[RegistryNode]:
        """Versatile search across multiple filters."""
        with self._lock:
            candidates: Optional[Set[str]] = None

            if node_id:
                if node_id in self._nodes_by_id:
                    candidates = {node_id}
                else:
                    return []

            if path:
                clean_path = path.strip().lstrip("./")
                path_matches = self._ids_by_path.get(clean_path, set())
                candidates = path_matches if candidates is None else candidates.intersection(path_matches)

            if node_type:
                type_matches = self._ids_by_type.get(node_type, set())
                candidates = type_matches if candidates is None else candidates.intersection(type_matches)

            if content_hash:
                hash_matches = self._ids_by_hash.get(content_hash, set())
                candidates = hash_matches if candidates is None else candidates.intersection(hash_matches)

            if candidates is None:
                candidates = set(self._nodes_by_id.keys())

            results = []
            for nid in candidates:
                node = self._nodes_by_id.get(nid)
                if not node:
                    continue
                if not include_deleted and node.status == NodeStatus.DELETED:
                    continue
                if name and name.lower() not in node.name.lower():
                    continue
                results.append(node)

            return results

    def list_all(self, include_deleted: bool = False) -> List[RegistryNode]:
        """Return all tracked nodes."""
        with self._lock:
            if include_deleted:
                return list(self._nodes_by_id.values())
            return [n for n in self._nodes_by_id.values() if n.status != NodeStatus.DELETED]

    def get_change_log(self, limit: Optional[int] = None) -> List[ChangeLogEntry]:
        """Fetch audit log of mutations."""
        with self._lock:
            if limit:
                return list(self._change_log[-limit:])
            return list(self._change_log)

    def count(self, include_deleted: bool = False) -> int:
        """Count active nodes."""
        with self._lock:
            if include_deleted:
                return len(self._nodes_by_id)
            return sum(1 for n in self._nodes_by_id.values() if n.status != NodeStatus.DELETED)

    # --------------------------------------------------------------------------
    # Write APIs (Protected - Registry Keeper Only)
    # --------------------------------------------------------------------------

    def write_node(
        self,
        node: RegistryNode,
        access_token: str,
        source_agent: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Tuple[RegistryNode, Optional[ChangeLogEntry]]:
        """
        Create or update a registry node.
        Computes differences and records change log entries only when meaningful mutations occur.
        """
        self._verify_write_access(access_token, agent_id=source_agent)

        with self._lock:
            clean_path = node.location.path.strip().lstrip("./")
            node.location.path = clean_path

            existing = self._nodes_by_id.get(node.id)

            if existing is None or existing.status == NodeStatus.DELETED:
                # Creation
                action = ChangeAction.CREATE
                node.created_at = time.time()
                node.updated_at = time.time()
                node.version = 1
                node.status = NodeStatus.ACTIVE

                self._nodes_by_id[node.id] = node
                self._index_node(node)

                log_entry = ChangeLogEntry(
                    action=action,
                    node_id=node.id,
                    node_type=node.type,
                    source_agent=source_agent,
                    old_hash=None,
                    new_hash=node.hash,
                    details=details or {"name": node.name, "path": clean_path},
                )
                self._change_log.append(log_entry)
                self._auto_save()
                return node, log_entry

            # Node exists: check if content changed
            old_hash = existing.hash
            hash_changed = old_hash != node.hash
            location_changed = (
                existing.location.path != node.location.path
                or existing.location.start_line != node.location.start_line
                or existing.location.end_line != node.location.end_line
                or existing.location.signature != node.location.signature
            )

            if not hash_changed and not location_changed and existing.status == NodeStatus.ACTIVE:
                # No material change: just update metadata if supplied
                if node.metadata:
                    existing.metadata.update(node.metadata)
                    existing.updated_at = time.time()
                return existing, None

            # Update existing
            self._unindex_node(existing)

            existing.name = node.name
            existing.location = node.location
            existing.hash = node.hash
            existing.metadata.update(node.metadata)
            existing.status = NodeStatus.ACTIVE
            existing.version += 1
            existing.updated_at = time.time()

            self._nodes_by_id[existing.id] = existing
            self._index_node(existing)

            log_entry = ChangeLogEntry(
                action=ChangeAction.UPDATE,
                node_id=existing.id,
                node_type=existing.type,
                source_agent=source_agent,
                old_hash=old_hash,
                new_hash=existing.hash,
                details=details or {
                    "version": existing.version,
                    "hash_changed": hash_changed,
                    "location_changed": location_changed,
                },
            )
            self._change_log.append(log_entry)
            self._auto_save()
            return existing, log_entry

    def delete_node(
        self,
        node_id: str,
        access_token: str,
        source_agent: str,
        reason: str = "",
    ) -> ChangeLogEntry:
        """Mark a node as deleted and purge it from active indexes."""
        self._verify_write_access(access_token, agent_id=source_agent)

        with self._lock:
            node = self._nodes_by_id.get(node_id)
            if not node:
                raise RegistryNotFoundError(f"Cannot delete node '{node_id}': not found in registry.")

            if node.status == NodeStatus.DELETED:
                # Already deleted
                return ChangeLogEntry(
                    action=ChangeAction.DELETE,
                    node_id=node_id,
                    node_type=node.type,
                    source_agent=source_agent,
                    details={"already_deleted": True, "reason": reason},
                )

            old_hash = node.hash
            self._unindex_node(node)
            node.status = NodeStatus.DELETED
            node.updated_at = time.time()

            log_entry = ChangeLogEntry(
                action=ChangeAction.DELETE,
                node_id=node_id,
                node_type=node.type,
                source_agent=source_agent,
                old_hash=old_hash,
                new_hash=None,
                details={"reason": reason},
            )
            self._change_log.append(log_entry)
            self._auto_save()
            return log_entry

    def delete_by_path(
        self,
        path: str,
        access_token: str,
        source_agent: str,
        reason: str = "File removed",
    ) -> List[ChangeLogEntry]:
        """Delete all nodes associated with a removed file path."""
        self._verify_write_access(access_token, agent_id=source_agent)

        with self._lock:
            clean_path = path.strip().lstrip("./")
            nodes_to_delete = self.get_by_path(clean_path, include_deleted=False)
            logs = []
            for node in nodes_to_delete:
                entry = self.delete_node(
                    node_id=node.id,
                    access_token=access_token,
                    source_agent=source_agent,
                    reason=reason,
                )
                logs.append(entry)
            return logs

    def rename_path(
        self,
        old_path: str,
        new_path: str,
        access_token: str,
        source_agent: str,
    ) -> List[ChangeLogEntry]:
        """
        Handle a file rename event:
        Updates location paths and adjusts IDs to maintain integrity.
        """
        self._verify_write_access(access_token, agent_id=source_agent)

        with self._lock:
            clean_old = old_path.strip().lstrip("./")
            clean_new = new_path.strip().lstrip("./")
            
            nodes = self.get_by_path(clean_old, include_deleted=False)
            logs = []

            for old_node in nodes:
                self._unindex_node(old_node)
                
                # Derive new ID if it was based on path
                old_id = old_node.id
                if clean_old in old_id:
                    new_id = old_id.replace(clean_old, clean_new, 1)
                else:
                    new_id = old_id

                # Remove old key if ID changed
                if new_id != old_id:
                    del self._nodes_by_id[old_id]

                old_node.id = new_id
                old_node.location.path = clean_new
                old_node.updated_at = time.time()
                old_node.version += 1

                self._nodes_by_id[new_id] = old_node
                self._index_node(old_node)

                log_entry = ChangeLogEntry(
                    action=ChangeAction.RENAME,
                    node_id=new_id,
                    node_type=old_node.type,
                    source_agent=source_agent,
                    old_hash=old_node.hash,
                    new_hash=old_node.hash,
                    details={"old_id": old_id, "old_path": clean_old, "new_path": clean_new},
                )
                self._change_log.append(log_entry)
                logs.append(log_entry)

            self._auto_save()
            return logs

    # --------------------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------------------

    def _index_node(self, node: RegistryNode) -> None:
        """Add node to auxiliary indexes."""
        self._ids_by_path[node.location.path].add(node.id)
        self._ids_by_type[node.type].add(node.id)
        if node.hash:
            self._ids_by_hash[node.hash].add(node.id)

    def _unindex_node(self, node: RegistryNode) -> None:
        """Remove node from auxiliary indexes."""
        self._ids_by_path[node.location.path].discard(node.id)
        self._ids_by_type[node.type].discard(node.id)
        if node.hash:
            self._ids_by_hash[node.hash].discard(node.id)

    def _auto_save(self) -> None:
        if self._persistence_path:
            self.save()

    def save(self, filepath: Optional[str] = None) -> None:
        """Save entire registry state to disk as JSON."""
        target = Path(filepath) if filepath else self._persistence_path
        if not target:
            return
        
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = {
                "nodes": {nid: node.model_dump() for nid, node in self._nodes_by_id.items()},
                "change_log": [entry.model_dump() for entry in self._change_log],
            }
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

    def load(self, filepath: Optional[str] = None) -> None:
        """Load registry state from disk."""
        target = Path(filepath) if filepath else self._persistence_path
        if not target or not target.exists():
            return

        with self._lock:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._nodes_by_id.clear()
            self._ids_by_path.clear()
            self._ids_by_type.clear()
            self._ids_by_hash.clear()
            self._change_log.clear()

            for nid, node_data in data.get("nodes", {}).items():
                node = RegistryNode.model_validate(node_data)
                self._nodes_by_id[nid] = node
                if node.status != NodeStatus.DELETED:
                    self._index_node(node)

            for entry_data in data.get("change_log", []):
                self._change_log.append(ChangeLogEntry.model_validate(entry_data))
