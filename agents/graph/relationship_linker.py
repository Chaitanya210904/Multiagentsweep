"""
Agent 5: Relationship Linker (Layer: Graph).
Role: Graph agent 2: code edges.
Description: Creates calls, imports, inheritance and test-to-code edges.
Looks up both endpoints in the registry first; missing endpoints go to the unresolved queue, never guessed.
Access: read-only
"""

import ast
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agents.base import AgentMetadata, BaseAgent
from models.registry import (
    NodeType,
    RegistryKeeperInput,
    RegistryKeeperOutput,
    RegistryNode,
    UpdateProposal,
)
from models.relationship import (
    CodeEdge,
    EdgeType,
    RelationshipLinkerInput,
    RelationshipLinkerOutput,
    UnresolvedLink,
)
from storage.registry_store import CodeRegistryStore
from tools.graph_write_edge_tool import GraphWriteEdgeTool
from tools.registry_lookup_tool import RegistryLookupTool
from tools.registry_propose_tool import RegistryProposeTool


RELATIONSHIP_LINKER_METADATA = AgentMetadata(
    id="relationship_linker",
    name="Relationship Linker",
    layer="graph",
    role="Graph agent 2: code edges",
    description=(
        "Creates calls, imports, inheritance and test-to-code edges. "
        "Looks up both endpoints in the registry first; missing endpoints go to the unresolved queue, never guessed."
    ),
    access="read-only",
    model_tier="small",
    inputs=[
        "nodes_from_structure_mapper",
        "registry_lookups",
    ],
    outputs=[
        "verified_edges",
        "unresolved_link_queue",
        "registry_update_proposals",
    ],
    tools=[
        "registry.lookup",
        "registry.propose",
        "graph.write_edge",
    ],
    trigger="after Structure Mapper; parallel with Data & Service Mapper",
    optional=False,
)


