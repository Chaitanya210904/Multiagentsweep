"""
Tool: graph.write_edge
Creates, validates, and records verified code edges connecting code entities in the knowledge graph.
Enforces edge validation rules before edges are packaged for registration.
"""

from typing import Any, Dict, List, Optional
from models.relationship import CodeEdge, EdgeType


class GraphWriteEdgeTool:
    """Tool for creating, validating, and recording graph edges."""

    name = "graph.write_edge"
    description = (
        "Creates and records verified code edges (calls, imports, inheritance, test-to-code) "
        "between validated endpoints."
    )

    def __init__(self):
        self._recorded_edges: Dict[str, CodeEdge] = {}

    def write_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        line_number: Optional[int] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CodeEdge:
        """
        Validates and records a verified edge.
        Returns the constructed CodeEdge instance.
        """
        if not source_id or not target_id:
            raise ValueError("Both source_id and target_id are required to create a graph edge.")

        if source_id == target_id and edge_type == EdgeType.INHERITANCE:
            raise ValueError(f"Self-inheritance detected for node '{source_id}'.")

        edge = CodeEdge.create(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            line_number=line_number,
            confidence=confidence,
            metadata=metadata or {},
        )

        self._recorded_edges[edge.id] = edge
        return edge

    def get_edge(self, edge_id: str) -> Optional[CodeEdge]:
        """Retrieve an edge by ID."""
        return self._recorded_edges.get(edge_id)

    def list_edges(self, edge_type: Optional[EdgeType] = None) -> List[CodeEdge]:
        """List all recorded edges, optionally filtered by edge type."""
        if edge_type:
            return [e for e in self._recorded_edges.values() if e.type == edge_type]
        return list(self._recorded_edges.values())

    def clear(self) -> None:
        """Reset recorded edges."""
        self._recorded_edges.clear()
