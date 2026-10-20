"""
Comprehensive tests for the Registry Keeper Agent (Layer: Graph).
Uses isolated in-memory stores and real filesystem/git integration tests.
"""

import json
from pathlib import Path
import pytest
import subprocess
import tempfile

from core.exceptions import UnauthorizedAccessError
from models.registry import (
    ChangeAction,
    GitDiffEntry,
    LookupQuery,
    NodeLocation,
    NodeStatus,
    NodeType,
    RegistryKeeperInput,
    RegistryNode,
    UpdateProposal,
)
from storage.registry_store import CodeRegistryStore
from agents.graph.registry_keeper import REGISTRY_KEEPER_METADATA, RegistryKeeper


@pytest.fixture
def store():
    """Provides an isolated in-memory CodeRegistryStore."""
    return CodeRegistryStore(persistence_path=":memory:")


def test_agent_metadata():
    """Verify Registry Keeper agent specification strictly matches system spec."""
    assert REGISTRY_KEEPER_METADATA.id == "registry_keeper"
    assert REGISTRY_KEEPER_METADATA.name == "Registry Keeper"
    assert REGISTRY_KEEPER_METADATA.layer == "graph"
    assert REGISTRY_KEEPER_METADATA.role == "Single source of truth (the list)"
    assert REGISTRY_KEEPER_METADATA.access == "registry-write"
    assert REGISTRY_KEEPER_METADATA.model_tier == "small"
    assert REGISTRY_KEEPER_METADATA.optional is False
    assert set(REGISTRY_KEEPER_METADATA.tools) == {"registry.read", "registry.write", "git.diff"}
    assert "update_proposals_from_structure_mapper" in REGISTRY_KEEPER_METADATA.inputs
    assert "updated_registry" in REGISTRY_KEEPER_METADATA.outputs
    assert "unresolved_items_list" in REGISTRY_KEEPER_METADATA.outputs


def test_registry_write_access_control(store):
    """Verify only agents with 'registry-write' permission can write to the store."""
    node = RegistryNode(
        id="file:src/app.py",
        name="app.py",
        type=NodeType.FILE,
        location=NodeLocation(path="src/app.py"),
        hash="hash123",
    )

    # Unauthorized agent (e.g. structure_mapper has read-only access to registry directly)
    with pytest.raises(UnauthorizedAccessError):
        store.write_node(node=node, access_token="read-only", source_agent="structure_mapper")

    # Authorized agent (registry_keeper with 'registry-write')
    written_node, log_entry = store.write_node(
        node=node,
        access_token="registry-write",
        source_agent="registry_keeper",
    )
    assert written_node.id == "file:src/app.py"
    assert log_entry is not None
    assert log_entry.action == ChangeAction.CREATE


def test_structure_mapper_proposals_flow(store):
    """Verify processing of node proposals from Structure Mapper."""
    keeper = RegistryKeeper(store=store)

    file_node = RegistryNode(
        id="file:src/auth.py",
        name="auth.py",
        type=NodeType.FILE,
        location=NodeLocation(path="src/auth.py"),
        hash="hash_file_1",
    )
    func_node = RegistryNode(
        id="func:src/auth.py:verify_jwt",
        name="verify_jwt",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="src/auth.py", start_line=10, end_line=25, signature="def verify_jwt(token: str) -> bool"),
        hash="hash_func_1",
    )
    invalid_node = RegistryNode(
        id="",  # missing ID
        name="",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="src/auth.py"),
        hash="",
    )

    inputs = RegistryKeeperInput(
        update_proposals_from_structure_mapper=[
            UpdateProposal(source_agent="structure_mapper", node=file_node),
            UpdateProposal(source_agent="structure_mapper", node=func_node),
            UpdateProposal(source_agent="structure_mapper", node=invalid_node),
        ]
    )

    output = keeper.execute(inputs)

    # 2 valid nodes written, 1 invalid node in unresolved items
    assert len(output.updated_registry) == 2
    assert len(output.unresolved_items_list) == 1
    assert "Node validation failed" in output.unresolved_items_list[0].reason

    # Verify store contains nodes
    assert store.get("file:src/auth.py") is not None
    assert store.get("func:src/auth.py:verify_jwt") is not None
    assert store.count() == 2

    # Verify change log entries
    assert len(output.change_log) == 2
    assert output.change_log[0].action == ChangeAction.CREATE


