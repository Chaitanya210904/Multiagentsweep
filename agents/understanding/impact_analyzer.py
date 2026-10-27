"""
Agent 7: Impact Analyzer (Layer: Understanding).
Role: Blast-radius finder.
Description: Walks the graph from changed nodes to find callers, callees and tests, then wakes only the affected agents.
Access: read-only
"""

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from agents.base import AgentMetadata, BaseAgent
from models.impact import (
    AffectedEntities,
    ImpactAnalyzerInput,
    ImpactAnalyzerOutput,
    ImpactSeverity,
    PropagationPath,
    WakeDirective,
)
from models.registry import NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore
from tools.graph_traverse_tool import GraphTraverseTool
from tools.registry_lookup_tool import RegistryLookupTool


IMPACT_ANALYZER_METADATA = AgentMetadata(
    id="impact_analyzer",
    name="Impact Analyzer",
    layer="understanding",
    role="Blast-radius finder",
    description=(
        "Walks the graph from changed nodes to find callers, callees and tests, "
        "then wakes only the affected agents."
    ),
    access="read-only",
    model_tier="small",
    inputs=[
        "changed_nodes",
        "graph",
        "registry",
    ],
    outputs=[
        "blast_radius_score",
        "affected_nodes_and_services",
        "agents_to_wake",
    ],
    tools=[
        "graph.traverse",
        "registry.lookup",
    ],
    trigger="after graph is refreshed on a change",
    optional=False,
)


