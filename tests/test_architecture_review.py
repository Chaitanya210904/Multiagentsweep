"""
Comprehensive tests for Agent 8: Architecture Review (Layer: Quality, Role: Structure checker).
Verifies:
1. Agent metadata, layer, role, read-only access enforcement
2. Layer inversion detection across architectural tiers
3. Circular dependency cycle detection with complete cycle paths
4. Package coupling metrics (Afferent Ca, Efferent Ce, Instability I) and hotspot alerts
5. Existing ADR ingestion (Markdown files and models) and compliance verification
6. Automated ADR drafting from architectural violations
7. Clean Architecture health score calculation
8. End-to-end integration across multi-module graphs
"""

from datetime import datetime
from pathlib import Path
import pytest
from tempfile import TemporaryDirectory

from agents.quality.architecture_review import (
    ARCHITECTURE_REVIEW_METADATA,
    ArchitectureReview,
)
from core.exceptions import UnauthorizedAccessError
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
from models.registry import (
    NodeLocation,
    NodeStatus,
    NodeType,
    RegistryNode,
)
from storage.registry_store import CodeRegistryStore


def _create_node(
    node_id: str,
    node_type: NodeType,
    name: str,
    path: str,
) -> RegistryNode:
    """Helper to create a well-formed RegistryNode."""
    return RegistryNode(
        id=node_id,
        type=node_type,
        name=name,
        location=NodeLocation(path=path, start_line=1, end_line=30),
        status=NodeStatus.ACTIVE,
        hash="test_hash_abc",
        summary=f"Summary for {name}",
        metadata={},
    )


def _add_node_to_store(store: CodeRegistryStore, node: RegistryNode) -> None:
    """Registers node into CodeRegistryStore."""
    store.write_node(node=node, access_token="registry-write", source_agent="registry_keeper")


