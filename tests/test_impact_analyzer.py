"""
Comprehensive tests for Agent 7: Impact Analyzer (Layer: Understanding, Role: Blast-radius finder).
Verifies:
1. Agent metadata, layer, role, read-only access enforcement
2. graph.traverse tool unit tests (upstream, downstream, both, cycles, depth)
3. Caller and callee discovery
4. API, table, and external service blast radius escalation
5. Test coverage detection, mitigation discount, and untested node penalty
6. Calibrated blast-radius score and severity tier calculation
7. Selective agent wake directives matrix
8. Full end-to-end integration across a multi-tier architecture
"""

import pytest
from pathlib import Path

from agents.understanding.impact_analyzer import (
    IMPACT_ANALYZER_METADATA,
    ImpactAnalyzer,
)
from core.exceptions import UnauthorizedAccessError
from models.impact import (
    AffectedEntities,
    ImpactAnalyzerInput,
    ImpactAnalyzerOutput,
    ImpactSeverity,
    WakeDirective,
)
from models.registry import (
    NodeLocation,
    NodeStatus,
    NodeType,
    RegistryNode,
)
from storage.registry_store import CodeRegistryStore
from tools.graph_traverse_tool import GraphTraverseTool


def _create_node(
    node_id: str,
    node_type: NodeType,
    name: str,
    path: str = "src/app.py",
) -> RegistryNode:
    """Helper to create a well-formed RegistryNode."""
    return RegistryNode(
        id=node_id,
        type=node_type,
        name=name,
        location=NodeLocation(path=path, start_line=1, end_line=20),
        status=NodeStatus.ACTIVE,
        hash="test_hash_123",
        summary=f"Summary for {name}",
        metadata={},
    )


def _add_node_to_store(store: CodeRegistryStore, node: RegistryNode) -> None:
    """Registers node into CodeRegistryStore via authorized token."""
    store.write_node(node=node, access_token="registry-write", source_agent="registry_keeper")


def _add_edge_to_store(
    store: CodeRegistryStore,
    source_id: str,
    target_id: str,
    edge_type: str,
) -> None:
    """Attaches outgoing edge to source and incoming edge to target in store."""
    src = store.get(source_id)
    tgt = store.get(target_id)
    if src:
        out_edges = src.metadata.setdefault("outgoing_edges", [])
        edge_dict = {"target_id": target_id, "type": edge_type}
        if edge_dict not in out_edges:
            out_edges.append(edge_dict)
            store.write_node(node=src, access_token="registry-write", source_agent="registry_keeper")
    if tgt:
        in_edges = tgt.metadata.setdefault("incoming_edges", [])
        in_dict = {"source_id": source_id, "type": edge_type}
        if in_dict not in in_edges:
            in_edges.append(in_dict)
            store.write_node(node=tgt, access_token="registry-write", source_agent="registry_keeper")


def test_impact_analyzer_metadata():
    """Validates impact analyzer agent metadata against the formal specification."""
    meta = IMPACT_ANALYZER_METADATA
    assert meta.id == "impact_analyzer"
    assert meta.name == "Impact Analyzer"
    assert meta.layer == "understanding"
    assert meta.role == "Blast-radius finder"
    assert meta.access == "read-only"
    assert meta.model_tier == "small"
    assert "changed_nodes" in meta.inputs
    assert "graph" in meta.inputs
    assert "registry" in meta.inputs
    assert "blast_radius_score" in meta.outputs
    assert "affected_nodes_and_services" in meta.outputs
    assert "agents_to_wake" in meta.outputs
    assert "graph.traverse" in meta.tools
    assert "registry.lookup" in meta.tools
    assert meta.trigger == "after graph is refreshed on a change"
    assert meta.optional is False


def test_read_only_access_enforcement():
    """Ensures ImpactAnalyzer strictly operates in read-only mode."""
    store = CodeRegistryStore(persistence_path=":memory:")
    analyzer = ImpactAnalyzer(store=store)
    # read-only check passes
    analyzer.require_access("read-only")

    # If configured with write access, require_access("read-only") must raise UnauthorizedAccessError
    custom_meta = IMPACT_ANALYZER_METADATA.model_copy(deep=True)
    custom_meta.access = "read-write"
    write_analyzer = ImpactAnalyzer(store=store, metadata=custom_meta)
    with pytest.raises(UnauthorizedAccessError):
        write_analyzer.require_access("read-only")