class ImpactAnalyzer(BaseAgent):
    """
    The Impact Analyzer Agent is the primary blast-radius engine of the system.
    Starting from modified or added nodes, it traverses the knowledge graph bidirectionally,
    measures risk severity, identifies affected callers, callees, APIs, tables, and test suites,
    and selectively determines which downstream agents must be awakened.
    """

    def __init__(
        self,
        store: CodeRegistryStore,
        repo_root: Optional[str] = None,
        metadata: Optional[AgentMetadata] = None,
    ):
        super().__init__(metadata=metadata or IMPACT_ANALYZER_METADATA.model_copy(deep=True))
        self.store = store
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

        # Tools
        self.lookup_tool = RegistryLookupTool(store=self.store)
        self.traverse_tool = GraphTraverseTool(store=self.store)

    def execute(self, inputs: Union[ImpactAnalyzerInput, Dict[str, Any]]) -> ImpactAnalyzerOutput:
        """
        Executes impact analysis and selective agent wake calculation:
        1. Normalizes changed root nodes
        2. Traverses knowledge graph bidirectionally via graph.traverse
        3. Identifies callers, callees, APIs, tables, services, and tests
        4. Calculates quantitative blast-radius score (0.0 to 100.0)
        5. Formulates targeted WakeDirectives for affected downstream agents
        """
        self.require_access("read-only")

        if isinstance(inputs, dict):
            inputs = ImpactAnalyzerInput.model_validate(inputs)

        # Normalize changed node IDs
        root_node_ids: List[str] = []
        for item in inputs.changed_nodes:
            if isinstance(item, RegistryNode):
                root_node_ids.append(item.id)
            elif isinstance(item, str):
                root_node_ids.append(item.strip())

        t0 = self.log_started({
            "changed_nodes_count": len(root_node_ids),
            "max_depth": inputs.max_depth,
        })

        try:
            # 1. Execute graph traversal
            traversal = self.traverse_tool.traverse(
                start_node_ids=root_node_ids,
                direction="both",
                max_depth=inputs.max_depth,
                edge_types=inputs.edge_types,
                record_paths=inputs.include_paths,
            )

            # 2. Categorize all affected entities
            affected = self._categorize_affected_entities(
                root_ids=root_node_ids,
                visited_ids=traversal.visited_node_ids,
                upstream_ids=traversal.upstream_node_ids,
                downstream_ids=traversal.downstream_node_ids,
                max_depth=traversal.max_depth_reached,
                paths=traversal.paths,
            )

            # 3. Calculate Blast Radius Score
            blast_score, severity = self._calculate_blast_radius_score(affected)

            # 4. Formulate Selective Wake Directives
            agents_to_wake = self._determine_agents_to_wake(
                affected=affected,
                blast_score=blast_score,
                severity=severity,
            )

            self.log_event(
                "impact.evaluated",
                f"Evaluated blast radius: {blast_score}/100.0 ({severity.value.upper()}). "
                f"Impacts {len(affected.all_affected_node_ids)} nodes, {len(affected.affected_apis)} APIs, "
                f"{len(affected.affected_tables)} tables, {len(affected.tests_to_run)} tests. "
                f"Waking {len(agents_to_wake)} agents.",
                blast_radius_score=blast_score,
                severity=severity.value,
                affected_nodes_count=len(affected.all_affected_node_ids),
                agents_to_wake_count=len(agents_to_wake),
            )

            stats = {
                "changed_nodes_analyzed": len(root_node_ids),
                "total_affected_nodes": len(affected.all_affected_node_ids),
                "max_depth_reached": affected.max_propagation_depth,
                "callers_count": len(affected.callers),
                "callees_count": len(affected.callees),
                "apis_affected": len(affected.affected_apis),
                "tables_affected": len(affected.affected_tables),
                "services_affected": len(affected.affected_services),
                "tests_to_run_count": len(affected.tests_to_run),
                "untested_nodes_count": len(affected.untested_nodes),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self.log_completed(t0, stats)

            return ImpactAnalyzerOutput(
                blast_radius_score=blast_score,
                severity=severity,
                affected_nodes_and_services=affected,
                agents_to_wake=agents_to_wake,
                stats=stats,
            )
        except Exception as e:
            self.log_failed(t0, e)
            raise

    # --------------------------------------------------------------------------
    # Subroutines: 1. Categorization
    # --------------------------------------------------------------------------

    def _categorize_affected_entities(
        self,
        root_ids: List[str],
        visited_ids: Set[str],
        upstream_ids: Set[str],
        downstream_ids: Set[str],
        max_depth: int,
        paths: List[PropagationPath],
    ) -> AffectedEntities:
        """Categorizes all visited nodes into callers, callees, APIs, tables, services, and tests."""
        callers: Set[str] = set()
        callees: Set[str] = set()
        affected_apis: Set[str] = set()
        affected_tables: Set[str] = set()
        affected_services: Set[str] = set()
        tests_to_run: Set[str] = set()
        untested_nodes: Set[str] = set()

        root_set = set(root_ids)

        for nid in visited_ids:
            node = self.lookup_tool.get(nid)
            if not node:
                continue

            ntype = node.type
            path = node.location.path

            # Is it a test entity?
            if self._is_test_entity(node):
                tests_to_run.add(nid)
                continue

            # APIs
            if ntype == NodeType.API:
                affected_apis.add(nid)
            # Tables
            elif ntype == NodeType.TABLE:
                affected_tables.add(nid)
            # External Services
            elif ntype == NodeType.SERVICE:
                affected_services.add(nid)

            # Code Nodes (Functions, Classes, Files)
            if nid in upstream_ids and nid not in root_set:
                callers.add(nid)
            elif nid in downstream_ids and nid not in root_set:
                callees.add(nid)

            # Check test coverage for code nodes
            if ntype in (NodeType.FUNCTION, NodeType.CLASS, NodeType.FILE) and nid not in affected_apis:
                has_test = False
                for edge in node.metadata.get("incoming_edges", []):
                    if edge.get("type") == "test_to_code":
                        has_test = True
                        tests_to_run.add(edge.get("source_id"))
                if not has_test:
                    untested_nodes.add(nid)

        # Select highest-value representative propagation paths
        sorted_paths = sorted(paths, key=lambda p: p.length, reverse=True)[:10]

        return AffectedEntities(
            changed_roots=root_ids,
            all_affected_node_ids=sorted(list(visited_ids)),
            callers=sorted(list(callers)),
            callees=sorted(list(callees)),
            affected_apis=sorted(list(affected_apis)),
            affected_tables=sorted(list(affected_tables)),
            affected_services=sorted(list(affected_services)),
            tests_to_run=sorted(list(tests_to_run)),
            untested_nodes=sorted(list(untested_nodes)),
            max_propagation_depth=max_depth,
            paths=sorted_paths,
        )

    def _is_test_entity(self, node: RegistryNode) -> bool:
        """Determines if a node belongs to a test suite or test function."""
        path = node.location.path.lower()
        parts = [p.lower() for p in Path(path).parts]
        return (
            "tests" in parts
            or "test" in parts
            or node.name.startswith("test_")
            or node.name.endswith("_test")
            or path.endswith("_test.py")
        )

    # --------------------------------------------------------------------------
    # Subroutines: 2. Quantitative Scoring
    # --------------------------------------------------------------------------

    def _calculate_blast_radius_score(self, affected: AffectedEntities) -> Tuple[float, ImpactSeverity]:
        """
        Calculates a calibrated blast-radius score from 0.0 to 100.0.
        Factors:
        - Scope size (number of affected nodes)
        - Max dependency propagation depth
        - API contract exposure (breaking changes risk)
        - Database persistence impact (schema/data corruption risk)
        - External service boundary crossings
        - Untested modified code penalty
        """
        node_count = len(affected.all_affected_node_ids)
        if node_count == 0:
            return 0.0, ImpactSeverity.LOW

        # 1. Scope Factor (0.0 to 35.0)
        scope_score = min(35.0, math.sqrt(node_count) * 7.0)

        # 2. Depth Factor (0.0 to 20.0)
        depth_score = min(20.0, affected.max_propagation_depth * 4.0)

        # 3. High-Value Entity Criticality
        api_score = min(20.0, len(affected.affected_apis) * 10.0)
        table_score = min(15.0, len(affected.affected_tables) * 7.5)
        service_score = min(10.0, len(affected.affected_services) * 5.0)

        # 4. Untested Code Risk Penalty
        untested_penalty = min(15.0, len(affected.untested_nodes) * 2.0)

        # 5. Test Mitigation Discount
        test_discount = 5.0 if len(affected.tests_to_run) >= 2 else 0.0

        total_score = scope_score + depth_score + api_score + table_score + service_score + untested_penalty - test_discount
        final_score = min(100.0, max(5.0, round(total_score, 1)))

        if final_score < 25.0:
            severity = ImpactSeverity.LOW
        elif final_score < 50.0:
            severity = ImpactSeverity.MEDIUM
        elif final_score < 75.0:
            severity = ImpactSeverity.HIGH
        else:
            severity = ImpactSeverity.CRITICAL

        return final_score, severity

    # --------------------------------------------------------------------------
    # Subroutines: 3. Selective Agent Waking
    # --------------------------------------------------------------------------

    def _determine_agents_to_wake(
        self,
        affected: AffectedEntities,
        blast_score: float,
        severity: ImpactSeverity,
    ) -> List[WakeDirective]:
        """
        Selectively identifies which downstream agents must awaken to respond to the blast radius.
        Only agents relevant to the specific impact surface are awakened.
        """
        directives: List[WakeDirective] = []

        # 1. Orchestrator (Control Layer): Always woken to supervise the workflow
        directives.append(
            WakeDirective(
                agent_id="orchestrator",
                layer="control",
                priority="high" if severity in (ImpactSeverity.HIGH, ImpactSeverity.CRITICAL) else "medium",
                reason=f"Overall change supervision; blast radius evaluated at {blast_score} ({severity.value.upper()})",
                payload={"severity": severity.value, "blast_radius_score": blast_score},
            )
        )

        # 2. Code Quality (Quality Layer): Woken if code nodes (functions/classes) are affected
        if affected.callers or affected.callees or affected.changed_roots:
            directives.append(
                WakeDirective(
                    agent_id="code_quality",
                    layer="quality",
                    priority="high" if severity in (ImpactSeverity.HIGH, ImpactSeverity.CRITICAL) else "medium",
                    reason=f"Analyze code standards and maintainability for {len(affected.callers) + len(affected.callees) + len(affected.changed_roots)} modified code entities",
                    payload={"affected_code_nodes": affected.callers + affected.callees + affected.changed_roots},
                )
            )

        # 3. Test Runner (Quality/Runtime Layer): Woken if existing tests cover the affected code
        if affected.tests_to_run:
            directives.append(
                WakeDirective(
                    agent_id="test_runner",
                    layer="quality",
                    priority="high",
                    reason=f"Execute {len(affected.tests_to_run)} targeted test suites directly covering modified entities",
                    payload={"tests_to_run": affected.tests_to_run},
                )
            )

        # 4. Test Generation (Optional Layer): Woken if affected code nodes have no test coverage
        if affected.untested_nodes:
            directives.append(
                WakeDirective(
                    agent_id="test_generation",
                    layer="optional",
                    priority="medium",
                    reason=f"Generate regression tests for {len(affected.untested_nodes)} modified code entities lacking test coverage",
                    payload={"untested_nodes": affected.untested_nodes},
                )
            )

        # 5. Security Agent (Safety Layer): Woken if APIs, external services, or critical blast radius
        if affected.affected_apis or affected.affected_services or severity == ImpactSeverity.CRITICAL:
            directives.append(
                WakeDirective(
                    agent_id="security_agent",
                    layer="safety",
                    priority="high",
                    reason=(
                        f"Security review triggered: {len(affected.affected_apis)} APIs, "
                        f"{len(affected.affected_services)} external services affected"
                    ),
                    payload={
                        "affected_apis": affected.affected_apis,
                        "affected_services": affected.affected_services,
                    },
                )
            )

        # 6. Compatibility & API Validator (Safety Layer): Woken if APIs or DB tables change
        if affected.affected_apis or affected.affected_tables:
            directives.append(
                WakeDirective(
                    agent_id="compatibility_agent",
                    layer="safety",
                    priority="high" if affected.affected_tables else "medium",
                    reason="Verify backward compatibility for modified public APIs or database schemas",
                    payload={
                        "apis": affected.affected_apis,
                        "tables": affected.affected_tables,
                    },
                )
            )

        # 7. Architecture Review (Quality Layer): Woken for wide blast radius or service crossings
        if severity in (ImpactSeverity.HIGH, ImpactSeverity.CRITICAL) or affected.affected_services:
            directives.append(
                WakeDirective(
                    agent_id="architecture_review",
                    layer="quality",
                    priority="high",
                    reason=(
                        f"High-impact architectural inspection: blast radius score {blast_score} "
                        f"with max propagation depth {affected.max_propagation_depth}"
                    ),
                    payload={"severity": severity.value, "max_depth": affected.max_propagation_depth},
                )
            )

        return directives
