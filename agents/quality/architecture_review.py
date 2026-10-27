"""
Agent 8: Architecture Review (Layer: Quality).
Role: Structure checker.
Description: Checks layers, boundaries, circular dependencies and coupling, and records ADRs.
Access: read-only
"""

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agents.base import AgentMetadata, BaseAgent
from models.architecture import (
    ADRRecord,
    ADRStatus,
    ArchitecturalViolation,
    ArchitectureReviewInput,
    ArchitectureReviewOutput,
    ArchitectureViolationType,
    CouplingMetric,
    ViolationSeverity,
)
from models.registry import NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore
from tools.graph_traverse_tool import GraphTraverseTool
from tools.registry_lookup_tool import RegistryLookupTool


ARCHITECTURE_REVIEW_METADATA = AgentMetadata(
    id="architecture_review",
    name="Architecture Review",
    layer="quality",
    role="Structure checker",
    description="Checks layers, boundaries, circular dependencies and coupling, and records ADRs.",
    access="read-only",
    model_tier="medium",
    inputs=[
        "graph_slice",
        "existing_adrs",
    ],
    outputs=[
        "violations",
        "coupling_metrics",
        "draft_adrs",
    ],
    tools=[
        "graph.traverse",
        "registry.lookup",
    ],
    trigger="when impact analysis flags structural change",
    optional=False,
)

DEFAULT_LAYER_HIERARCHY = [
    "core",
    "domain",
    "models",
    "storage",
    "tools",
    "services",
    "agents",
    "controllers",
    "api",
    "cli",
]