def test_hash_update_and_idempotency(store):
    """Verify hash updates increment versions, and identical writes are idempotent."""
    keeper = RegistryKeeper(store=store)

    initial_func = RegistryNode(
        id="func:src/math.py:add",
        name="add",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="src/math.py", start_line=1, end_line=3, signature="def add(a, b): return a + b"),
        hash="hash_v1",
    )

    # Initial registration
    out1 = keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=initial_func)
            ]
        )
    )
    assert len(out1.updated_registry) == 1
    assert out1.updated_registry[0].version == 1
    assert len(out1.change_log) == 1

    # Idempotent write (no change in hash or location)
    out2 = keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=initial_func)
            ]
        )
    )
    assert len(out2.change_log) == 0  # No redundant log entry

    # Update with new code hash
    updated_func = initial_func.model_copy(deep=True)
    updated_func.hash = "hash_v2_new_implementation"
    out3 = keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=updated_func)
            ]
        )
    )
    assert len(out3.updated_registry) == 1
    assert out3.updated_registry[0].version == 2
    assert len(out3.change_log) == 1
    assert out3.change_log[0].action == ChangeAction.UPDATE
    assert out3.change_log[0].old_hash == "hash_v1"
    assert out3.change_log[0].new_hash == "hash_v2_new_implementation"


def test_git_diff_file_deletion(store):
    """Verify file deletion via git diff purges file and all internal child nodes."""
    keeper = RegistryKeeper(store=store)

    # Prepopulate file, class, function
    file_node = RegistryNode(
        id="file:src/legacy.py",
        name="legacy.py",
        type=NodeType.FILE,
        location=NodeLocation(path="src/legacy.py"),
        hash="h1",
    )
    class_node = RegistryNode(
        id="class:src/legacy.py:LegacyService",
        name="LegacyService",
        type=NodeType.CLASS,
        location=NodeLocation(path="src/legacy.py", start_line=5, end_line=50),
        hash="h2",
    )
    keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=file_node),
                UpdateProposal(source_agent="structure_mapper", node=class_node),
            ]
        )
    )
    assert store.count() == 2

    # Commit git diff reports file deleted
    out_diff = keeper.execute(
        RegistryKeeperInput(
            git_diffs=[
                GitDiffEntry(change_type="D", path="src/legacy.py")
            ]
        )
    )

    # Active nodes should now be 0
    assert store.count() == 0
    assert store.get("file:src/legacy.py") is None
    assert store.get("class:src/legacy.py:LegacyService") is None
    assert len(out_diff.change_log) == 2
    assert all(entry.action == ChangeAction.DELETE for entry in out_diff.change_log)


def test_git_diff_file_rename(store):
    """Verify file rename updates file path and ID remapping."""
    keeper = RegistryKeeper(store=store)

    file_node = RegistryNode(
        id="file:src/util.py",
        name="util.py",
        type=NodeType.FILE,
        location=NodeLocation(path="src/util.py"),
        hash="h_util",
    )
    func_node = RegistryNode(
        id="func:src/util.py:format_date",
        name="format_date",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="src/util.py", start_line=1, end_line=10),
        hash="h_func",
    )
    keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=file_node),
                UpdateProposal(source_agent="structure_mapper", node=func_node),
            ]
        )
    )

    # Commit diff reports file renamed: src/util.py -> src/helpers.py
    out_rename = keeper.execute(
        RegistryKeeperInput(
            git_diffs=[
                GitDiffEntry(change_type="R", old_path="src/util.py", path="src/helpers.py")
            ]
        )
    )

    assert len(out_rename.change_log) == 2
    assert all(entry.action == ChangeAction.RENAME for entry in out_rename.change_log)

    # Check that new path is queryable
    nodes_in_helpers = store.get_by_path("src/helpers.py")
    assert len(nodes_in_helpers) == 2
    assert store.get("file:src/helpers.py") is not None
    assert store.get("func:src/helpers.py:format_date") is not None
    assert store.get("file:src/util.py") is None