class RelationshipLinker(BaseAgent):
    """
    The Relationship Linker Agent discovers and verifies code relationships.
    Enforces the zero-guessing invariant: both endpoints must be verified in the registry.
    Missing endpoints are routed to the unresolved link queue.
    """

    def __init__(
        self,
        store: CodeRegistryStore,
        repo_root: Optional[str] = None,
        metadata: Optional[AgentMetadata] = None,
    ):
        super().__init__(metadata=metadata or RELATIONSHIP_LINKER_METADATA)
        self.store = store
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

        # Tools (read-only safe)
        self.lookup_tool = RegistryLookupTool(store=self.store)
        self.propose_tool = RegistryProposeTool(source_agent=self.id)
        self.write_edge_tool = GraphWriteEdgeTool()

    def execute(self, inputs: Union[RelationshipLinkerInput, Dict[str, Any]]) -> RelationshipLinkerOutput:
        """
        Executes code relationship linking:
        1. Resolves input nodes from Structure Mapper or Registry
        2. Discovers inheritance relationships
        3. Discovers import relationships
        4. Discovers function/method call relationships
        5. Discovers test-to-code relationships
        6. Verifies both endpoints via registry.lookup; missing endpoints -> unresolved queue
        7. Packages verified edges into UpdateProposal objects for Registry Keeper
        """
        self.require_access("read-only")

        if isinstance(inputs, dict):
            inputs = RelationshipLinkerInput.model_validate(inputs)

        t0 = self.log_started({"repo_root": str(self.repo_root)})

        try:
            # 1. Resolve target nodes
            nodes = inputs.nodes_from_structure_mapper
            if not nodes:
                nodes = self.store.list_all(include_deleted=False)

            if inputs.shard_path:
                clean_shard = inputs.shard_path.strip().lstrip("./")
                nodes = [n for n in nodes if n.location.path.startswith(clean_shard)]

            enabled_types = set(inputs.edge_types or [
                EdgeType.INHERITANCE,
                EdgeType.IMPORTS,
                EdgeType.CALLS,
                EdgeType.TEST_TO_CODE,
            ])

            verified_edges: List[CodeEdge] = []
            unresolved_queue: List[UnresolvedLink] = []
            seen_edge_keys: Set[str] = set()

            # Group nodes for fast endpoint lookup
            nodes_by_file: Dict[str, List[RegistryNode]] = {}
            classes_by_name: Dict[str, List[RegistryNode]] = {}
            functions_by_name: Dict[str, List[RegistryNode]] = {}

            for node in nodes:
                nodes_by_file.setdefault(node.location.path, []).append(node)
                if node.type == NodeType.CLASS:
                    classes_by_name.setdefault(node.name, []).append(node)
                elif node.type == NodeType.FUNCTION:
                    # e.g. "func_name" or "Class.func_name"
                    short_name = node.name.split(".")[-1]
                    functions_by_name.setdefault(short_name, []).append(node)
                    functions_by_name.setdefault(node.name, []).append(node)

            # 2. Extract Inheritance Edges
            if EdgeType.INHERITANCE in enabled_types:
                self._extract_inheritance_edges(
                    nodes=nodes,
                    classes_by_name=classes_by_name,
                    verified_edges=verified_edges,
                    unresolved_queue=unresolved_queue,
                    seen_edge_keys=seen_edge_keys,
                )

            # 3. Extract Import Edges
            if EdgeType.IMPORTS in enabled_types:
                self._extract_import_edges(
                    nodes_by_file=nodes_by_file,
                    classes_by_name=classes_by_name,
                    verified_edges=verified_edges,
                    unresolved_queue=unresolved_queue,
                    seen_edge_keys=seen_edge_keys,
                )

            # 4. Extract Call Edges
            if EdgeType.CALLS in enabled_types:
                self._extract_call_edges(
                    nodes=nodes,
                    functions_by_name=functions_by_name,
                    verified_edges=verified_edges,
                    unresolved_queue=unresolved_queue,
                    seen_edge_keys=seen_edge_keys,
                )

            # 5. Extract Test-to-Code Edges
            if EdgeType.TEST_TO_CODE in enabled_types:
                self._extract_test_to_code_edges(
                    nodes_by_file=nodes_by_file,
                    verified_edges=verified_edges,
                    unresolved_queue=unresolved_queue,
                    seen_edge_keys=seen_edge_keys,
                )

            self.log_event(
                "edges.verified",
                f"Verified {len(verified_edges)} code edges across registry nodes",
                count=len(verified_edges),
            )
            if unresolved_queue:
                self.log_event(
                    "edges.unresolved",
                    f"Identified {len(unresolved_queue)} unverified links (saved to unresolved queue without guessing)",
                    count=len(unresolved_queue),
                )

            # 6. Formulate Update Proposals for Registry Keeper
            proposals = [self.propose_tool.propose_edge(edge) for edge in verified_edges]

            stats = {
                "total_nodes_analyzed": len(nodes),
                "verified_edges_count": len(verified_edges),
                "unresolved_links_count": len(unresolved_queue),
                "proposals_generated": len(proposals),
                "edges_by_type": {
                    etype.value: sum(1 for e in verified_edges if e.type == etype)
                    for etype in EdgeType
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self.log_completed(t0, stats)

            return RelationshipLinkerOutput(
                verified_edges=verified_edges,
                unresolved_link_queue=unresolved_queue,
                registry_update_proposals=proposals,
                stats=stats,
            )
        except Exception as e:
            self.log_failed(t0, e)
            raise

    def link_and_register(
        self,
        registry_keeper: Any,
        nodes_from_structure_mapper: Optional[List[RegistryNode]] = None,
        shard_path: Optional[str] = None,
    ) -> Tuple[RelationshipLinkerOutput, RegistryKeeperOutput]:
        """
        End-to-end linking workflow:
        1. Runs RelationshipLinker to discover and verify code edges
        2. Transmits verified edge proposals to RegistryKeeper
        3. Registry Keeper verifies endpoints again and attaches relations to registry nodes
        """
        inputs = RelationshipLinkerInput(
            nodes_from_structure_mapper=nodes_from_structure_mapper,
            shard_path=shard_path,
        )
        linker_out = self.execute(inputs)

        # Pass proposals to Registry Keeper
        keeper_in = RegistryKeeperInput(
            update_proposals_from_relationship_linker=linker_out.registry_update_proposals
        )
        keeper_out = registry_keeper.execute(keeper_in)

        return linker_out, keeper_out

    # --------------------------------------------------------------------------
    # Subroutines: 1. Inheritance Edges
    # --------------------------------------------------------------------------

    def _extract_inheritance_edges(
        self,
        nodes: List[RegistryNode],
        classes_by_name: Dict[str, List[RegistryNode]],
        verified_edges: List[CodeEdge],
        unresolved_queue: List[UnresolvedLink],
        seen_edge_keys: Set[str],
    ) -> None:
        """Finds class inheritance and maps to verified parent classes in the registry."""
        standard_builtins = {"object", "type", "dict", "list", "set", "tuple", "Exception", "BaseException"}

        for node in nodes:
            if node.type != NodeType.CLASS:
                continue

            bases = node.metadata.get("bases", [])
            for base_name in bases:
                if not base_name or base_name in standard_builtins:
                    continue

                # Strip qualifications if present (e.g. "package.BaseClass" -> "BaseClass")
                simple_base = base_name.split(".")[-1]

                # Strict registry lookup: verify target exists in registry
                target_candidates = classes_by_name.get(simple_base) or self.lookup_tool.find_by_type(NodeType.CLASS)
                matched_target: Optional[RegistryNode] = None

                for candidate in target_candidates:
                    if candidate.name == simple_base and candidate.id != node.id:
                        matched_target = candidate
                        break

                if matched_target:
                    # Verified in registry
                    edge_key = f"inheritance:{node.id}->{matched_target.id}"
                    if edge_key not in seen_edge_keys:
                        seen_edge_keys.add(edge_key)
                        edge = self.write_edge_tool.write_edge(
                            source_id=node.id,
                            target_id=matched_target.id,
                            edge_type=EdgeType.INHERITANCE,
                            line_number=node.location.start_line,
                            metadata={"base_name": base_name, "parent_class": matched_target.name},
                        )
                        verified_edges.append(edge)
                else:
                    # Target endpoint not in registry: never guess!
                    unresolved_queue.append(
                        UnresolvedLink(
                            source_id=node.id,
                            source_path=node.location.path,
                            raw_target=base_name,
                            edge_type=EdgeType.INHERITANCE,
                            line_number=node.location.start_line,
                            reason=f"Base class '{base_name}' not found in registry (may be an external library or standard type)",
                        )
                    )

    # --------------------------------------------------------------------------
    # Subroutines: 2. Import Edges
    # --------------------------------------------------------------------------

    def _extract_import_edges(
        self,
        nodes_by_file: Dict[str, List[RegistryNode]],
        classes_by_name: Dict[str, List[RegistryNode]],
        verified_edges: List[CodeEdge],
        unresolved_queue: List[UnresolvedLink],
        seen_edge_keys: Set[str],
    ) -> None:
        """Finds imports across files and resolves them to verified file or symbol nodes."""
        for file_path, file_nodes in nodes_by_file.items():
            file_node = next((n for n in file_nodes if n.type == NodeType.FILE), None)
            source_id = file_node.id if file_node else f"file:{file_path}"

            full_path = (self.repo_root / file_path).resolve()
            if not full_path.is_file():
                continue

            ext = full_path.suffix.lower()
            if ext in (".py", ".pyi"):
                self._parse_python_imports(
                    file_path=file_path,
                    source_id=source_id,
                    full_path=full_path,
                    classes_by_name=classes_by_name,
                    verified_edges=verified_edges,
                    unresolved_queue=unresolved_queue,
                    seen_edge_keys=seen_edge_keys,
                )
            elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs"):
                self._parse_javascript_imports(
                    file_path=file_path,
                    source_id=source_id,
                    full_path=full_path,
                    verified_edges=verified_edges,
                    unresolved_queue=unresolved_queue,
                    seen_edge_keys=seen_edge_keys,
                )

    def _parse_python_imports(
        self,
        file_path: str,
        source_id: str,
        full_path: Path,
        classes_by_name: Dict[str, List[RegistryNode]],
        verified_edges: List[CodeEdge],
        unresolved_queue: List[UnresolvedLink],
        seen_edge_keys: Set[str],
    ) -> None:
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=file_path)
        except Exception:
            return

        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    module_name = alias.name
                    target_node = self._resolve_python_module_to_node(module_name)
                    if target_node:
                        edge_key = f"imports:{source_id}->{target_node.id}"
                        if edge_key not in seen_edge_keys and source_id != target_node.id:
                            seen_edge_keys.add(edge_key)
                            edge = self.write_edge_tool.write_edge(
                                source_id=source_id,
                                target_id=target_node.id,
                                edge_type=EdgeType.IMPORTS,
                                line_number=stmt.lineno,
                                metadata={"module": module_name},
                            )
                            verified_edges.append(edge)
                    else:
                        unresolved_queue.append(
                            UnresolvedLink(
                                source_id=source_id,
                                source_path=file_path,
                                raw_target=module_name,
                                edge_type=EdgeType.IMPORTS,
                                line_number=stmt.lineno,
                                reason=f"Module '{module_name}' not found in registry (likely standard library or external package)",
                            )
                        )

            elif isinstance(stmt, ast.ImportFrom):
                module = stmt.module or ""
                target_file_node = self._resolve_python_module_to_node(module)

                for alias in stmt.names:
                    symbol_name = alias.name
                    target_symbol_node: Optional[RegistryNode] = None

                    # Try to resolve symbol directly in target file if target file was found
                    if target_file_node:
                        target_file_path = target_file_node.location.path
                        # Look for class or function with that name in the target file
                        nodes_in_file = self.lookup_tool.get_by_path(target_file_path)
                        for candidate in nodes_in_file:
                            if candidate.name == symbol_name:
                                target_symbol_node = candidate
                                break

                    if not target_symbol_node:
                        # Try finding class with that symbol name across registry
                        candidates = classes_by_name.get(symbol_name)
                        if candidates:
                            target_symbol_node = candidates[0]

                    # Pick destination: symbol node if resolved, else file node, else unresolved
                    final_target = target_symbol_node or target_file_node
                    if final_target:
                        edge_key = f"imports:{source_id}->{final_target.id}"
                        if edge_key not in seen_edge_keys and source_id != final_target.id:
                            seen_edge_keys.add(edge_key)
                            edge = self.write_edge_tool.write_edge(
                                source_id=source_id,
                                target_id=final_target.id,
                                edge_type=EdgeType.IMPORTS,
                                line_number=stmt.lineno,
                                metadata={"module": module, "symbol": symbol_name},
                            )
                            verified_edges.append(edge)
                    else:
                        full_symbol = f"{module}.{symbol_name}" if module else symbol_name
                        unresolved_queue.append(
                            UnresolvedLink(
                                source_id=source_id,
                                source_path=file_path,
                                raw_target=full_symbol,
                                edge_type=EdgeType.IMPORTS,
                                line_number=stmt.lineno,
                                reason=f"Imported symbol '{full_symbol}' could not be matched to an indexed registry node",
                            )
                        )

    def _resolve_python_module_to_node(self, module_name: str) -> Optional[RegistryNode]:
        """Maps Python dotted module (e.g. 'models.registry') to a real registered file node."""
        if not module_name:
            return None

        # Direct path conversion
        mod_as_path = module_name.replace(".", "/")
        candidates = [
            f"{mod_as_path}.py",
            f"{mod_as_path}/__init__.py",
            f"src/{mod_as_path}.py",
            f"src/{mod_as_path}/__init__.py",
        ]

        for cand in candidates:
            node = self.lookup_tool.get(f"file:{cand}")
            if node:
                return node
            nodes = self.lookup_tool.get_by_path(cand)
            if nodes:
                file_n = next((n for n in nodes if n.type == NodeType.FILE), None)
                if file_n:
                    return file_n

        return None

    def _parse_javascript_imports(
        self,
        file_path: str,
        source_id: str,
        full_path: Path,
        verified_edges: List[CodeEdge],
        unresolved_queue: List[UnresolvedLink],
        seen_edge_keys: Set[str],
    ) -> None:
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        import_pattern = re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""")
        for idx, line in enumerate(content.splitlines(), start=1):
            for match in import_pattern.finditer(line):
                raw_target = match.group(1) or match.group(2)
                if not raw_target:
                    continue

                # Relative import?
                if raw_target.startswith("."):
                    base_dir = Path(file_path).parent
                    resolved_rel = (base_dir / raw_target).as_posix()
                    # Check extensions
                    target_node = None
                    for ext in ("", ".js", ".ts", ".jsx", ".tsx", "/index.js", "/index.ts"):
                        cand = f"{resolved_rel}{ext}".lstrip("./")
                        target_node = self.lookup_tool.get(f"file:{cand}")
                        if target_node:
                            break
                    if target_node:
                        edge_key = f"imports:{source_id}->{target_node.id}"
                        if edge_key not in seen_edge_keys:
                            seen_edge_keys.add(edge_key)
                            edge = self.write_edge_tool.write_edge(
                                source_id=source_id,
                                target_id=target_node.id,
                                edge_type=EdgeType.IMPORTS,
                                line_number=idx,
                                metadata={"import_path": raw_target},
                            )
                            verified_edges.append(edge)
                    else:
                        unresolved_queue.append(
                            UnresolvedLink(
                                source_id=source_id,
                                source_path=file_path,
                                raw_target=raw_target,
                                edge_type=EdgeType.IMPORTS,
                                line_number=idx,
                                reason=f"Relative JS/TS import '{raw_target}' not found in registry",
                            )
                        )
                else:
                    unresolved_queue.append(
                        UnresolvedLink(
                            source_id=source_id,
                            source_path=file_path,
                            raw_target=raw_target,
                            edge_type=EdgeType.IMPORTS,
                            line_number=idx,
                            reason=f"External package '{raw_target}' not indexed in registry",
                        )
                    )

    # --------------------------------------------------------------------------
    # Subroutines: 3. Call Edges
    # --------------------------------------------------------------------------

    def _extract_call_edges(
        self,
        nodes: List[RegistryNode],
        functions_by_name: Dict[str, List[RegistryNode]],
        verified_edges: List[CodeEdge],
        unresolved_queue: List[UnresolvedLink],
        seen_edge_keys: Set[str],
    ) -> None:
        """Inspects function AST bodies to identify calls to other verified functions."""
        standard_builtins = {
            "print", "len", "range", "str", "int", "float", "bool", "dict", "list", "set",
            "tuple", "isinstance", "issubclass", "hasattr", "getattr", "setattr", "delattr",
            "open", "super", "next", "iter", "enumerate", "zip", "map", "filter", "any", "all",
            "min", "max", "sum", "sorted", "reversed", "id", "hash", "repr", "format",
        }

        # Cache parsed ASTs per file
        file_ast_cache: Dict[str, Optional[ast.AST]] = {}

        for node in nodes:
            if node.type != NodeType.FUNCTION:
                continue

            file_path = node.location.path
            full_path = (self.repo_root / file_path).resolve()
            if not full_path.is_file() or full_path.suffix.lower() not in (".py", ".pyi"):
                continue

            if file_path not in file_ast_cache:
                try:
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                    file_ast_cache[file_path] = ast.parse(content, filename=file_path)
                except Exception:
                    file_ast_cache[file_path] = None

            tree = file_ast_cache.get(file_path)
            if not tree:
                continue

            # Extract calls within this function's line range
            start_l = node.location.start_line or 1
            end_l = node.location.end_line or start_l

            calls_in_fn = self._find_ast_calls_in_range(tree, start_l, end_l)

            for call_name, lineno in calls_in_fn:
                if call_name in standard_builtins:
                    continue

                # Dissect simple name
                short_name = call_name.split(".")[-1]

                # 1. Look for matching method inside same class/file
                parent_class = node.metadata.get("parent_class")
                target_node: Optional[RegistryNode] = None

                if parent_class:
                    same_class_id = f"func:{file_path}:{parent_class}.{short_name}"
                    target_node = self.lookup_tool.get(same_class_id)

                if not target_node:
                    same_file_id = f"func:{file_path}:{short_name}"
                    target_node = self.lookup_tool.get(same_file_id)

                # 2. Look for single unambiguous match in functions_by_name
                if not target_node:
                    candidates = functions_by_name.get(short_name, [])
                    if len(candidates) == 1 and candidates[0].id != node.id:
                        target_node = candidates[0]
                    elif len(candidates) > 1:
                        # Ambiguous: never guess!
                        unresolved_queue.append(
                            UnresolvedLink(
                                source_id=node.id,
                                source_path=file_path,
                                raw_target=call_name,
                                edge_type=EdgeType.CALLS,
                                line_number=lineno,
                                reason=f"Ambiguous call '{call_name}' matched {len(candidates)} registry functions; skipped to avoid guessing",
                                candidate_matches=[c.id for c in candidates[:5]],
                            )
                        )
                        continue

                if target_node and target_node.id != node.id:
                    edge_key = f"calls:{node.id}->{target_node.id}"
                    if edge_key not in seen_edge_keys:
                        seen_edge_keys.add(edge_key)
                        edge = self.write_edge_tool.write_edge(
                            source_id=node.id,
                            target_id=target_node.id,
                            edge_type=EdgeType.CALLS,
                            line_number=lineno,
                            metadata={"call_name": call_name, "callee": target_node.name},
                        )
                        verified_edges.append(edge)
                elif not target_node:
                    unresolved_queue.append(
                        UnresolvedLink(
                            source_id=node.id,
                            source_path=file_path,
                            raw_target=call_name,
                            edge_type=EdgeType.CALLS,
                            line_number=lineno,
                            reason=f"Call target '{call_name}' not resolved in registry (external function, standard library, or dynamic call)",
                        )
                    )

    def _find_ast_calls_in_range(self, tree: ast.AST, start_line: int, end_line: int) -> List[Tuple[str, int]]:
        """Finds all ast.Call invocations located between start_line and end_line."""
        calls: List[Tuple[str, int]] = []

        class CallVisitor(ast.NodeVisitor):
            def visit_Call(self, call_node: ast.Call):
                lineno = getattr(call_node, "lineno", start_line)
                if start_line <= lineno <= end_line:
                    name = None
                    if isinstance(call_node.func, ast.Name):
                        name = call_node.func.id
                    elif isinstance(call_node.func, ast.Attribute):
                        name = call_node.func.attr
                    if name:
                        calls.append((name, lineno))
                self.generic_visit(call_node)

        CallVisitor().visit(tree)
        return calls

    # --------------------------------------------------------------------------
    # Subroutines: 4. Test-to-Code Edges
    # --------------------------------------------------------------------------

    def _extract_test_to_code_edges(
        self,
        nodes_by_file: Dict[str, List[RegistryNode]],
        verified_edges: List[CodeEdge],
        unresolved_queue: List[UnresolvedLink],
        seen_edge_keys: Set[str],
    ) -> None:
        """Links test files and test functions to the production code entities they test."""
        for file_path, file_nodes in nodes_by_file.items():
            if not self._is_test_file(file_path):
                continue

            test_file_node = next((n for n in file_nodes if n.type == NodeType.FILE), None)
            source_id = test_file_node.id if test_file_node else f"file:{file_path}"

            # Derive candidate production file path (e.g. "tests/test_registry_keeper.py" -> "agents/graph/registry_keeper.py")
            inferred_prod_name = Path(file_path).stem
            for prefix in ("test_", "tests_"):
                if inferred_prod_name.startswith(prefix):
                    inferred_prod_name = inferred_prod_name[len(prefix):]
                    break
            if inferred_prod_name.endswith("_test"):
                inferred_prod_name = inferred_prod_name[:-5]

            # Look for production files in the registry matching the name
            matched_prod_nodes = self.lookup_tool.find_by_type(NodeType.FILE)
            target_prod_file: Optional[RegistryNode] = None

            for prod_node in matched_prod_nodes:
                p_path = prod_node.location.path
                if not self._is_test_file(p_path) and Path(p_path).stem == inferred_prod_name:
                    target_prod_file = prod_node
                    break

            if target_prod_file:
                edge_key = f"test_to_code:{source_id}->{target_prod_file.id}"
                if edge_key not in seen_edge_keys:
                    seen_edge_keys.add(edge_key)
                    edge = self.write_edge_tool.write_edge(
                        source_id=source_id,
                        target_id=target_prod_file.id,
                        edge_type=EdgeType.TEST_TO_CODE,
                        metadata={"test_file": file_path, "tested_file": target_prod_file.location.path},
                    )
                    verified_edges.append(edge)

                # Link individual test functions to the production file / classes
                for node in file_nodes:
                    if node.type == NodeType.FUNCTION and node.name.startswith("test_"):
                        fn_edge_key = f"test_to_code:{node.id}->{target_prod_file.id}"
                        if fn_edge_key not in seen_edge_keys:
                            seen_edge_keys.add(fn_edge_key)
                            fn_edge = self.write_edge_tool.write_edge(
                                source_id=node.id,
                                target_id=target_prod_file.id,
                                edge_type=EdgeType.TEST_TO_CODE,
                                line_number=node.location.start_line,
                                metadata={"test_function": node.name},
                            )
                            verified_edges.append(fn_edge)
            else:
                unresolved_queue.append(
                    UnresolvedLink(
                        source_id=source_id,
                        source_path=file_path,
                        raw_target=inferred_prod_name,
                        edge_type=EdgeType.TEST_TO_CODE,
                        reason=f"No matching production file found in registry for test file '{file_path}' (target '{inferred_prod_name}')",
                    )
                )

    def _is_test_file(self, path: str) -> bool:
        """Identifies if a file is a test suite or test specification."""
        p = Path(path)
        parts = [part.lower() for part in p.parts]
        return (
            "tests" in parts
            or "test" in parts
            or p.name.startswith("test_")
            or p.name.endswith("_test.py")
            or p.name.endswith(".test.js")
            or p.name.endswith(".spec.ts")
            or p.name.endswith("_test.go")
        )