def test_graph_traverse_tool_bidirectional_and_cycles():
    """Tests graph.traverse tool for upstream, downstream, and cycle handling."""
    store = CodeRegistryStore(persistence_path=":memory:")
    # Node A -> calls -> Node B -> calls -> Node C -> calls -> Node A (circular)
    # Node B -> calls -> Node D
    node_a = _create_node("func:pkg.a", NodeType.FUNCTION, "a")
    node_b = _create_node("func:pkg.b", NodeType.FUNCTION, "b")
    node_c = _create_node("func:pkg.c", NodeType.FUNCTION, "c")
    node_d = _create_node("func:pkg.d", NodeType.FUNCTION, "d")

    for n in [node_a, node_b, node_c, node_d]:
        _add_node_to_store(store, n)

    _add_edge_to_store(store, "func:pkg.a", "func:pkg.b", "calls")
    _add_edge_to_store(store, "func:pkg.b", "func:pkg.c", "calls")
    _add_edge_to_store(store, "func:pkg.c", "func:pkg.a", "calls")
    _add_edge_to_store(store, "func:pkg.b", "func:pkg.d", "calls")

    traverse_tool = GraphTraverseTool(store=store)

    # 1. Downstream from B: should find C, A, D without infinite loop
    res_down = traverse_tool.traverse(start_node_ids=["func:pkg.b"], direction="downstream", max_depth=5)
    assert "func:pkg.c" in res_down.downstream_node_ids
    assert "func:pkg.d" in res_down.downstream_node_ids
    assert "func:pkg.a" in res_down.downstream_node_ids
    assert len(res_down.visited_node_ids) == 4

    # 2. Upstream from B: should find A (caller of B) and C (caller of A)
    res_up = traverse_tool.traverse(start_node_ids=["func:pkg.b"], direction="upstream", max_depth=5)
    assert "func:pkg.a" in res_up.upstream_node_ids
    assert "func:pkg.c" in res_up.upstream_node_ids

    # 3. Max depth cutoff
    res_depth_1 = traverse_tool.traverse(start_node_ids=["func:pkg.b"], direction="downstream", max_depth=1)
    assert "func:pkg.c" in res_depth_1.downstream_node_ids
    assert "func:pkg.d" in res_depth_1.downstream_node_ids
    # A is at depth 2 from B, so it should NOT be reached at max_depth=1
    assert "func:pkg.a" not in res_depth_1.downstream_node_ids


def test_caller_and_callee_categorization():
    """Tests that callers and callees are cleanly segregated."""
    store = CodeRegistryStore(persistence_path=":memory:")

    caller = _create_node("func:controller.handle", NodeType.FUNCTION, "handle", "src/controller.py")
    changed = _create_node("func:service.process", NodeType.FUNCTION, "process", "src/service.py")
    callee1 = _create_node("func:repo.save", NodeType.FUNCTION, "save", "src/repo.py")
    callee2 = _create_node("func:util.format", NodeType.FUNCTION, "format", "src/util.py")

    for n in [caller, changed, callee1, callee2]:
        _add_node_to_store(store, n)

    _add_edge_to_store(store, "func:controller.handle", "func:service.process", "calls")
    _add_edge_to_store(store, "func:service.process", "func:repo.save", "calls")
    _add_edge_to_store(store, "func:service.process", "func:util.format", "calls")

    analyzer = ImpactAnalyzer(store=store)
    output = analyzer.execute(ImpactAnalyzerInput(changed_nodes=["func:service.process"]))

    assert "func:controller.handle" in output.affected_nodes_and_services.callers
    assert "func:repo.save" in output.affected_nodes_and_services.callees
    assert "func:util.format" in output.affected_nodes_and_services.callees
    assert "func:service.process" in output.affected_nodes_and_services.changed_roots
    assert output.blast_radius_score > 0.0