def _add_edge_to_store(
    store: CodeRegistryStore,
    source_id: str,
    target_id: str,
    edge_type: str = "calls",
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


def test_architecture_review_metadata():
    """Validates architecture review agent metadata against the formal specification."""
    meta = ARCHITECTURE_REVIEW_METADATA
    assert meta.id == "architecture_review"
    assert meta.name == "Architecture Review"
    assert meta.layer == "quality"
    assert meta.role == "Structure checker"
    assert meta.description == "Checks layers, boundaries, circular dependencies and coupling, and records ADRs."
    assert meta.access == "read-only"
    assert meta.model_tier == "medium"
    assert "graph_slice" in meta.inputs
    assert "existing_adrs" in meta.inputs
    assert "violations" in meta.outputs
    assert "coupling_metrics" in meta.outputs
    assert "draft_adrs" in meta.outputs
    assert "graph.traverse" in meta.tools
    assert "registry.lookup" in meta.tools
    assert meta.trigger == "when impact analysis flags structural change"
    assert meta.optional is False


def test_read_only_access_enforcement():
    """Ensures ArchitectureReview strictly operates in read-only mode."""
    store = CodeRegistryStore(persistence_path=":memory:")
    reviewer = ArchitectureReview(store=store)
    reviewer.require_access("read-only")

    # If configured with write access, require_access("read-only") must raise UnauthorizedAccessError
    custom_meta = ARCHITECTURE_REVIEW_METADATA.model_copy(deep=True)
    custom_meta.access = "read-write"
    write_reviewer = ArchitectureReview(store=store, metadata=custom_meta)
    with pytest.raises(UnauthorizedAccessError):
        write_reviewer.require_access("read-only")


def test_layer_inversion_detection():
    """
    Tests detection of Layer Inversion violations:
    When a lower layer (e.g., models) depends on a higher layer (e.g., agents).
    """
    store = CodeRegistryStore(persistence_path=":memory:")

    # Low-level model node
    model_node = _create_node("class:models/user.py:User", NodeType.CLASS, "User", "models/user.py")
    # Higher-level agent node
    agent_node = _create_node("class:agents/agent.py:MyAgent", NodeType.CLASS, "MyAgent", "agents/agent.py")

    _add_node_to_store(store, model_node)
    _add_node_to_store(store, agent_node)

    # Inverted edge: models -> agents
    _add_edge_to_store(store, "class:models/user.py:User", "class:agents/agent.py:MyAgent", "imports")

    reviewer = ArchitectureReview(store=store)
    output = reviewer.execute(ArchitectureReviewInput())

    layer_violations = [v for v in output.violations if v.type == ArchitectureViolationType.LAYER_INVERSION]
    assert len(layer_violations) == 1
    v = layer_violations[0]
    assert v.source_node_id == "class:models/user.py:User"
    assert v.target_node_id == "class:agents/agent.py:MyAgent"
    assert v.severity == ViolationSeverity.ERROR
    assert "Layer Inversion" in v.message
    assert "Invert dependency" in v.remediation
    assert output.clean_architecture_score < 100.0


def test_circular_dependency_detection():
    """
    Tests detection of circular dependency chains:
    A -> B -> C -> A
    """
    store = CodeRegistryStore(persistence_path=":memory:")

    node_a = _create_node("func:services/a.py:step_a", NodeType.FUNCTION, "step_a", "services/a.py")
    node_b = _create_node("func:services/b.py:step_b", NodeType.FUNCTION, "step_b", "services/b.py")
    node_c = _create_node("func:services/c.py:step_c", NodeType.FUNCTION, "step_c", "services/c.py")

    for n in [node_a, node_b, node_c]:
        _add_node_to_store(store, n)

    _add_edge_to_store(store, "func:services/a.py:step_a", "func:services/b.py:step_b", "calls")
    _add_edge_to_store(store, "func:services/b.py:step_b", "func:services/c.py:step_c", "calls")
    _add_edge_to_store(store, "func:services/c.py:step_c", "func:services/a.py:step_a", "calls")

    reviewer = ArchitectureReview(store=store)
    output = reviewer.execute(ArchitectureReviewInput(check_cycles=True))

    cycle_violations = [v for v in output.violations if v.type == ArchitectureViolationType.CIRCULAR_DEPENDENCY]
    assert len(cycle_violations) >= 1
    cv = cycle_violations[0]
    assert cv.severity == ViolationSeverity.CRITICAL
    assert cv.cycle_path is not None
    assert len(cv.cycle_path) >= 3
    assert cv.cycle_path[0] == cv.cycle_path[-1]  # Closed loop


def test_coupling_metrics_and_hotspots():
    """
    Tests calculation of Ca, Ce, Instability I, and excessive coupling hotspots.
    """
    store = CodeRegistryStore(persistence_path=":memory:")

    # Central God module with 6 outgoing dependencies
    central_node = _create_node("file:services/god_service.py", NodeType.FILE, "god_service.py", "services/god_service.py")
    _add_node_to_store(store, central_node)

    for i in range(6):
        dep_node = _create_node(f"file:utils/dep_{i}.py", NodeType.FILE, f"dep_{i}.py", f"utils/dep_{i}.py")
        _add_node_to_store(store, dep_node)
        _add_edge_to_store(store, "file:services/god_service.py", f"file:utils/dep_{i}.py", "imports")

    # Set threshold = 5 so central_node (Ce=6) is flagged as hotspot
    reviewer = ArchitectureReview(store=store)
    output = reviewer.execute(ArchitectureReviewInput(max_coupling_threshold=5))

    god_metric = next((m for m in output.coupling_metrics if m.entity_id == "file:services/god_service.py"), None)
    assert god_metric is not None
    assert god_metric.efferent_coupling == 6
    assert god_metric.afferent_coupling == 0
    assert god_metric.instability == 1.0  # Ce / (Ca + Ce) = 6 / 6 = 1.0
    assert god_metric.is_hotspot is True
    assert god_metric.risk_level == "high"

    # Verify excessive coupling violation was generated
    coupling_violations = [v for v in output.violations if v.type == ArchitectureViolationType.EXCESSIVE_COUPLING]
    assert len(coupling_violations) == 1
    assert "god_service.py" in coupling_violations[0].message


def test_existing_adr_ingestion_and_compliance():
    """
    Tests parsing existing ADR markdown files and flagging compliance violations.
    """
    store = CodeRegistryStore(persistence_path=":memory:")

    caller = _create_node("func:controllers/order.py:create", NodeType.FUNCTION, "create", "controllers/order.py")
    direct_db = _create_node("func:db/raw_sql.py:execute_raw", NodeType.FUNCTION, "execute_raw", "db/raw_sql.py")
    _add_node_to_store(store, caller)
    _add_node_to_store(store, direct_db)

    # Direct edge: controller calling raw sql
    _add_edge_to_store(store, "func:controllers/order.py:create", "func:db/raw_sql.py:execute_raw", "calls")

    with TemporaryDirectory() as tmpdir:
        adr_file = Path(tmpdir) / "0001-no-direct-db-calls-from-controllers.md"
        adr_file.write_text(
            """# 1. No direct database calls from controllers
## Status
Accepted
## Context
Controllers were directly executing raw SQL queries, leading to security and maintainability risks.
## Decision
We forbid controllers from raw_sql. All database interactions must go through the repository layer.
## Consequences
Improves security and decoupling.
""",
            encoding="utf-8",
        )

        reviewer = ArchitectureReview(store=store, repo_root=tmpdir)
        output = reviewer.execute(ArchitectureReviewInput(existing_adrs=[adr_file]))

        adr_violations = [v for v in output.violations if v.type == ArchitectureViolationType.FORBIDDEN_DEPENDENCY]
        assert len(adr_violations) == 1
        av = adr_violations[0]
        assert "controllers/order.py" in av.source_node_id
        assert "raw_sql" in av.target_node_id
        assert "ADR-1" in av.rule_name or "ADR-0001" in av.rule_name


def test_automated_adr_drafting():
    """
    Tests that architectural anti-patterns automatically generate draft ADRs.
    """
    store = CodeRegistryStore(persistence_path=":memory:")

    # Layer inversion: core -> cli
    core_node = _create_node("file:core/config.py", NodeType.FILE, "config.py", "core/config.py")
    cli_node = _create_node("file:cli/app.py", NodeType.FILE, "app.py", "cli/app.py")
    _add_node_to_store(store, core_node)
    _add_node_to_store(store, cli_node)
    _add_edge_to_store(store, "file:core/config.py", "file:cli/app.py", "imports")

    reviewer = ArchitectureReview(store=store)
    output = reviewer.execute(ArchitectureReviewInput())

    assert len(output.draft_adrs) >= 1
    draft = output.draft_adrs[0]
    assert draft.status == ADRStatus.PROPOSED
    assert "Layer" in draft.title
    assert "Dependency Inversion" in draft.title or "Decoupling" in draft.title
    assert len(draft.consequences) > 0
    assert "file:core/config.py" in draft.affected_nodes


def test_end_to_end_clean_architecture_review():
    """
    End-to-end integration test across a multi-component graph:
    Verifies full analysis, clean architecture scoring, violation reporting, and ADR generation.
    """
    store = CodeRegistryStore(persistence_path=":memory:")

    # Clean stack
    api = _create_node("api:GET_/users", NodeType.API, "GET /users", "api/routes.py")
    controller = _create_node("func:controllers.handle", NodeType.FUNCTION, "handle", "controllers/user.py")
    service = _create_node("func:services.get_user", NodeType.FUNCTION, "get_user", "services/user.py")
    model = _create_node("class:models.User", NodeType.CLASS, "User", "models/user.py")

    for n in [api, controller, service, model]:
        _add_node_to_store(store, n)

    # Clean downward dependencies
    _add_edge_to_store(store, "api:GET_/users", "func:controllers.handle", "api_to_code")
    _add_edge_to_store(store, "func:controllers.handle", "func:services.get_user", "calls")
    _add_edge_to_store(store, "func:services.get_user", "class:models.User", "calls")

    reviewer = ArchitectureReview(store=store)
    clean_output = reviewer.execute(ArchitectureReviewInput())

    # Pristine architecture should have high score and 0 violations
    assert clean_output.clean_architecture_score == 100.0
    assert len(clean_output.violations) == 0
    assert len(clean_output.draft_adrs) == 0

    # Now introduce a circular dependency between controller and service: service -> controller
    _add_edge_to_store(store, "func:services.get_user", "func:controllers.handle", "calls")

    degraded_output = reviewer.execute(ArchitectureReviewInput(check_cycles=True))
    assert degraded_output.clean_architecture_score < 100.0
    assert any(v.type == ArchitectureViolationType.CIRCULAR_DEPENDENCY for v in degraded_output.violations)
    assert len(degraded_output.draft_adrs) >= 1
