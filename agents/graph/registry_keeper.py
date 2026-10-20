"""
Registry Keeper Agent
Layer: graph
Role: Single source of truth (the list)
Description: Owns the registry of every file, module, function, class, API, table and service
             with ID, location and hash. Only agent allowed to write to the registry.
Access: registry-write
Model Tier: small
Trigger: first on every commit; on every update proposal
"""

import ast
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agents.base import AgentMetadata, BaseAgent
from core.exceptions import UnauthorizedAccessError
from models.registry import (
    ChangeAction,
    ChangeLogEntry,
    GitDiffEntry,
    LookupQuery,
    NodeLocation,
    NodeStatus,
    NodeType,
    RegistryKeeperInput,
    RegistryKeeperOutput,
    RegistryNode,
    UnresolvedItem,
    UpdateProposal,
)
from storage.registry_store import CodeRegistryStore
from tools.git_diff import GitDiffTool
from tools.registry_read import RegistryReadTool
from tools.registry_write import RegistryWriteTool

logger = logging.getLogger(__name__)


REGISTRY_KEEPER_METADATA = AgentMetadata(
    id="registry_keeper",
    name="Registry Keeper",
    layer="graph",
    role="Single source of truth (the list)",
    description=(
        "Owns the registry of every file, module, function, class, API, table and service "
        "with ID, location and hash. Only agent allowed to write to the registry."
    ),
    access="registry-write",
    model_tier="small",
    inputs=[
        "update_proposals_from_structure_mapper",
        "update_proposals_from_relationship_linker",
        "update_proposals_from_data_service_mapper",
        "git_diffs",
        "deleted_or_renamed_files",
    ],
    outputs=[
        "updated_registry",
        "lookup_answers",
        "unresolved_items_list",
        "change_log",
    ],
    tools=[
        "registry.read",
        "registry.write",
        "git.diff",
    ],
    trigger="first on every commit; on every update proposal",
    optional=False,
)