def test_api_and_table_blast_radius_escalation():
    """Tests that API contracts and DB tables escalate blast-radius score and trigger safety agents."""
    store = CodeRegistryStore(persistence_path=":memory:")

    api_node = _create_node("api:POST_/users", NodeType.API, "POST /users", "api/routes.py")
    service_node = _create_node("func:service.create_user", NodeType.FUNCTION, "create_user", "src/user_service.py")
    table_node = _create_node("table:users", NodeType.TABLE, "users", "schema.sql")
    ext_service = _create_node("service:stripe_billing", NodeType.SERVICE, "stripe_billing", "config.yaml")

    for n in [api_node, service_node, table_node, ext_service]:
        _add_node_to_store(store, n)

    _add_edge_to_store(store, "api:POST_/users", "func:service.create_user", "api_to_code")
    _add_edge_to_store(store, "func:service.create_user", "table:users", "writes_table")
    _add_edge_to_store(store, "func:service.create_user", "service:stripe_billing", "calls_service")

    analyzer = ImpactAnalyzer(store=store)
    output = analyzer.execute(ImpactAnalyzerInput(changed_nodes=["func:service.create_user"]))

    aff = output.affected_nodes_and_services
    assert "api:POST_/users" in aff.affected_apis
    assert "table:users" in aff.affected_tables
    assert "service:stripe_billing" in aff.affected_services

    # With API (10), Table (7.5), and Service (5.0), blast score should be significantly elevated
    assert output.blast_radius_score >= 35.0
    assert output.severity in (ImpactSeverity.MEDIUM, ImpactSeverity.HIGH, ImpactSeverity.CRITICAL)

    # Verify selective agent wake directives
    agent_ids = {w.agent_id for w in output.agents_to_wake}
    assert "orchestrator" in agent_ids
    assert "security_agent" in agent_ids
    assert "compatibility_agent" in agent_ids


def test_test_coverage_detection_and_discount():
    """Tests that test coverage mitigates risk and awakens the test_runner agent."""
    store = CodeRegistryStore(persistence_path=":memory:")

    target_func = _create_node("func:calc.add", NodeType.FUNCTION, "add", "src/calc.py")
    test1 = _create_node("func:tests.test_calc.test_add", NodeType.FUNCTION, "test_add", "tests/test_calc.py")
    test2 = _create_node("func:tests.test_calc.test_add_negative", NodeType.FUNCTION, "test_add_negative", "tests/test_calc.py")

    for n in [target_func, test1, test2]:
        _add_node_to_store(store, n)

    _add_edge_to_store(store, "func:tests.test_calc.test_add", "func:calc.add", "test_to_code")
    _add_edge_to_store(store, "func:tests.test_calc.test_add_negative", "func:calc.add", "test_to_code")

    analyzer = ImpactAnalyzer(store=store)
    output = analyzer.execute(ImpactAnalyzerInput(changed_nodes=["func:calc.add"]))

    assert "func:tests.test_calc.test_add" in output.affected_nodes_and_services.tests_to_run
    assert "func:tests.test_calc.test_add_negative" in output.affected_nodes_and_services.tests_to_run
    assert len(output.affected_nodes_and_services.untested_nodes) == 0

    # test_runner must be woken with high priority
    test_runner_directive = next((w for w in output.agents_to_wake if w.agent_id == "test_runner"), None)
    assert test_runner_directive is not None
    assert test_runner_directive.priority == "high"
    assert "tests_to_run" in test_runner_directive.payload


def test_untested_nodes_penalty_and_test_generation_wake():
    """Tests that untested code triggers the test_generation agent with penalty."""
    store = CodeRegistryStore(persistence_path=":memory:")

    target_func = _create_node("func:calc.subtract", NodeType.FUNCTION, "subtract", "src/calc.py")
    _add_node_to_store(store, target_func)

    analyzer = ImpactAnalyzer(store=store)
    output = analyzer.execute(ImpactAnalyzerInput(changed_nodes=["func:calc.subtract"]))

    assert "func:calc.subtract" in output.affected_nodes_and_services.untested_nodes
    assert len(output.affected_nodes_and_services.tests_to_run) == 0

    # test_generation agent must be woken
    gen_directive = next((w for w in output.agents_to_wake if w.agent_id == "test_generation"), None)
    assert gen_directive is not None
    assert gen_directive.agent_id == "test_generation"
    assert "func:calc.subtract" in gen_directive.payload["untested_nodes"]


