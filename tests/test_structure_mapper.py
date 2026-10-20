"""
Comprehensive tests for Structure Mapper Agent (Layer: Graph, Role: Graph agent 1: nodes).
Tests Tree-sitter parsing, SCIP symbol enrichment, read-only access control,
registry proposal generation, and end-to-end registration with Registry Keeper.
"""

from pathlib import Path
import pytest

from core.exceptions import UnauthorizedAccessError
from models.registry import ChangeAction, NodeType, RegistryNode
from models.structure import RepoShard, StructureMapperInput
from storage.registry_store import CodeRegistryStore
from tools.scip_tool import ScipTool
from tools.tree_sitter_tool import TreeSitterTool
from agents.graph.registry_keeper import RegistryKeeper
from agents.graph.structure_mapper import STRUCTURE_MAPPER_METADATA, StructureMapper


@pytest.fixture
def store():
    """Isolated in-memory registry store."""
    return CodeRegistryStore(persistence_path=":memory:")


def test_structure_mapper_metadata():
    """Verify Structure Mapper specification strictly matches system spec."""
    assert STRUCTURE_MAPPER_METADATA.id == "structure_mapper"
    assert STRUCTURE_MAPPER_METADATA.name == "Structure Mapper"
    assert STRUCTURE_MAPPER_METADATA.layer == "graph"
    assert STRUCTURE_MAPPER_METADATA.role == "Graph agent 1: nodes"
    assert STRUCTURE_MAPPER_METADATA.access == "read-only"
    assert STRUCTURE_MAPPER_METADATA.model_tier == "small"
    assert STRUCTURE_MAPPER_METADATA.optional is False
    assert set(STRUCTURE_MAPPER_METADATA.tools) == {
        "tree_sitter",
        "scip",
        "registry.lookup",
        "registry.propose",
    }
    assert "repo_shard" in STRUCTURE_MAPPER_METADATA.inputs
    assert "language_configs" in STRUCTURE_MAPPER_METADATA.inputs
    assert "registry" in STRUCTURE_MAPPER_METADATA.inputs
    assert "nodes(id,type,path,signature,hash,summary)" in STRUCTURE_MAPPER_METADATA.outputs
    assert "registry_update_proposals" in STRUCTURE_MAPPER_METADATA.outputs
    assert STRUCTURE_MAPPER_METADATA.trigger == "after Registry Keeper; per changed shard"


def test_read_only_access_enforcement(store):
    """Verify Structure Mapper has read-only access and cannot write directly to registry store."""
    mapper = StructureMapper(store=store)
    assert mapper.access == "read-only"

    dummy_node = RegistryNode(
        id="file:src/test.py",
        name="test.py",
        type=NodeType.FILE,
        location={"path": "src/test.py"},
        hash="abc123hash",
    )

    # Attempting direct write to store must raise UnauthorizedAccessError
    with pytest.raises(UnauthorizedAccessError):
        store.write_node(
            node=dummy_node,
            access_token=mapper.access,
            source_agent=mapper.id,
        )


def test_tree_sitter_python_ast_extraction(tmp_path):
    """Verify TreeSitterTool extracts files, classes, methods, functions, signatures, and summaries."""
    tool = TreeSitterTool(repo_root=str(tmp_path))
    py_file = tmp_path / "calculator.py"
    py_file.write_text(
        '"""Calculator utilities."""\n'
        '\n'
        'class Calculator:\n'
        '    """Arithmetic calculation engine."""\n'
        '    def add(self, a: int, b: int) -> int:\n'
        '        """Add two integers."""\n'
        '        return a + b\n'
        '\n'
        'def multiply(x: int, y: int) -> int:\n'
        '    """Multiply numbers."""\n'
        '    return x * y\n'
    )

    nodes = tool.parse_file(py_file)
    assert len(nodes) == 4  # file, Calculator class, add method, multiply function

    # 1. File node
    file_node = next(n for n in nodes if n.type == NodeType.FILE)
    assert file_node.id == "file:calculator.py"
    assert file_node.name == "calculator.py"
    assert file_node.hash != ""

    # 2. Class node
    class_node = next(n for n in nodes if n.type == NodeType.CLASS)
    assert class_node.id == "class:calculator.py:Calculator"
    assert class_node.name == "Calculator"
    assert class_node.location.start_line == 3
    assert class_node.location.end_line == 7
    assert class_node.metadata.get("summary") == "Arithmetic calculation engine."

    # 3. Method node
    method_node = next(n for n in nodes if n.id == "func:calculator.py:Calculator.add")
    assert method_node.name == "Calculator.add"
    assert method_node.metadata.get("parent_class") == "Calculator"
    assert "def add(self, a, b)" in method_node.location.signature
    assert method_node.metadata.get("summary") == "Add two integers."

    # 4. Standalone function node
    fn_node = next(n for n in nodes if n.id == "func:calculator.py:multiply")
    assert fn_node.name == "multiply"
    assert fn_node.location.start_line == 9
    assert fn_node.metadata.get("summary") == "Multiply numbers."


def test_tree_sitter_javascript_extraction(tmp_path):
    """Verify TreeSitterTool extracts JS/TS classes and functions."""
    tool = TreeSitterTool(repo_root=str(tmp_path))
    js_file = tmp_path / "service.js"
    js_file.write_text(
        "export class OrderService extends BaseService {\n"
        "  processOrder(orderId) {}\n"
        "}\n"
        "export async function fetchPrice(itemId) {}\n"
        "const calculateDiscount = (rate) => {};\n"
    )

    nodes = tool.parse_file(js_file)
    node_ids = {n.id for n in nodes}

    assert "file:service.js" in node_ids
    assert "class:service.js:OrderService" in node_ids
    assert "func:service.js:fetchPrice" in node_ids
    assert "func:service.js:calculateDiscount" in node_ids