def test_relationship_linker_endpoint_verification(store):
    """
    Verify Relationship Linker edges:
    Endpoints are looked up; if missing, placed in unresolved queue instead of being guessed.
    """
    keeper = RegistryKeeper(store=store)

    # Only register caller node
    caller_node = RegistryNode(
        id="func:src/controller.py:handle_request",
        name="handle_request",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="src/controller.py"),
        hash="h_req",
    )
    keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=caller_node)
            ]
        )
    )

    # Case 1: Target endpoint missing -> goes to unresolved queue
    out_missing = keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_relationship_linker=[
                UpdateProposal(
                    source_agent="relationship_linker",
                    details={
                        "source_id": "func:src/controller.py:handle_request",
                        "target_id": "func:src/missing.py:nonexistent_func",
                        "edge_type": "call",
                    },
                )
            ]
        )
    )
    assert len(out_missing.unresolved_items_list) == 1
    assert "Target endpoint 'func:src/missing.py:nonexistent_func' does not exist in registry" in out_missing.unresolved_items_list[0].reason

    # Case 2: Register target node, now edge should succeed
    target_node = RegistryNode(
        id="func:src/service.py:execute_command",
        name="execute_command",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="src/service.py"),
        hash="h_cmd",
    )
    keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=target_node)
            ]
        )
    )

    out_success = keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_relationship_linker=[
                UpdateProposal(
                    source_agent="relationship_linker",
                    details={
                        "source_id": "func:src/controller.py:handle_request",
                        "target_id": "func:src/service.py:execute_command",
                        "edge_type": "call",
                    },
                )
            ]
        )
    )
    assert len(out_success.unresolved_items_list) == 0
    updated_caller = store.get("func:src/controller.py:handle_request")
    edges = updated_caller.metadata.get("outgoing_edges", [])
    assert len(edges) == 1
    assert edges[0]["target_id"] == "func:src/service.py:execute_command"


def test_data_service_mapper_proposals(store):
    """Verify registration of APIs, DB tables, and services from Data & Service Mapper."""
    keeper = RegistryKeeper(store=store)

    api_node = RegistryNode(
        id="api:POST:/api/v1/checkout",
        name="Checkout API",
        type=NodeType.API,
        location=NodeLocation(
            path="routes/checkout.py",
            endpoint_method="POST",
            endpoint_route="/api/v1/checkout",
        ),
        hash="hash_api_1",
    )
    table_node = RegistryNode(
        id="table:orders",
        name="orders",
        type=NodeType.TABLE,
        location=NodeLocation(path="migrations/001_create_orders.sql", table_name="orders"),
        hash="hash_table_1",
    )
    service_node = RegistryNode(
        id="service:order-processor",
        name="order-processor",
        type=NodeType.SERVICE,
        location=NodeLocation(path="services/order_processor", service_name="order-processor"),
        hash="hash_service_1",
    )

    output = keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_data_service_mapper=[
                UpdateProposal(source_agent="data_service_mapper", node=api_node),
                UpdateProposal(source_agent="data_service_mapper", node=table_node),
                UpdateProposal(source_agent="data_service_mapper", node=service_node),
            ]
        )
    )

    assert len(output.updated_registry) == 3
    assert len(output.unresolved_items_list) == 0
    assert store.get("api:POST:/api/v1/checkout") is not None
    assert store.get("table:orders") is not None
    assert store.get("service:order-processor") is not None