class ArchitectureReview(BaseAgent):
    """
    Architecture Review Agent enforces structural discipline across codebases:
    1. Layer Inversion Auditing: Enforces that lower architectural tiers never depend on higher tiers.
    2. Circular Dependency Detection: Identifies cyclic import/call loops using DFS back-edge detection.
    3. Package Coupling Metrics: Computes Afferent (Ca), Efferent (Ce), and Instability (I).
    4. ADR Ingestion & Verification: Ingests existing ADRs and flags violations against recorded decisions.
    5. Automated ADR Drafting: Formulates Michael Nygard-compliant draft ADRs to resolve detected anti-patterns.
    """

    def __init__(
        self,
        store: CodeRegistryStore,
        repo_root: Optional[str] = None,
        metadata: Optional[AgentMetadata] = None,
    ):
        super().__init__(metadata=metadata or ARCHITECTURE_REVIEW_METADATA.model_copy(deep=True))
        self.store = store
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

        # Tools
        self.lookup_tool = RegistryLookupTool(store=self.store)
        self.traverse_tool = GraphTraverseTool(store=self.store)

    def execute(self, inputs: Union[ArchitectureReviewInput, Dict[str, Any]]) -> ArchitectureReviewOutput:
        """
        Executes architectural inspection:
        - Resolves scoped nodes (graph_slice or all active registry nodes)
        - Ingests and verifies against existing ADRs
        - Audits layer inversions and boundary violations
        - Detects circular dependency chains
        - Calculates Robert C. Martin coupling metrics (Ca, Ce, Instability)
        - Formulates draft ADR proposals for observed structural defects
        - Computes Clean Architecture health score
        """
        self.require_access("read-only")

        if isinstance(inputs, dict):
            inputs = ArchitectureReviewInput.model_validate(inputs)

        # 1. Resolve scoped nodes in the graph slice
        scoped_nodes = self._resolve_graph_slice(inputs.graph_slice)
        layer_order = inputs.layer_hierarchy or DEFAULT_LAYER_HIERARCHY

        t0 = self.log_started({
            "scoped_nodes_count": len(scoped_nodes),
            "check_cycles": inputs.check_cycles,
            "max_coupling_threshold": inputs.max_coupling_threshold,
        })

        try:
            # 2. Ingest existing ADRs
            existing_adrs = self._ingest_existing_adrs(inputs.existing_adrs)

            # 3. Check Layer & Boundary Violations
            layer_violations = self._check_layer_violations(scoped_nodes, layer_order)

            # 4. Check ADR Compliance
            adr_violations = self._check_adr_compliance(scoped_nodes, existing_adrs)

            # 5. Check Circular Dependencies
            cycle_violations: List[ArchitecturalViolation] = []
            if inputs.check_cycles:
                cycle_violations = self._detect_circular_dependencies(scoped_nodes)

            # 6. Calculate Coupling & Instability Metrics
            coupling_metrics, coupling_violations = self._calculate_coupling_metrics(
                scoped_nodes=scoped_nodes,
                threshold=inputs.max_coupling_threshold,
            )

            # Aggregate all violations
            all_violations = layer_violations + adr_violations + cycle_violations + coupling_violations

            # 7. Formulate Draft ADRs for unresolved architectural problems
            draft_adrs = self._draft_adrs_from_violations(all_violations, coupling_metrics, existing_adrs)

            # 8. Compute Clean Architecture Score (0.0 to 100.0)
            health_score = self._compute_clean_architecture_score(
                violations=all_violations,
                coupling_metrics=coupling_metrics,
            )

            stats = {
                "nodes_reviewed": len(scoped_nodes),
                "total_violations": len(all_violations),
                "layer_inversions": len(layer_violations),
                "circular_dependencies": len(cycle_violations),
                "coupling_hotspots": sum(1 for m in coupling_metrics if m.is_hotspot),
                "existing_adrs_loaded": len(existing_adrs),
                "draft_adrs_generated": len(draft_adrs),
                "clean_architecture_score": health_score,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self.log_event(
                "architecture.reviewed",
                f"Architecture Review completed. Health Score: {health_score}/100.0. "
                f"Found {len(all_violations)} violations ({len(layer_violations)} layer, "
                f"{len(cycle_violations)} cycles, {stats['coupling_hotspots']} hotspots). "
                f"Drafted {len(draft_adrs)} ADRs.",
                **stats,
            )

            self.log_completed(t0, stats)

            return ArchitectureReviewOutput(
                violations=all_violations,
                coupling_metrics=coupling_metrics,
                draft_adrs=draft_adrs,
                clean_architecture_score=health_score,
                summary=stats,
            )
        except Exception as e:
            self.log_failed(t0, e)
            raise

    # --------------------------------------------------------------------------
    # Subroutines: 1. Graph Slice Resolution
    # --------------------------------------------------------------------------

    def _resolve_graph_slice(
        self,
        graph_slice: Optional[List[Union[str, RegistryNode]]],
    ) -> List[RegistryNode]:
        """Resolves node identifiers or defaults to all active registered nodes."""
        if not graph_slice:
            return self.store.list_all(include_deleted=False)

        resolved: List[RegistryNode] = []
        for item in graph_slice:
            if isinstance(item, RegistryNode):
                resolved.append(item)
            elif isinstance(item, str):
                node = self.lookup_tool.get(item.strip())
                if node:
                    resolved.append(node)
        return resolved

    # --------------------------------------------------------------------------
    # Subroutines: 2. Layer & Boundary Violations
    # --------------------------------------------------------------------------

    def _check_layer_violations(
        self,
        nodes: List[RegistryNode],
        layer_order: List[str],
    ) -> List[ArchitecturalViolation]:
        """
        Enforces Layer Inversion Rules:
        Lower layers (e.g. models, core) must not depend on higher layers (e.g. agents, cli).
        """
        violations: List[ArchitecturalViolation] = []
        layer_rank: Dict[str, int] = {name.lower(): idx for idx, name in enumerate(layer_order)}

        for node in nodes:
            src_layer = self._extract_layer_from_node(node)
            if not src_layer or src_layer not in layer_rank:
                continue

            src_rank = layer_rank[src_layer]

            outgoing = node.metadata.get("outgoing_edges", [])
            for edge in outgoing:
                target_id = edge.get("target_id")
                if not target_id:
                    continue

                target_node = self.lookup_tool.get(target_id)
                if not target_node:
                    continue

                tgt_layer = self._extract_layer_from_node(target_node)
                if not tgt_layer or tgt_layer not in layer_rank:
                    continue

                tgt_rank = layer_rank[tgt_layer]

                # If source is at a lower tier and imports/calls a higher tier -> Layer Inversion
                if src_rank < tgt_rank:
                    vid = f"violation:layer:{node.id}->{target_id}"
                    msg = (
                        f"Layer Inversion: Lower-tier module '{node.id}' (layer: '{src_layer}', rank {src_rank}) "
                        f"directly depends on higher-tier module '{target_id}' (layer: '{tgt_layer}', rank {tgt_rank})."
                    )
                    remediation = (
                        f"Invert dependency: introduce an interface or callback in '{src_layer}', "
                        f"and have '{tgt_layer}' implement it (Dependency Inversion Principle)."
                    )
                    violations.append(
                        ArchitecturalViolation(
                            id=vid,
                            type=ArchitectureViolationType.LAYER_INVERSION,
                            severity=ViolationSeverity.ERROR,
                            source_node_id=node.id,
                            target_node_id=target_id,
                            rule_name="Layer Hierarchy Inversion Prevention",
                            message=msg,
                            remediation=remediation,
                        )
                    )

        return violations

    def _extract_layer_from_node(self, node: RegistryNode) -> Optional[str]:
        """Extracts the architectural layer classification from a node's path or metadata."""
        if "layer" in node.metadata:
            return str(node.metadata["layer"]).lower()

        path = node.location.path.lower().replace("\\", "/")
        parts = [p for p in path.split("/") if p and p != "."]

        for part in parts:
            clean = part.replace(".py", "").replace(".js", "").replace(".ts", "")
            if clean in DEFAULT_LAYER_HIERARCHY:
                return clean
            # Partial prefix matches (e.g., 'controller' -> 'controllers')
            if clean.startswith("controller"):
                return "controllers"
            if clean.startswith("service"):
                return "services"
            if clean.startswith("model"):
                return "models"
            if clean.startswith("route") or clean.startswith("api"):
                return "api"

        return None

    # --------------------------------------------------------------------------
    # Subroutines: 3. Circular Dependency Detection
    # --------------------------------------------------------------------------

    def _detect_circular_dependencies(
        self,
        nodes: List[RegistryNode],
    ) -> List[ArchitecturalViolation]:
        """
        Finds cyclic dependency loops using Depth-First Search (DFS) with cycle back-edges.
        """
        violations: List[ArchitecturalViolation] = []
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        path: List[str] = []
        reported_cycles: Set[frozenset] = set()

        node_map: Dict[str, RegistryNode] = {n.id: n for n in nodes}

        def dfs(current_id: str) -> None:
            visited.add(current_id)
            rec_stack.add(current_id)
            path.append(current_id)

            curr_node = node_map.get(current_id) or self.lookup_tool.get(current_id)
            if curr_node:
                outgoing = curr_node.metadata.get("outgoing_edges", [])
                for edge in outgoing:
                    neighbor_id = edge.get("target_id")
                    if not neighbor_id:
                        continue

                    if neighbor_id not in visited:
                        dfs(neighbor_id)
                    elif neighbor_id in rec_stack:
                        # Cycle found!
                        cycle_start_idx = path.index(neighbor_id)
                        cycle_chain = path[cycle_start_idx:] + [neighbor_id]
                        cycle_set = frozenset(cycle_chain)

                        if cycle_set not in reported_cycles and len(cycle_chain) > 2:
                            reported_cycles.add(cycle_set)
                            vid = f"violation:cycle:{neighbor_id}->{current_id}"
                            msg = f"Circular dependency cycle detected: {' -> '.join(cycle_chain)}"
                            remediation = (
                                f"Break circular loop between '{neighbor_id}' and '{current_id}'. "
                                f"Extract shared structures into a separate lower-tier module or use events."
                            )
                            violations.append(
                                ArchitecturalViolation(
                                    id=vid,
                                    type=ArchitectureViolationType.CIRCULAR_DEPENDENCY,
                                    severity=ViolationSeverity.CRITICAL,
                                    source_node_id=current_id,
                                    target_node_id=neighbor_id,
                                    rule_name="Circular Dependency Prevention",
                                    message=msg,
                                    cycle_path=cycle_chain,
                                    remediation=remediation,
                                )
                            )

            rec_stack.remove(current_id)
            path.pop()

        for node in nodes:
            if node.id not in visited:
                dfs(node.id)

        return violations

    # --------------------------------------------------------------------------
    # Subroutines: 4. Coupling & Instability Metrics
    # --------------------------------------------------------------------------

    def _calculate_coupling_metrics(
        self,
        scoped_nodes: List[RegistryNode],
        threshold: int,
    ) -> Tuple[List[CouplingMetric], List[ArchitecturalViolation]]:
        """
        Computes Afferent (Ca), Efferent (Ce), and Instability (I = Ce / (Ca + Ce)).
        Flags modules exceeding max_coupling_threshold as excessive coupling hotspots.
        """
        metrics: List[CouplingMetric] = []
        violations: List[ArchitecturalViolation] = []

        # Aggregate by file or class entity
        entity_ca: Dict[str, Set[str]] = defaultdict(set)
        entity_ce: Dict[str, Set[str]] = defaultdict(set)

        for node in scoped_nodes:
            entity_key = f"file:{node.location.path}"

            # Incoming callers (Ca)
            for in_edge in node.metadata.get("incoming_edges", []):
                src = in_edge.get("source_id")
                if src and src != node.id:
                    entity_ca[entity_key].add(src)

            # Outgoing dependencies (Ce)
            for out_edge in node.metadata.get("outgoing_edges", []):
                tgt = out_edge.get("target_id")
                if tgt and tgt != node.id:
                    entity_ce[entity_key].add(tgt)

        all_keys = set(entity_ca.keys()).union(set(entity_ce.keys()))

        for key in sorted(all_keys):
            ca = len(entity_ca[key])
            ce = len(entity_ce[key])
            total = ca + ce
            instability = round(ce / total, 3) if total > 0 else 0.0

            is_hotspot = ce > threshold
            risk = "high" if is_hotspot or ce > (threshold * 0.8) else ("medium" if ce > (threshold * 0.5) else "low")

            cm = CouplingMetric(
                entity_id=key,
                afferent_coupling=ca,
                efferent_coupling=ce,
                instability=instability,
                is_hotspot=is_hotspot,
                risk_level=risk,
            )
            metrics.append(cm)

            if is_hotspot:
                vid = f"violation:coupling:{key}"
                msg = (
                    f"Excessive Coupling Hotspot: Entity '{key}' has {ce} outgoing dependencies "
                    f"(limit is {threshold}), instability I={instability}."
                )
                remediation = (
                    f"Decompose '{key}' into smaller cohesive components. Apply Facade or Mediator pattern."
                )
                violations.append(
                    ArchitecturalViolation(
                        id=vid,
                        type=ArchitectureViolationType.EXCESSIVE_COUPLING,
                        severity=ViolationSeverity.WARNING,
                        source_node_id=key,
                        rule_name="Modular Coupling Bound",
                        message=msg,
                        remediation=remediation,
                    )
                )

        return metrics, violations

    # --------------------------------------------------------------------------
    # Subroutines: 5. ADR Ingestion & Rule Compliance
    # --------------------------------------------------------------------------

    def _ingest_existing_adrs(
        self,
        adr_inputs: List[Union[str, Path, ADRRecord, Dict[str, Any]]],
    ) -> List[ADRRecord]:
        """Loads and parses existing ADR markdown documents or models."""
        adrs: List[ADRRecord] = []

        # Auto-discover local ADR directories if no ADRs are passed explicitly
        to_process = list(adr_inputs)
        if not to_process:
            candidate_dirs = [
                self.repo_root / "docs" / "adr",
                self.repo_root / "docs" / "adrs",
                self.repo_root / "adrs",
            ]
            for adr_dir in candidate_dirs:
                if adr_dir.exists() and adr_dir.is_dir():
                    to_process.extend(list(adr_dir.glob("*.md")))

        for item in to_process:
            if isinstance(item, ADRRecord):
                adrs.append(item)
            elif isinstance(item, dict):
                try:
                    adrs.append(ADRRecord.model_validate(item))
                except Exception:
                    continue
            elif isinstance(item, (str, Path)):
                p = Path(item)
                if not p.is_absolute():
                    p = self.repo_root / p
                if p.exists() and p.is_file() and p.suffix.lower() == ".md":
                    parsed = self._parse_adr_markdown(p)
                    if parsed:
                        adrs.append(parsed)

        return adrs

    def _parse_adr_markdown(self, path: Path) -> Optional[ADRRecord]:
        """Parses a markdown Architecture Decision Record conforming to Michael Nygard template."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return None

        # Title
        title_match = re.search(r"^#\s+(?:ADR-?\d+[:\s]+)?(.+)$", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else path.stem

        # Extract ID (e.g. ADR-001 or filename)
        id_match = re.search(r"(ADR-?\d+)", path.name, re.IGNORECASE)
        adr_id = id_match.group(1).upper() if id_match else f"ADR-{path.stem}"

        # Status
        status = ADRStatus.PROPOSED
        status_match = re.search(r"##\s*Status\s*\n+([a-zA-Z]+)", content, re.IGNORECASE)
        if status_match:
            st = status_match.group(1).lower()
            if st in [s.value for s in ADRStatus]:
                status = ADRStatus(st)

        # Context
        context_match = re.search(r"##\s*Context\s*\n+([^#]+)", content, re.IGNORECASE)
        context = context_match.group(1).strip() if context_match else ""

        # Decision
        decision_match = re.search(r"##\s*Decision\s*\n+([^#]+)", content, re.IGNORECASE)
        decision = decision_match.group(1).strip() if decision_match else ""

        # Consequences
        consequences = []
        cons_match = re.search(r"##\s*Consequences\s*\n+([^#]+)", content, re.IGNORECASE)
        if cons_match:
            lines = cons_match.group(1).strip().splitlines()
            consequences = [l.strip().lstrip("*- ").strip() for l in lines if l.strip()]

        return ADRRecord(
            id=adr_id,
            title=title,
            status=status,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            context=context,
            decision=decision,
            consequences=consequences,
            affected_nodes=[],
            source_path=str(path),
        )

    def _check_adr_compliance(
        self,
        nodes: List[RegistryNode],
        existing_adrs: List[ADRRecord],
    ) -> List[ArchitecturalViolation]:
        """Validates graph edges against established ADR decisions."""
        violations: List[ArchitecturalViolation] = []

        for adr in existing_adrs:
            if adr.status != ADRStatus.ACCEPTED:
                continue

            dec_lower = adr.decision.lower()

            # Rule heuristic: Check for prohibited patterns in decision text
            # e.g., "do not import X from Y" or "forbid direct calls from X to Y"
            forbidden_matches = re.findall(r"forbid(?:s)?\s+([a-zA-Z0-9_]+)\s+(?:from|to)\s+([a-zA-Z0-9_]+)", dec_lower)
            for src_pat, tgt_pat in forbidden_matches:
                for node in nodes:
                    if src_pat in node.id.lower() or src_pat in node.location.path.lower():
                        for edge in node.metadata.get("outgoing_edges", []):
                            target_id = edge.get("target_id", "")
                            if tgt_pat in target_id.lower():
                                vid = f"violation:adr:{adr.id}:{node.id}->{target_id}"
                                msg = (
                                    f"ADR Compliance Breach: Call from '{node.id}' to '{target_id}' "
                                    f"violates accepted decision in {adr.id} ('{adr.title}')."
                                )
                                remediation = f"Consult {adr.id} and decouple '{node.id}' from '{target_id}'."
                                violations.append(
                                    ArchitecturalViolation(
                                        id=vid,
                                        type=ArchitectureViolationType.FORBIDDEN_DEPENDENCY,
                                        severity=ViolationSeverity.ERROR,
                                        source_node_id=node.id,
                                        target_node_id=target_id,
                                        rule_name=f"ADR Compliance: {adr.id}",
                                        message=msg,
                                        remediation=remediation,
                                    )
                                )

        return violations

    # --------------------------------------------------------------------------
    # Subroutines: 6. Automated ADR Drafting
    # --------------------------------------------------------------------------

    def _draft_adrs_from_violations(
        self,
        violations: List[ArchitecturalViolation],
        coupling_metrics: List[CouplingMetric],
        existing_adrs: List[ADRRecord],
    ) -> List[ADRRecord]:
        """
        Formulates formal draft ADRs for recurring architectural defects or high-risk coupling hotspots.
        """
        drafts: List[ADRRecord] = []
        next_idx = len(existing_adrs) + 1
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. ADR for Layer Inversions
        layer_inversions = [v for v in violations if v.type == ArchitectureViolationType.LAYER_INVERSION]
        if layer_inversions:
            adr_id = f"ADR-{next_idx:03d}"
            next_idx += 1
            affected = sorted(list({v.source_node_id for v in layer_inversions} | {v.target_node_id for v in layer_inversions if v.target_node_id}))
            drafts.append(
                ADRRecord(
                    id=adr_id,
                    title="Enforce Strict Architectural Layer Decoupling and Dependency Inversion",
                    status=ADRStatus.PROPOSED,
                    date=today,
                    context=(
                        f"Architecture review discovered {len(layer_inversions)} layer inversion violations where "
                        f"lower-level foundational tiers depend directly on outer orchestration tiers."
                    ),
                    decision=(
                        "Forbid lower-tier packages (e.g. models, core) from importing or referencing higher tiers. "
                        "All cross-tier coordination must be mediated through abstract protocols and interfaces."
                    ),
                    consequences=[
                        "Prevents architectural rot and untangles circular component dependencies.",
                        "Enables independent testing of foundational domain logic.",
                        "Requires refactoring existing inverted calls into abstract interfaces.",
                    ],
                    affected_nodes=affected,
                )
            )

        # 2. ADR for Circular Dependencies
        cycles = [v for v in violations if v.type == ArchitectureViolationType.CIRCULAR_DEPENDENCY]
        if cycles:
            adr_id = f"ADR-{next_idx:03d}"
            next_idx += 1
            affected = sorted(list({v.source_node_id for v in cycles} | {v.target_node_id for v in cycles if v.target_node_id}))
            drafts.append(
                ADRRecord(
                    id=adr_id,
                    title="Eliminate Circular Dependencies via Intermediate Extraction or Event Dispatch",
                    status=ADRStatus.PROPOSED,
                    date=today,
                    context=(
                        f"Architecture review detected {len(cycles)} cyclic dependency loop(s). "
                        f"Circular dependencies impede tree-shaking, prevent module isolation, and induce runtime import errors."
                    ),
                    decision=(
                        "Refactor cyclic dependencies by extracting shared types into independent sibling modules "
                        "or replacing synchronous direct calls with event-driven notifications."
                    ),
                    consequences=[
                        "Modules become cleanly DAG-ordered (Directed Acyclic Graph).",
                        "Eliminates circular import runtime panics.",
                        "Requires small restructuring of shared types.",
                    ],
                    affected_nodes=affected,
                )
            )

        # 3. ADR for Excessive Coupling Hotspots
        hotspots = [m for m in coupling_metrics if m.is_hotspot]
        if hotspots:
            adr_id = f"ADR-{next_idx:03d}"
            next_idx += 1
            drafts.append(
                ADRRecord(
                    id=adr_id,
                    title="Decompose High-Efferent Coupling Hotspots into Focused Facades",
                    status=ADRStatus.PROPOSED,
                    date=today,
                    context=(
                        f"Detected {len(hotspots)} module(s) exceeding maximum efferent coupling bounds. "
                        f"These 'God Modules' compromise maintainability and create fragile change ripple effects."
                    ),
                    decision=(
                        "Establish module-level coupling limits (Ce <= 15). Decompose monolithic modules into "
                        "single-responsibility collaborators behind a clean Facade interface."
                    ),
                    consequences=[
                        "Significantly reduces blast radius of changes.",
                        "Improves cognitive clarity and modular testability.",
                    ],
                    affected_nodes=[h.entity_id for h in hotspots],
                )
            )

        return drafts

    # --------------------------------------------------------------------------
    # Subroutines: 7. Clean Architecture Scoring
    # --------------------------------------------------------------------------

    def _compute_clean_architecture_score(
        self,
        violations: List[ArchitecturalViolation],
        coupling_metrics: List[CouplingMetric],
    ) -> float:
        """
        Computes calibrated Clean Architecture score from 0.0 to 100.0:
        Base: 100.0
        - Layer Inversion: -15.0 each
        - Circular Dependency: -12.0 each
        - ADR Breach: -10.0 each
        - Coupling Hotspot: -5.0 each
        """
        score = 100.0

        for v in violations:
            if v.type == ArchitectureViolationType.LAYER_INVERSION:
                score -= 15.0
            elif v.type == ArchitectureViolationType.CIRCULAR_DEPENDENCY:
                score -= 12.0
            elif v.type == ArchitectureViolationType.FORBIDDEN_DEPENDENCY:
                score -= 10.0
            elif v.type == ArchitectureViolationType.EXCESSIVE_COUPLING:
                score -= 5.0

        return max(0.0, min(100.0, round(score, 1)))
