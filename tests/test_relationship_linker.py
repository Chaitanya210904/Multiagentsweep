"""
Unit and Integration Tests for Agent 5: Relationship Linker (Layer: Graph).
Verifies:
1. Agent metadata, read-only permissions, and tool inventory.
2. Inheritance edge extraction and strict endpoint resolution.
3. Import edge extraction and resolution to file/symbol nodes.
4. Call edge extraction and detection of internal calls.
5. Test-to-code edge extraction linking test files to production code.
6. Zero-guessing compliance (unresolved queue for missing endpoints).
7. End-to-end integration with Structure Mapper and Registry Keeper.
"""

from pathlib import Path
import pytest

from agents.graph.registry_keeper import RegistryKeeper
from agents.graph.relationship_linker import (
    RELATIONSHIP_LINKER_METADATA,
    RelationshipLinker,
)
from agents.graph.structure_mapper import StructureMapper
from core.exceptions import UnauthorizedAccessError
from models.registry import (
    NodeLocation,
    NodeType,
    RegistryNode,
)
from models.relationship import (
    CodeEdge,
    EdgeType,
    RelationshipLinkerInput,
)
from storage.registry_store import CodeRegistryStore
from tools.graph_write_edge_tool import GraphWriteEdgeTool


@pytest.fixture
def store():
    """In-memory store fixture guaranteeing clean isolation for each test."""
    return CodeRegistryStore(persistence_path=":memory:")


def test_relationship_linker_metadata():
    """Verifies Agent 5 metadata matches platform architectural specification."""
    meta = RELATIONSHIP_LINKER_METADATA
    assert meta.id == "relationship_linker"
    assert meta.name == "Relationship Linker"
    assert meta.layer == "graph"
    assert meta.role == "Graph agent 2: code edges"
    assert meta.access == "read-only"
    assert "nodes_from_structure_mapper" in meta.inputs
    assert "registry_lookups" in meta.inputs
    assert "verified_edges" in meta.outputs
    assert "unresolved_link_queue" in meta.outputs
    assert "registry_update_proposals" in meta.outputs
    assert "registry.lookup" in meta.tools
    assert "registry.propose" in meta.tools
    assert "graph.write_edge" in meta.tools


def test_read_only_access_enforcement(store):
    """Verifies Relationship Linker enforces read-only access and cannot write directly to store."""
    linker = RelationshipLinker(store=store)
    assert linker.access == "read-only"

    # Attempting to call write_node on the store with linker's access must be rejected
    sample_node = RegistryNode(
        id="file:sample.py",
        name="sample.py",
        type=NodeType.FILE,
        location=NodeLocation(path="sample.py"),
        hash="abc123hash",
    )
    with pytest.raises(UnauthorizedAccessError):
        store.write_node(
            node=sample_node,
            access_token=linker.access,
            source_agent=linker.id,
        )


def test_graph_write_edge_tool():
    """Verifies GraphWriteEdgeTool creates valid edges and rejects invalid relationships."""
    tool = GraphWriteEdgeTool()
    edge = tool.write_edge(
        source_id="class:foo.py:Child",
        target_id="class:foo.py:Parent",
        edge_type=EdgeType.INHERITANCE,
        line_number=10,
    )
    assert edge.id == "edge:inheritance:class:foo.py:Child->class:foo.py:Parent"
    assert edge.type == EdgeType.INHERITANCE
    assert tool.get_edge(edge.id) is not None

    # Self-inheritance must be rejected
    with pytest.raises(ValueError, match="Self-inheritance"):
        tool.write_edge(
            source_id="class:foo.py:Child",
            target_id="class:foo.py:Child",
            edge_type=EdgeType.INHERITANCE,
        )