class RegistryKeeper(BaseAgent):
    """
    The Registry Keeper Agent is the sole owner and guardian of the Code Registry.
    Guarantees registry integrity, handles git diff updates, processes node proposals
    from Structure Mapper, Relationship Linker, and Data & Service Mapper, and answers lookups.
    """

    def __init__(
        self,
        store: CodeRegistryStore,
        repo_root: Optional[str] = None,
        metadata: Optional[AgentMetadata] = None,
    ):
        super().__init__(metadata=metadata or REGISTRY_KEEPER_METADATA)
        self.store = store
        
        # Tools initialized with proper permissions
        self.read_tool = RegistryReadTool(store=self.store)
        self.write_tool = RegistryWriteTool(
            store=self.store,
            caller_access=self.access,
            caller_agent_id=self.id,
        )
        self.git_tool = GitDiffTool(repo_root=repo_root)

    def execute(self, inputs: RegistryKeeperInput) -> RegistryKeeperOutput:
        """
        Executes the Registry Keeper reconciliation cycle:
        1. Process git diffs and deleted/renamed files
        2. Process node proposals from Structure Mapper
        3. Process relationship proposals from Relationship Linker
        4. Process service/data proposals from Data & Service Mapper
        5. Answer lookup queries
        6. Return updated registry slice, unresolved items, and change log
        """
        self.require_access("registry-write")

        updated_nodes: Dict[str, RegistryNode] = {}
        unresolved_items: List[UnresolvedItem] = []
        change_logs: List[ChangeLogEntry] = []

        # ----------------------------------------------------------------------
        # 1. Process Git Diffs & Deleted / Renamed Files
        # ----------------------------------------------------------------------
        self._process_git_diffs_and_deletions(
            git_diffs=inputs.git_diffs,
            deleted_or_renamed_files=inputs.deleted_or_renamed_files,
            change_logs=change_logs,
        )

        # ----------------------------------------------------------------------
        # 2. Process Proposals from Structure Mapper (Agent 4: Nodes)
        # ----------------------------------------------------------------------
        self._process_structure_mapper_proposals(
            proposals=inputs.update_proposals_from_structure_mapper,
            updated_nodes=updated_nodes,
            unresolved_items=unresolved_items,
            change_logs=change_logs,
        )

        # ----------------------------------------------------------------------
        # 3. Process Proposals from Relationship Linker (Agent 5: Code Edges)
        # ----------------------------------------------------------------------
        self._process_relationship_linker_proposals(
            proposals=inputs.update_proposals_from_relationship_linker,
            updated_nodes=updated_nodes,
            unresolved_items=unresolved_items,
            change_logs=change_logs,
        )

        # ----------------------------------------------------------------------
        # 4. Process Proposals from Data & Service Mapper (Agent 6: System Edges)
        # ----------------------------------------------------------------------
        self._process_data_service_mapper_proposals(
            proposals=inputs.update_proposals_from_data_service_mapper,
            updated_nodes=updated_nodes,
            unresolved_items=unresolved_items,
            change_logs=change_logs,
        )

        # ----------------------------------------------------------------------
        # 5. Answer Lookup Queries
        # ----------------------------------------------------------------------
        lookup_answers = self._answer_lookups(inputs.lookups)

        # Compile statistics
        stats = {
            "total_active_nodes": self.store.count(include_deleted=False),
            "updated_nodes_count": len(updated_nodes),
            "unresolved_items_count": len(unresolved_items),
            "change_log_entries_count": len(change_logs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return RegistryKeeperOutput(
            updated_registry=list(updated_nodes.values()),
            lookup_answers=lookup_answers,
            unresolved_items_list=unresolved_items,
            change_log=change_logs,
            stats=stats,
        )

    # --------------------------------------------------------------------------
    # Subroutines
    # --------------------------------------------------------------------------

    def _process_git_diffs_and_deletions(
        self,
        git_diffs: List[GitDiffEntry],
        deleted_or_renamed_files: List[Dict[str, Any]],
        change_logs: List[ChangeLogEntry],
    ) -> None:
        """Handles deleted and renamed files detected from git diff or explicit notifications."""
        # Process git diff entries
        for diff in git_diffs:
            change_type = diff.change_type.upper()
            if change_type == "D":
                # File deleted: delete all child nodes in registry
                logs = self.write_tool.delete_by_path(
                    path=diff.path,
                    reason=f"File deleted according to git diff: {diff.path}",
                )
                change_logs.extend(logs)
            elif change_type == "R" and diff.old_path:
                # File renamed: update path and IDs
                logs = self.write_tool.rename_path(
                    old_path=diff.old_path,
                    new_path=diff.path,
                )
                change_logs.extend(logs)

        # Process explicit deleted_or_renamed_files list
        for item in deleted_or_renamed_files:
            action = item.get("action", "").lower()
            if action in ("delete", "deleted"):
                path = item.get("path")
                if path:
                    logs = self.write_tool.delete_by_path(
                        path=path,
                        reason=item.get("reason", f"File marked deleted: {path}"),
                    )
                    change_logs.extend(logs)
            elif action in ("rename", "renamed"):
                old_path = item.get("old_path")
                new_path = item.get("new_path")
                if old_path and new_path:
                    logs = self.write_tool.rename_path(
                        old_path=old_path,
                        new_path=new_path,
                    )
                    change_logs.extend(logs)

    def _process_structure_mapper_proposals(
        self,
        proposals: List[UpdateProposal],
        updated_nodes: Dict[str, RegistryNode],
        unresolved_items: List[UnresolvedItem],
        change_logs: List[ChangeLogEntry],
    ) -> None:
        """
        Structure Mapper registers nodes: files, modules, classes, and functions.
        Each node must have a canonical ID, location with path, and content hash.
        """
        for proposal in proposals:
            node = proposal.node
            if not node:
                unresolved_items.append(
                    UnresolvedItem(
                        item_id=proposal.proposal_id,
                        reason="Proposal missing node definition",
                        source_agent="structure_mapper",
                        proposal=proposal.model_dump(),
                        suggested_action="Ensure node object is attached to proposal",
                    )
                )
                continue

            # Validate required node fields
            if not node.id or not node.name or not node.location or not node.location.path or not node.hash:
                unresolved_items.append(
                    UnresolvedItem(
                        item_id=node.id or proposal.proposal_id,
                        reason=f"Node validation failed for '{node.name or 'unknown'}': missing required fields (id, name, path, hash)",
                        source_agent="structure_mapper",
                        proposal=proposal.model_dump(),
                        suggested_action="Provide complete node with id, name, location.path, and hash",
                    )
                )
                continue

            # Apply write
            try:
                written_node, log_entry = self.write_tool.write_node(
                    node=node,
                    details={"source": "structure_mapper", "proposal_id": proposal.proposal_id},
                )
                updated_nodes[written_node.id] = written_node
                if log_entry:
                    change_logs.append(log_entry)
            except Exception as e:
                unresolved_items.append(
                    UnresolvedItem(
                        item_id=node.id,
                        reason=f"Failed to write node to registry: {str(e)}",
                        source_agent="structure_mapper",
                        proposal=proposal.model_dump(),
                        suggested_action="Review node schema and conflicts",
                    )
                )

    def _process_relationship_linker_proposals(
        self,
        proposals: List[UpdateProposal],
        updated_nodes: Dict[str, RegistryNode],
        unresolved_items: List[UnresolvedItem],
        change_logs: List[ChangeLogEntry],
    ) -> None:
        """
        Relationship Linker creates calls, imports, inheritance, and test-to-code edges.
        Both endpoints MUST exist in the registry first; if one is missing, it goes
        to unresolved_items_list instead of being guessed.
        """
        for proposal in proposals:
            details = proposal.details or {}
            source_id = details.get("source_id") or (proposal.node.id if proposal.node else None)
            target_id = details.get("target_id")

            if not source_id or not target_id:
                # If proposal is a node update instead
                if proposal.node:
                    try:
                        written_node, log_entry = self.write_tool.write_node(
                            node=proposal.node,
                            details={"source": "relationship_linker", "proposal_id": proposal.proposal_id},
                        )
                        updated_nodes[written_node.id] = written_node
                        if log_entry:
                            change_logs.append(log_entry)
                    except Exception as e:
                        unresolved_items.append(
                            UnresolvedItem(
                                item_id=proposal.node.id,
                                reason=f"Failed to write node: {str(e)}",
                                source_agent="relationship_linker",
                                proposal=proposal.model_dump(),
                            )
                        )
                continue

            # Verify both endpoints exist in the registry
            source_node = self.read_tool.get(source_id)
            target_node = self.read_tool.get(target_id)

            if not source_node:
                unresolved_items.append(
                    UnresolvedItem(
                        item_id=f"edge:{source_id}->{target_id}",
                        reason=f"Source endpoint '{source_id}' does not exist in registry. Edge rejected to unresolved queue.",
                        source_agent="relationship_linker",
                        proposal=proposal.model_dump(),
                        suggested_action=f"Register source node '{source_id}' via Structure Mapper first",
                    )
                )
                continue

            if not target_node:
                unresolved_items.append(
                    UnresolvedItem(
                        item_id=f"edge:{source_id}->{target_id}",
                        reason=f"Target endpoint '{target_id}' does not exist in registry. Edge rejected to unresolved queue.",
                        source_agent="relationship_linker",
                        proposal=proposal.model_dump(),
                        suggested_action=f"Register target node '{target_id}' via Structure Mapper first",
                    )
                )
                continue

            # Both endpoints exist: attach relationship link metadata to source node
            edge_type = details.get("edge_type", "reference")
            edges = source_node.metadata.setdefault("outgoing_edges", [])
            edge_repr = {"target_id": target_id, "type": edge_type}
            if edge_repr not in edges:
                edges.append(edge_repr)
                written_node, log_entry = self.write_tool.write_node(
                    node=source_node,
                    details={
                        "source": "relationship_linker",
                        "edge_added": edge_repr,
                    },
                )
                updated_nodes[written_node.id] = written_node
                if log_entry:
                    change_logs.append(log_entry)

    def _process_data_service_mapper_proposals(
        self,
        proposals: List[UpdateProposal],
        updated_nodes: Dict[str, RegistryNode],
        unresolved_items: List[UnresolvedItem],
        change_logs: List[ChangeLogEntry],
    ) -> None:
        """
        Data & Service Mapper maps APIs, DB tables, queries, and services.
        Checks registry before linking and registers verified system nodes.
        """
        for proposal in proposals:
            node = proposal.node
            if not node:
                unresolved_items.append(
                    UnresolvedItem(
                        item_id=proposal.proposal_id,
                        reason="Proposal missing system node definition",
                        source_agent="data_service_mapper",
                        proposal=proposal.model_dump(),
                    )
                )
                continue

            # Check that node type is valid for Data & Service Mapper
            if node.type not in (NodeType.API, NodeType.TABLE, NodeType.SERVICE):
                unresolved_items.append(
                    UnresolvedItem(
                        item_id=node.id,
                        reason=f"Unexpected node type '{node.type}' for Data & Service Mapper",
                        source_agent="data_service_mapper",
                        proposal=proposal.model_dump(),
                        suggested_action="Ensure type is 'api', 'table', or 'service'",
                    )
                )
                continue

            # API specific check
            if node.type == NodeType.API:
                if not (node.location.endpoint_route or node.location.signature):
                    unresolved_items.append(
                        UnresolvedItem(
                            item_id=node.id,
                            reason="API node missing endpoint route or signature",
                            source_agent="data_service_mapper",
                            proposal=proposal.model_dump(),
                            suggested_action="Provide endpoint_route (e.g. '/api/v1/auth') or signature",
                        )
                    )
                    continue

            # Table specific check
            if node.type == NodeType.TABLE:
                if not (node.location.table_name or node.name):
                    unresolved_items.append(
                        UnresolvedItem(
                            item_id=node.id,
                            reason="Table node missing table_name or name",
                            source_agent="data_service_mapper",
                            proposal=proposal.model_dump(),
                        )
                    )
                    continue

            # Service specific check
            if node.type == NodeType.SERVICE:
                if not (node.location.service_name or node.name):
                    unresolved_items.append(
                        UnresolvedItem(
                            item_id=node.id,
                            reason="Service node missing service_name or name",
                            source_agent="data_service_mapper",
                            proposal=proposal.model_dump(),
                        )
                    )
                    continue

            # Write system node
            try:
                written_node, log_entry = self.write_tool.write_node(
                    node=node,
                    details={"source": "data_service_mapper", "proposal_id": proposal.proposal_id},
                )
                updated_nodes[written_node.id] = written_node
                if log_entry:
                    change_logs.append(log_entry)
            except Exception as e:
                unresolved_items.append(
                    UnresolvedItem(
                        item_id=node.id,
                        reason=f"Failed to write system node: {str(e)}",
                        source_agent="data_service_mapper",
                        proposal=proposal.model_dump(),
                    )
                )

    def _answer_lookups(self, lookups: List[LookupQuery]) -> Dict[str, Optional[RegistryNode]]:
        """Resolves lookup queries against the registry."""
        answers: Dict[str, Optional[RegistryNode]] = {}
        for query in lookups:
            query_key = query.id or f"{query.type}:{query.path}:{query.name}"
            if query.id:
                node = self.read_tool.get(query.id)
                answers[query_key] = node
            else:
                matches = self.read_tool.lookup(
                    path=query.path,
                    name=query.name,
                    node_type=query.type,
                    content_hash=query.hash,
                )
                answers[query_key] = matches[0] if matches else None
        return answers

    # --------------------------------------------------------------------------
    # Production Ready Utilities: Real Repository Scanning & Git Sync
    # --------------------------------------------------------------------------

    def scan_repository(
        self,
        repo_path: Optional[str] = None,
        exclude_dirs: Optional[List[str]] = None,
        source_agent: str = "structure_mapper",
    ) -> RegistryKeeperOutput:
        """
        Scans a real repository filesystem, extracts all files, classes, and functions,
        computes real cryptographic SHA-256 hashes, and updates the registry.
        """
        target_dir = Path(repo_path).resolve() if repo_path else self.git_tool.repo_root
        excluded = set(exclude_dirs or [
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
            ".registry",
            "dist",
            "build",
            ".egg-info",
        ])

        proposals: List[UpdateProposal] = []

        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in excluded and not d.startswith(".")]
            
            for file_name in files:
                if file_name.startswith("."):
                    continue
                file_full = Path(root) / file_name
                nodes = extract_nodes_from_disk(file_full, target_dir)
                for node in nodes:
                    proposals.append(
                        UpdateProposal(
                            source_agent=source_agent,
                            action=ChangeAction.CREATE,
                            node=node,
                            details={"scanned_from_disk": True},
                        )
                    )

        inputs = RegistryKeeperInput(update_proposals_from_structure_mapper=proposals)
        return self.execute(inputs)

    def sync_with_git(
        self,
        base_commit: Optional[str] = None,
        target_commit: Optional[str] = None,
        staged: bool = False,
        source_agent: str = "structure_mapper",
    ) -> RegistryKeeperOutput:
        """
        Queries real git diff from the local repository, parses added, modified,
        renamed, or deleted files, parses code nodes from changed files, and reconciles the registry.
        """
        diff_entries = self.git_tool.get_diff_entries(
            base_commit=base_commit,
            target_commit=target_commit,
            staged=staged,
        )

        structure_proposals: List[UpdateProposal] = []
        git_diffs: List[GitDiffEntry] = []

        for diff in diff_entries:
            git_diffs.append(diff)
            change = diff.change_type.upper()

            if change in ("A", "M"):
                file_path = self.git_tool.repo_root / diff.path
                if file_path.is_file():
                    nodes = extract_nodes_from_disk(file_path, self.git_tool.repo_root)
                    for node in nodes:
                        structure_proposals.append(
                            UpdateProposal(
                                source_agent=source_agent,
                                action=ChangeAction.UPDATE if change == "M" else ChangeAction.CREATE,
                                node=node,
                                details={"git_change": change},
                            )
                        )

        inputs = RegistryKeeperInput(
            update_proposals_from_structure_mapper=structure_proposals,
            git_diffs=git_diffs,
        )
        return self.execute(inputs)

    def apply_proposals_file(self, file_path: str) -> RegistryKeeperOutput:
        """Loads and applies real proposals from a JSON file."""
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Proposals file not found: {file_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        inputs = RegistryKeeperInput.model_validate(data)
        return self.execute(inputs)


def extract_nodes_from_disk(file_path: Path, repo_root: Path) -> List[RegistryNode]:
    """Inspects a real file on disk and extracts RegistryNode objects (file, classes, functions)."""
    try:
        rel_path = str(file_path.relative_to(repo_root))
    except ValueError:
        rel_path = str(file_path)

    if not file_path.is_file():
        return []

    try:
        raw_bytes = file_path.read_bytes()
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
    except Exception:
        return []

    stat = file_path.stat()
    file_node = RegistryNode(
        id=f"file:{rel_path}",
        name=file_path.name,
        type=NodeType.FILE,
        location=NodeLocation(path=rel_path),
        hash=file_hash,
        metadata={
            "size_bytes": stat.st_size,
            "modified_time": stat.st_mtime,
            "extension": file_path.suffix,
        },
    )

    nodes = [file_node]

    # If python file, parse AST to extract real functions and classes
    if file_path.suffix == ".py":
        try:
            content = raw_bytes.decode("utf-8")
            tree = ast.parse(content, filename=rel_path)
            lines = content.splitlines()

            for item in tree.body:
                if isinstance(item, ast.ClassDef):
                    class_lines = "\n".join(lines[item.lineno - 1 : item.end_lineno])
                    class_hash = hashlib.sha256(class_lines.encode("utf-8")).hexdigest()
                    class_node = RegistryNode(
                        id=f"class:{rel_path}:{item.name}",
                        name=item.name,
                        type=NodeType.CLASS,
                        location=NodeLocation(
                            path=rel_path,
                            start_line=item.lineno,
                            end_line=item.end_lineno,
                            signature=f"class {item.name}",
                        ),
                        hash=class_hash,
                        metadata={"docstring": ast.get_docstring(item)},
                    )
                    nodes.append(class_node)

                    # Extract methods within class
                    for sub in item.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            fn_lines = "\n".join(lines[sub.lineno - 1 : sub.end_lineno])
                            fn_hash = hashlib.sha256(fn_lines.encode("utf-8")).hexdigest()
                            args = [arg.arg for arg in sub.args.args]
                            sig = f"def {sub.name}({', '.join(args)})"
                            method_node = RegistryNode(
                                id=f"func:{rel_path}:{item.name}.{sub.name}",
                                name=f"{item.name}.{sub.name}",
                                type=NodeType.FUNCTION,
                                location=NodeLocation(
                                    path=rel_path,
                                    start_line=sub.lineno,
                                    end_line=sub.end_lineno,
                                    signature=sig,
                                ),
                                hash=fn_hash,
                                metadata={
                                    "parent_class": item.name,
                                    "is_async": isinstance(sub, ast.AsyncFunctionDef),
                                    "docstring": ast.get_docstring(sub),
                                },
                            )
                            nodes.append(method_node)

                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_lines = "\n".join(lines[item.lineno - 1 : item.end_lineno])
                    fn_hash = hashlib.sha256(fn_lines.encode("utf-8")).hexdigest()
                    args = [arg.arg for arg in item.args.args]
                    sig = f"def {item.name}({', '.join(args)})"
                    fn_node = RegistryNode(
                        id=f"func:{rel_path}:{item.name}",
                        name=item.name,
                        type=NodeType.FUNCTION,
                        location=NodeLocation(
                            path=rel_path,
                            start_line=item.lineno,
                            end_line=item.end_lineno,
                            signature=sig,
                        ),
                        hash=fn_hash,
                        metadata={
                            "is_async": isinstance(item, ast.AsyncFunctionDef),
                            "docstring": ast.get_docstring(item),
                        },
                    )
                    nodes.append(fn_node)
        except Exception:
            # Fall back to file node if syntax error in user file
            pass

    return nodes
