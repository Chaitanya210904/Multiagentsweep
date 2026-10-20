"""
Tool: scip
Source Code Intelligence Protocol (SCIP) indexer and symbol generator.
Generates canonical, language-aware SCIP symbols for files, classes, methods, and functions.
Format: <scheme> <package_name> <version> <descriptors...>
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from models.registry import NodeType, RegistryNode


class ScipTool:
    """Generates standardized SCIP symbols for code nodes."""

    name = "scip"
    description = "Generates Source Code Intelligence Protocol (SCIP) symbols and descriptors for code entities."

    def __init__(self, package_name: str = "multiagent", version: str = "0.1.0"):
        self.package_name = package_name
        self.version = version

    def generate_symbol(self, node: RegistryNode) -> str:
        """
        Constructs a canonical SCIP symbol string.
        Examples:
          - File:     scip-python multiagent 0.1.0 path/to/file.py/
          - Class:    scip-python multiagent 0.1.0 path/to/file.py/MyClass#
          - Function: scip-python multiagent 0.1.0 path/to/file.py/my_func().
          - Method:   scip-python multiagent 0.1.0 path/to/file.py/MyClass#my_method().
        """
        scheme = self._get_scheme(node.location.path)
        clean_path = node.location.path.strip().lstrip("./")

        if node.type == NodeType.FILE:
            descriptor = f"{clean_path}/"
        elif node.type == NodeType.CLASS:
            descriptor = f"{clean_path}/{node.name}#"
        elif node.type == NodeType.FUNCTION:
            if "." in node.name:
                parent, method = node.name.split(".", 1)
                descriptor = f"{clean_path}/{parent}#{method}()."
            else:
                descriptor = f"{clean_path}/{node.name}()."
        else:
            descriptor = f"{clean_path}/{node.name}"

        return f"{scheme} {self.package_name} {self.version} {descriptor}"

    def enrich_node(self, node: RegistryNode) -> RegistryNode:
        """Attaches the computed SCIP symbol and documentation summary to node metadata."""
        symbol = self.generate_symbol(node)
        node.metadata["scip_symbol"] = symbol
        return node

    def enrich_nodes(self, nodes: List[RegistryNode]) -> List[RegistryNode]:
        """Batch enriches a list of nodes with SCIP symbols."""
        for n in nodes:
            self.enrich_node(n)
        return nodes

    def _get_scheme(self, path: str) -> str:
        """Determines the SCIP scheme from file extension."""
        ext = Path(path).suffix.lower()
        if ext in (".py", ".pyi"):
            return "scip-python"
        elif ext in (".ts", ".tsx"):
            return "scip-typescript"
        elif ext in (".js", ".jsx", ".mjs"):
            return "scip-javascript"
        elif ext == ".go":
            return "scip-go"
        elif ext == ".java":
            return "scip-java"
        elif ext == ".sql":
            return "scip-sql"
        return "scip-code"