def test_inheritance_edge_extraction(store, tmp_path):
    """Verifies that class inheritance is linked when parent exists, and queued when missing."""
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    # Register parent class in registry
    parent_node = RegistryNode(
        id="class:core/base.py:BaseService",
        name="BaseService",
        type=NodeType.CLASS,
        location=NodeLocation(path="core/base.py", start_line=5),
        hash="hash_base",
    )
    # Register child class inheriting from BaseService AND UnknownLibraryClass
    child_node = RegistryNode(
        id="class:services/auth.py:AuthService",
        name="AuthService",
        type=NodeType.CLASS,
        location=NodeLocation(path="services/auth.py", start_line=12),
        hash="hash_child",
        metadata={"bases": ["BaseService", "UnknownLibraryClass"]},
    )

    # Register nodes via Registry Keeper
    keeper.write_tool.write_node(parent_node)
    keeper.write_tool.write_node(child_node)

    linker = RelationshipLinker(store=store, repo_root=str(tmp_path))
    output = linker.execute(RelationshipLinkerInput(edge_types=[EdgeType.INHERITANCE]))

    # 1 verified edge to BaseService
    assert len(output.verified_edges) == 1
    edge = output.verified_edges[0]
    assert edge.type == EdgeType.INHERITANCE
    assert edge.source_id == child_node.id
    assert edge.target_id == parent_node.id

    # 1 unresolved link for UnknownLibraryClass (never guessed)
    assert len(output.unresolved_link_queue) == 1
    unresolved = output.unresolved_link_queue[0]
    assert unresolved.raw_target == "UnknownLibraryClass"
    assert unresolved.edge_type == EdgeType.INHERITANCE
    assert "not found in registry" in unresolved.reason


def test_import_edge_extraction(store, tmp_path):
    """Verifies that imports across project files are verified and external imports are queued."""
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    # Create real Python files in tmp_path
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir(parents=True)
    util_file = lib_dir / "utils.py"
    util_file.write_text("def helper(): pass\n", encoding="utf-8")

    app_file = tmp_path / "app.py"
    app_file.write_text(
        "import sys\n"
        "from lib.utils import helper\n",
        encoding="utf-8",
    )

    # Register file nodes in registry
    util_node = RegistryNode(
        id="file:lib/utils.py",
        name="utils.py",
        type=NodeType.FILE,
        location=NodeLocation(path="lib/utils.py"),
        hash="hash_utils",
    )
    app_node = RegistryNode(
        id="file:app.py",
        name="app.py",
        type=NodeType.FILE,
        location=NodeLocation(path="app.py"),
        hash="hash_app",
    )
    keeper.write_tool.write_node(util_node)
    keeper.write_tool.write_node(app_node)

    linker = RelationshipLinker(store=store, repo_root=str(tmp_path))
    output = linker.execute(RelationshipLinkerInput(edge_types=[EdgeType.IMPORTS]))

    # Verified import of lib/utils.py
    verified_import_targets = {e.target_id for e in output.verified_edges}
    assert util_node.id in verified_import_targets

    # External import 'sys' queued as unresolved (never guessed)
    unresolved_targets = {u.raw_target for u in output.unresolved_link_queue}
    assert "sys" in unresolved_targets


def test_call_edge_extraction(store, tmp_path):
    """Verifies that internal function calls are linked and external/ambiguous calls are queued."""
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    # Create source file with caller and callee
    service_file = tmp_path / "calculator.py"
    service_file.write_text(
        "def add(a, b):\n"
        "    return a + b\n\n"
        "def compute(x):\n"
        "    res = add(x, 10)\n"
        "    unknown_ext_func(res)\n"
        "    return res\n",
        encoding="utf-8",
    )

    add_node = RegistryNode(
        id="func:calculator.py:add",
        name="add",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="calculator.py", start_line=1, end_line=2),
        hash="hash_add",
    )
    compute_node = RegistryNode(
        id="func:calculator.py:compute",
        name="compute",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="calculator.py", start_line=4, end_line=7),
        hash="hash_compute",
    )
    keeper.write_tool.write_node(add_node)
    keeper.write_tool.write_node(compute_node)

    linker = RelationshipLinker(store=store, repo_root=str(tmp_path))
    output = linker.execute(RelationshipLinkerInput(edge_types=[EdgeType.CALLS]))

    # Verified call from compute -> add
    call_edges = [e for e in output.verified_edges if e.type == EdgeType.CALLS]
    assert len(call_edges) == 1
    assert call_edges[0].source_id == compute_node.id
    assert call_edges[0].target_id == add_node.id

    # Unresolved call for unknown_ext_func
    unresolved_names = {u.raw_target for u in output.unresolved_link_queue if u.edge_type == EdgeType.CALLS}
    assert "unknown_ext_func" in unresolved_names