def test_lookup_queries(store):
    """Verify lookup resolution by ID and filters."""
    keeper = RegistryKeeper(store=store)

    node = RegistryNode(
        id="func:src/user.py:get_user_by_id",
        name="get_user_by_id",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="src/user.py", start_line=12, end_line=20),
        hash="h_user",
    )
    keeper.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=node)
            ]
        )
    )

    out = keeper.execute(
        RegistryKeeperInput(
            lookups=[
                LookupQuery(id="func:src/user.py:get_user_by_id"),
                LookupQuery(path="src/user.py", name="get_user_by_id"),
                LookupQuery(id="func:nonexistent:fn"),
            ]
        )
    )

    assert out.lookup_answers["func:src/user.py:get_user_by_id"] is not None
    assert out.lookup_answers["func:nonexistent:fn"] is None


def test_store_disk_persistence(tmp_path):
    """Verify saving and reloading registry state to/from disk."""
    dump_file = tmp_path / "registry.json"
    store1 = CodeRegistryStore(persistence_path=str(dump_file))
    keeper1 = RegistryKeeper(store=store1)

    node = RegistryNode(
        id="file:src/main.py",
        name="main.py",
        type=NodeType.FILE,
        location=NodeLocation(path="src/main.py"),
        hash="hash_main",
    )
    keeper1.execute(
        RegistryKeeperInput(
            update_proposals_from_structure_mapper=[
                UpdateProposal(source_agent="structure_mapper", node=node)
            ]
        )
    )

    assert dump_file.exists()

    # Create new store from the same persisted file
    store2 = CodeRegistryStore(persistence_path=str(dump_file))
    reloaded_node = store2.get("file:src/main.py")
    assert reloaded_node is not None
    assert reloaded_node.name == "main.py"
    assert len(store2.get_change_log()) == 1


def test_real_repository_ast_scanning(tmp_path):
    """
    Creates real Python files on disk, scans the folder using RegistryKeeper,
    and validates real AST extraction of files, classes, and methods with accurate line numbers and hashes.
    """
    # Create a real mini project structure
    service_file = tmp_path / "payment.py"
    service_file.write_text(
        '"""Payment processing module."""\n'
        '\n'
        'class PaymentGateway:\n'
        '    """Handles payment transactions."""\n'
        '    def authorize(self, card_number: str, amount: float) -> bool:\n'
        '        return True\n'
        '\n'
        '    def refund(self, txn_id: str) -> bool:\n'
        '        return True\n'
        '\n'
        'def compute_fee(amount: float) -> float:\n'
        '    return amount * 0.029\n'
    )

    store = CodeRegistryStore(persistence_path=":memory:")
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    output = keeper.scan_repository(repo_path=str(tmp_path))

    assert output.stats["total_active_nodes"] >= 4
    file_node = store.get("file:payment.py")
    assert file_node is not None
    assert file_node.type == NodeType.FILE

    class_node = store.get("class:payment.py:PaymentGateway")
    assert class_node is not None
    assert class_node.location.start_line == 3
    assert class_node.location.end_line == 9

    auth_method = store.get("func:payment.py:PaymentGateway.authorize")
    assert auth_method is not None
    assert "def authorize" in auth_method.location.signature

    func_node = store.get("func:payment.py:compute_fee")
    assert func_node is not None
    assert func_node.location.start_line == 11
    assert func_node.hash != ""


def test_real_git_sync(tmp_path):
    """
    Initializes a real git repo, commits a file, modifies it, and tests real sync_with_git.
    """
    # Initialize a temporary git repository
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@agent.internal"], cwd=str(tmp_path), check=True)

    test_file = tmp_path / "service.py"
    test_file.write_text("def ping(): return 'pong'\n")

    subprocess.run(["git", "add", "service.py"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(tmp_path), check=True)

    store = CodeRegistryStore(persistence_path=":memory:")
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    # Initial scan
    keeper.scan_repository(repo_path=str(tmp_path))
    assert store.get("func:service.py:ping") is not None

    # Now modify the file
    test_file.write_text("def ping(): return 'pong v2'\n")

    # Run real sync_with_git
    output = keeper.sync_with_git()
    assert len(output.updated_registry) > 0

    updated_fn = store.get("func:service.py:ping")
    assert updated_fn.version == 2