def test_end_to_end_multi_tier_architecture_blast_radius():
    """
    End-to-end integration test:
    Constructs a realistic multi-tier web application dependency graph:
      [API: GET /items] -> calls -> [Handler: get_items] -> calls -> [Service: item_service]
                                                                            |
                                                      +---------------------+---------------------+
                                                      |                                           |
                                            [Repo: query_items]                     [External: cache_redis]
                                                      |
                                            [Table: items_table]
      And:
      [Test: test_get_items] -> test_to_code -> [Handler: get_items]
    
    Trigger change on [Service: item_service].
    Verify complete traversal, blast radius scoring, and selective wake directives.
    """
    store = CodeRegistryStore(persistence_path=":memory:")

    api_get = _create_node("api:GET_/items", NodeType.API, "GET /items", "api/routes.py")
    handler = _create_node("func:handlers.get_items", NodeType.FUNCTION, "get_items", "src/handlers.py")
    service = _create_node("func:services.item_service", NodeType.FUNCTION, "item_service", "src/services.py")
    repo = _create_node("func:repo.query_items", NodeType.FUNCTION, "query_items", "src/repo.py")
    table = _create_node("table:items_table", NodeType.TABLE, "items_table", "migrations/001_items.sql")
    cache = _create_node("service:redis_cache", NodeType.SERVICE, "redis_cache", "config.env")
    test_handler = _create_node("func:tests.test_handlers.test_get_items", NodeType.FUNCTION, "test_get_items", "tests/test_handlers.py")

    all_nodes = [api_get, handler, service, repo, table, cache, test_handler]
    for n in all_nodes:
        _add_node_to_store(store, n)

    # Edges
    _add_edge_to_store(store, "api:GET_/items", "func:handlers.get_items", "api_to_code")
    _add_edge_to_store(store, "func:handlers.get_items", "func:services.item_service", "calls")
    _add_edge_to_store(store, "func:services.item_service", "func:repo.query_items", "calls")
    _add_edge_to_store(store, "func:repo.query_items", "table:items_table", "queries_table")
    _add_edge_to_store(store, "func:services.item_service", "service:redis_cache", "calls_service")
    _add_edge_to_store(store, "func:tests.test_handlers.test_get_items", "func:handlers.get_items", "test_to_code")

    analyzer = ImpactAnalyzer(store=store)
    output = analyzer.execute(ImpactAnalyzerInput(changed_nodes=["func:services.item_service"], max_depth=5))

    aff = output.affected_nodes_and_services

    # Verify upstream callers found
    assert "func:handlers.get_items" in aff.callers
    # Verify API contract reached
    assert "api:GET_/items" in aff.affected_apis
    # Verify downstream callees found
    assert "func:repo.query_items" in aff.callees
    # Verify DB table reached
    assert "table:items_table" in aff.affected_tables
    # Verify external service reached
    assert "service:redis_cache" in aff.affected_services
    # Verify test reached upstream
    assert "func:tests.test_handlers.test_get_items" in aff.tests_to_run

    # Check propagation paths
    assert len(aff.paths) > 0
    assert aff.max_propagation_depth >= 2

    # Check blast radius score
    assert output.blast_radius_score >= 40.0

    # Check awakened agents
    woken_agents = {w.agent_id: w for w in output.agents_to_wake}
    assert "orchestrator" in woken_agents
    assert "code_quality" in woken_agents
    assert "test_runner" in woken_agents
    assert "security_agent" in woken_agents
    assert "compatibility_agent" in woken_agents

    # Verify statistics dictionary
    assert output.stats["changed_nodes_analyzed"] == 1
    assert output.stats["apis_affected"] == 1
    assert output.stats["tables_affected"] == 1
    assert output.stats["services_affected"] == 1
    assert output.stats["tests_to_run_count"] == 1