def test_test_to_code_edge_extraction(store, tmp_path):
    """Verifies that test files and test functions link to matching production files."""
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    prod_file_node = RegistryNode(
        id="file:services/payment.py",
        name="payment.py",
        type=NodeType.FILE,
        location=NodeLocation(path="services/payment.py"),
        hash="hash_prod",
    )
    test_file_node = RegistryNode(
        id="file:tests/test_payment.py",
        name="test_payment.py",
        type=NodeType.FILE,
        location=NodeLocation(path="tests/test_payment.py"),
        hash="hash_test_file",
    )
    test_func_node = RegistryNode(
        id="func:tests/test_payment.py:test_process_charge",
        name="test_process_charge",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="tests/test_payment.py", start_line=10, end_line=15),
        hash="hash_test_fn",
    )
    keeper.write_tool.write_node(prod_file_node)
    keeper.write_tool.write_node(test_file_node)
    keeper.write_tool.write_node(test_func_node)

    linker = RelationshipLinker(store=store, repo_root=str(tmp_path))
    output = linker.execute(RelationshipLinkerInput(edge_types=[EdgeType.TEST_TO_CODE]))

    # Verified test-to-code edges
    test_edges = [e for e in output.verified_edges if e.type == EdgeType.TEST_TO_CODE]
    assert len(test_edges) >= 2
    target_ids = {e.target_id for e in test_edges}
    assert prod_file_node.id in target_ids


def test_link_and_register_integration(store, tmp_path):
    """
    End-to-end integration test:
    Structure Mapper registers nodes -> Relationship Linker verifies edges and proposes
    -> Registry Keeper attaches bidirectional edges in registry.
    """
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))
    mapper = StructureMapper(store=store, repo_root=str(tmp_path))
    linker = RelationshipLinker(store=store, repo_root=str(tmp_path))

    # Create real interconnected codebase in tmp_path
    app_py = tmp_path / "app.py"
    app_py.write_text(
        "class Animal:\n"
        "    def speak(self):\n"
        "        pass\n\n"
        "class Dog(Animal):\n"
        "    def speak(self):\n"
        "        return 'woof'\n\n"
        "def run_app():\n"
        "    d = Dog()\n"
        "    d.speak()\n",
        encoding="utf-8",
    )

    # 1. Structure Mapper maps and registers nodes with Registry Keeper
    mapper_out, keeper_nodes_out = mapper.map_and_register(
        registry_keeper=keeper,
        repo_shard=".",
    )
    assert len(mapper_out.nodes) >= 4

    # 2. Relationship Linker links and registers verified edges
    linker_out, keeper_edges_out = linker.link_and_register(
        registry_keeper=keeper,
    )

    # Verified inheritance Dog -> Animal
    inheritance_edges = [e for e in linker_out.verified_edges if e.type == EdgeType.INHERITANCE]
    assert len(inheritance_edges) >= 1
    dog_edge = inheritance_edges[0]
    assert "Dog" in dog_edge.source_id
    assert "Animal" in dog_edge.target_id

    # 3. Verify that Registry Keeper successfully persisted edges onto registry nodes
    dog_node = store.get(dog_edge.source_id)
    assert dog_node is not None
    assert "outgoing_edges" in dog_node.metadata
    assert any(e["target_id"] == dog_edge.target_id for e in dog_node.metadata["outgoing_edges"])

    animal_node = store.get(dog_edge.target_id)
    assert animal_node is not None
    assert "incoming_edges" in animal_node.metadata
    assert any(e["source_id"] == dog_edge.source_id for e in animal_node.metadata["incoming_edges"])