def test_scip_tool_symbol_generation(tmp_path):
    """Verify ScipTool generates valid SCIP format symbols for all node types."""
    scip = ScipTool(package_name="testpkg", version="1.0.0")

    file_node = RegistryNode(
        id="file:src/auth.py",
        name="auth.py",
        type=NodeType.FILE,
        location={"path": "src/auth.py"},
        hash="h1",
    )
    class_node = RegistryNode(
        id="class:src/auth.py:AuthManager",
        name="AuthManager",
        type=NodeType.CLASS,
        location={"path": "src/auth.py", "start_line": 10},
        hash="h2",
    )
    method_node = RegistryNode(
        id="func:src/auth.py:AuthManager.login",
        name="AuthManager.login",
        type=NodeType.FUNCTION,
        location={"path": "src/auth.py", "start_line": 15},
        hash="h3",
    )
    func_node = RegistryNode(
        id="func:src/auth.py:verify_hash",
        name="verify_hash",
        type=NodeType.FUNCTION,
        location={"path": "src/auth.py", "start_line": 30},
        hash="h4",
    )

    assert scip.generate_symbol(file_node) == "scip-python testpkg 1.0.0 src/auth.py/"
    assert scip.generate_symbol(class_node) == "scip-python testpkg 1.0.0 src/auth.py/AuthManager#"
    assert scip.generate_symbol(method_node) == "scip-python testpkg 1.0.0 src/auth.py/AuthManager#login()."
    assert scip.generate_symbol(func_node) == "scip-python testpkg 1.0.0 src/auth.py/verify_hash()."

    enriched = scip.enrich_node(func_node)
    assert enriched.metadata["scip_symbol"] == "scip-python testpkg 1.0.0 src/auth.py/verify_hash()."


def test_structure_mapper_execute_shard(tmp_path, store):
    """Verify StructureMapper walks a shard and generates proper UpdateProposals."""
    # Create shard folder
    shard_dir = tmp_path / "shard_auth"
    shard_dir.mkdir()
    auth_file = shard_dir / "token.py"
    auth_file.write_text(
        'def create_token(user_id: str) -> str:\n'
        '    """Creates a signed JWT."""\n'
        '    return "jwt_token"\n'
    )

    mapper = StructureMapper(store=store, repo_root=str(tmp_path))
    shard = RepoShard.from_directory(shard_dir, repo_root=str(tmp_path))

    output = mapper.execute(StructureMapperInput(repo_shard=shard))

    assert output.shard_id == "shard:shard_auth"
    assert len(output.nodes) == 2  # file and create_token
    assert len(output.registry_update_proposals) == 2

    # Check proposals
    prop_actions = [p.action for p in output.registry_update_proposals]
    assert all(a == ChangeAction.CREATE for a in prop_actions)
    assert output.registry_update_proposals[0].source_agent == "structure_mapper"


def test_structure_mapper_detects_modified_nodes(tmp_path, store):
    """Verify Structure Mapper marks modified nodes with action=UPDATE when hash changes."""
    mapper = StructureMapper(store=store, repo_root=str(tmp_path))
    code_file = tmp_path / "module.py"
    code_file.write_text("def run(): return 1\n")

    # Initial parse
    shard = RepoShard.from_directory(tmp_path, repo_root=str(tmp_path))
    out1 = mapper.execute(StructureMapperInput(repo_shard=shard))

    # Pre-register in store using Registry Keeper
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))
    keeper.execute(
        {"update_proposals_from_structure_mapper": out1.registry_update_proposals}
    )

    # Modify code on disk
    code_file.write_text("def run(): return 2  # updated implementation\n")

    # Run mapper again with only_changed=True
    out2 = mapper.execute(StructureMapperInput(repo_shard=shard, only_changed=True))

    # File and function hashes changed, so UPDATE proposals are emitted
    assert len(out2.registry_update_proposals) == 2
    assert all(p.action == ChangeAction.UPDATE for p in out2.registry_update_proposals)
    fn_prop = next(p for p in out2.registry_update_proposals if p.node.id == "func:module.py:run")
    assert fn_prop.details.get("status") == "modified_hash"


def test_map_and_register_integration(tmp_path, store):
    """
    Verify end-to-end integration:
    Structure Mapper walks shard and registers nodes with Registry Keeper
    before they are used anywhere else.
    """
    shard_dir = tmp_path / "core"
    shard_dir.mkdir()
    app_file = shard_dir / "app.py"
    app_file.write_text(
        'class Application:\n'
        '    def bootstrap(self): pass\n'
    )

    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))
    mapper = StructureMapper(store=store, repo_root=str(tmp_path))

    # Verify store is empty
    assert store.count() == 0

    # Execute map_and_register
    mapper_out, keeper_out = mapper.map_and_register(
        registry_keeper=keeper,
        repo_shard=str(shard_dir),
    )

    # Check that nodes are registered in the store
    assert len(mapper_out.nodes) == 3  # file, class, method
    assert len(keeper_out.updated_registry) == 3
    assert store.count() == 3

    assert store.get("file:core/app.py") is not None
    assert store.get("class:core/app.py:Application") is not None
    assert store.get("func:core/app.py:Application.bootstrap") is not None

    # Verify audit change logs were recorded by Registry Keeper
    assert len(keeper_out.change_log) == 3
    assert all(entry.source_agent == "registry_keeper" for entry in keeper_out.change_log)
