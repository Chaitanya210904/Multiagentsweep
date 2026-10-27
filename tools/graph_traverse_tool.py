"""
Tool: graph.traverse
Bidirectional graph traversal engine for discovering upstream callers/importers/APIs/tests
and downstream callees/dependencies/tables/services with cycle detection and path recording.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from models.impact import PropagationPath, TraversalStep
from models.registry import NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore


@dataclass
class TraversalResult:
    """Result payload returned by graph.traverse."""
    root_node_ids: List[str]
    visited_node_ids: Set[str] = field(default_factory=set)
    upstream_node_ids: Set[str] = field(default_factory=set)
    downstream_node_ids: Set[str] = field(default_factory=set)
    nodes_by_depth: Dict[int, Set[str]] = field(default_factory=dict)
    paths: List[PropagationPath] = field(default_factory=list)
    max_depth_reached: int = 0


class GraphTraverseTool:
    """Graph traversal tool for dependency analysis and blast-radius calculation."""

    name = "graph.traverse"
    description = (
        "Traverses code and system dependency graphs bidirectionally to discover "
        "upstream callers/importers/APIs and downstream callees/tables/services."
    )

    def __init__(self, store: CodeRegistryStore):
        self._store = store

    def traverse(
        self,
        start_node_ids: List[str],
        direction: str = "both",  # "upstream", "downstream", "both"
        max_depth: int = 6,
        edge_types: Optional[List[str]] = None,
        record_paths: bool = True,
    ) -> TraversalResult:
        """
        Executes breadth-first search traversal starting from start_node_ids.
        - upstream: follows incoming_edges (callers, importers, APIs, tests)
        - downstream: follows outgoing_edges (callees, imports, tables, services)
        - both: explores both directions concurrently
        """
        result = TraversalResult(root_node_ids=list(start_node_ids))
        valid_edge_types = set(edge_types) if edge_types else None

        # Queue items: (current_node_id, current_depth, root_id, current_path_steps, direction_history)
        queue = deque()
        visited: Dict[Tuple[str, str], int] = {}  # (node_id, direction) -> shortest depth

        for start_id in start_node_ids:
            clean_id = start_id.strip()
            result.visited_node_ids.add(clean_id)
            result.nodes_by_depth.setdefault(0, set()).add(clean_id)

            if direction in ("upstream", "both"):
                queue.append((clean_id, 0, clean_id, [], "upstream"))
                visited[(clean_id, "upstream")] = 0
            if direction in ("downstream", "both"):
                queue.append((clean_id, 0, clean_id, [], "downstream"))
                visited[(clean_id, "downstream")] = 0

        while queue:
            current_id, depth, root_id, steps, curr_dir = queue.popleft()

            if depth >= max_depth:
                continue

            node = self._store.get(current_id)
            if not node:
                continue

            next_depth = depth + 1
            if next_depth > result.max_depth_reached:
                result.max_depth_reached = next_depth

            # 1. Upstream Traversal (incoming edges: callers, importers, APIs, tests)
            if curr_dir == "upstream":
                incoming_edges = node.metadata.get("incoming_edges", [])
                for edge in incoming_edges:
                    source_id = edge.get("source_id")
                    etype = edge.get("type", "unknown")

                    if not source_id:
                        continue
                    if valid_edge_types and etype not in valid_edge_types:
                        continue

                    step = TraversalStep(
                        source_id=source_id,
                        target_id=current_id,
                        edge_type=etype,
                        direction="upstream",
                        depth=next_depth,
                    )
                    new_steps = steps + [step] if record_paths else []

                    # Record path if leaf or progress
                    if record_paths and new_steps:
                        result.paths.append(
                            PropagationPath(
                                root_node_id=root_id,
                                leaf_node_id=source_id,
                                length=len(new_steps),
                                steps=new_steps,
                            )
                        )

                    # Cycle detection with depth optimization
                    prev_depth = visited.get((source_id, "upstream"))
                    if prev_depth is None or next_depth < prev_depth:
                        visited[(source_id, "upstream")] = next_depth
                        result.visited_node_ids.add(source_id)
                        result.upstream_node_ids.add(source_id)
                        result.nodes_by_depth.setdefault(next_depth, set()).add(source_id)
                        queue.append((source_id, next_depth, root_id, new_steps, "upstream"))

            # 2. Downstream Traversal (outgoing edges: callees, imports, tables, services)
            elif curr_dir == "downstream":
                outgoing_edges = node.metadata.get("outgoing_edges", [])
                for edge in outgoing_edges:
                    target_id = edge.get("target_id")
                    etype = edge.get("type", "unknown")

                    if not target_id:
                        continue
                    if valid_edge_types and etype not in valid_edge_types:
                        continue

                    step = TraversalStep(
                        source_id=current_id,
                        target_id=target_id,
                        edge_type=etype,
                        direction="downstream",
                        depth=next_depth,
                    )
                    new_steps = steps + [step] if record_paths else []

                    if record_paths and new_steps:
                        result.paths.append(
                            PropagationPath(
                                root_node_id=root_id,
                                leaf_node_id=target_id,
                                length=len(new_steps),
                                steps=new_steps,
                            )
                        )

                    prev_depth = visited.get((target_id, "downstream"))
                    if prev_depth is None or next_depth < prev_depth:
                        visited[(target_id, "downstream")] = next_depth
                        result.visited_node_ids.add(target_id)
                        result.downstream_node_ids.add(target_id)
                        result.nodes_by_depth.setdefault(next_depth, set()).add(target_id)
                        queue.append((target_id, next_depth, root_id, new_steps, "downstream"))

        return result
