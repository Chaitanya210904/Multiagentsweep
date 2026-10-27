"""
Unit and Integration Tests for Agent 6: Data & Service Mapper (Layer: Graph).
Verifies:
1. Agent metadata, read-only permissions, and tool inventory.
2. API endpoint extraction from web decorators and linking to code handlers (api_to_code).
3. Database table extraction from SQL migrations and ORM schemas.
4. SQL query detection and linking caller functions to tables (code_to_table).
5. External service/queue extraction from config/env files and client call linking (service_to_service).
6. Zero-guessing compliance (unresolved queue for missing endpoints).
7. End-to-end integration with Structure Mapper and Registry Keeper.
"""

from pathlib import Path
import pytest

from agents.graph.data_service_mapper import (
    DATA_SERVICE_MAPPER_METADATA,
    DataServiceMapper,
)
from agents.graph.registry_keeper import RegistryKeeper
from agents.graph.structure_mapper import StructureMapper
from core.exceptions import UnauthorizedAccessError
from models.data_service import (
    DataServiceMapperInput,
    SystemEdgeType,
)
from models.registry import (
    NodeLocation,
    NodeType,
    RegistryNode,
)
from storage.registry_store import CodeRegistryStore


@pytest.fixture
def store():
    """In-memory store fixture guaranteeing clean isolation for each test."""
    return CodeRegistryStore(persistence_path=":memory:")


def test_data_service_mapper_metadata():
    """Verifies Agent 6 metadata matches platform architectural specification."""
    meta = DATA_SERVICE_MAPPER_METADATA
    assert meta.id == "data_service_mapper"
    assert meta.name == "Data & Service Mapper"
    assert meta.layer == "graph"
    assert meta.role == "Graph agent 3: system edges"
    assert meta.access == "read-only"
    assert "api_specs" in meta.inputs
    assert "migrations" in meta.inputs
    assert "query_code" in meta.inputs
    assert "config_files" in meta.inputs
    assert "registry" in meta.inputs
    assert "api_to_code_edges" in meta.outputs
    assert "code_to_table_edges" in meta.outputs
    assert "service_to_service_edges" in meta.outputs
    assert "unresolved_queue" in meta.outputs
    assert "registry_update_proposals" in meta.outputs
    assert "registry.lookup" in meta.tools
    assert "registry.propose" in meta.tools
    assert "graph.write_edge" in meta.tools


def test_read_only_access_enforcement(store):
    """Verifies Data & Service Mapper enforces read-only access and cannot write directly to store."""
    dsm = DataServiceMapper(store=store)
    assert dsm.access == "read-only"

    api_node = RegistryNode(
        id="api:GET:/users",
        name="GET /users",
        type=NodeType.API,
        location=NodeLocation(path="routes.py", endpoint_route="/users", endpoint_method="GET"),
        hash="hash123",
    )
    with pytest.raises(UnauthorizedAccessError):
        store.write_node(
            node=api_node,
            access_token=dsm.access,
            source_agent=dsm.id,
        )


def test_api_discovery_and_linking(store, tmp_path):
    """Verifies API endpoint discovery from decorators and linking to registered handler functions."""
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    # Create real Python web controller file
    routes_file = tmp_path / "routes.py"
    routes_file.write_text(
        "class MockApp:\n"
        "    def get(self, path): return lambda f: f\n"
        "app = MockApp()\n\n"
        "@app.get('/api/v1/users')\n"
        "def list_users():\n"
        "    return []\n\n"
        "@app.get('/api/v1/missing')\n"
        "def unindexed_handler():\n"
        "    pass\n",
        encoding="utf-8",
    )

    # Register only list_users in registry
    handler_node = RegistryNode(
        id="func:routes.py:list_users",
        name="list_users",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="routes.py", start_line=5, end_line=6),
        hash="hash_handler",
    )
    keeper.write_tool.write_node(handler_node)

    dsm = DataServiceMapper(store=store, repo_root=str(tmp_path))
    output = dsm.execute(DataServiceMapperInput())

    # 2 API nodes discovered
    api_ids = {a.id for a in output.api_nodes}
    assert "api:GET:/api/v1/users" in api_ids
    assert "api:GET:/api/v1/missing" in api_ids

    # 1 verified api_to_code edge to list_users
    api_edges = [e for e in output.api_to_code_edges if e.type == SystemEdgeType.API_TO_CODE]
    assert len(api_edges) == 1
    assert api_edges[0].source_id == "api:GET:/api/v1/users"
    assert api_edges[0].target_id == handler_node.id
    assert api_edges[0].operation == "GET"

    # 1 unresolved queue item for unindexed_handler (never guessed)
    unresolved_routes = {u.raw_target for u in output.unresolved_queue if u.edge_type == SystemEdgeType.API_TO_CODE}
    assert "unindexed_handler" in unresolved_routes


def test_database_table_discovery(store, tmp_path):
    """Verifies table discovery from SQL CREATE TABLE and Python ORM schemas."""
    # Create SQL migration
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(parents=True)
    schema_sql = migrations_dir / "001_init.sql"
    schema_sql.write_text(
        "CREATE TABLE IF NOT EXISTS users (\n"
        "    id INTEGER PRIMARY KEY,\n"
        "    email VARCHAR(255) NOT NULL\n"
        ");\n\n"
        "CREATE TABLE products (\n"
        "    id INTEGER PRIMARY KEY,\n"
        "    price DECIMAL\n"
        ");\n",
        encoding="utf-8",
    )

    # Create Python ORM model
    models_file = tmp_path / "models.py"
    models_file.write_text(
        "class Order:\n"
        "    __tablename__ = 'orders'\n",
        encoding="utf-8",
    )

    dsm = DataServiceMapper(store=store, repo_root=str(tmp_path))
    output = dsm.execute(DataServiceMapperInput())

    table_names = {t.name for t in output.table_nodes}
    assert "users" in table_names
    assert "products" in table_names
    assert "orders" in table_names


def test_sql_query_to_table_linking(store, tmp_path):
    """Verifies that SQL queries in code link caller functions to registered database tables."""
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    # Register table 'customers' in registry
    cust_table = RegistryNode(
        id="table:customers",
        name="customers",
        type=NodeType.TABLE,
        location=NodeLocation(path="migrations/001.sql", table_name="customers"),
        hash="hash_cust",
    )
    keeper.write_tool.write_node(cust_table)

    # Code with query to 'customers' AND query to unindexed 'secret_logs'
    repo_file = tmp_path / "repository.py"
    repo_file.write_text(
        "def get_customer(cid):\n"
        "    query = 'SELECT * FROM customers WHERE id = 1'\n"
        "    return query\n\n"
        "def audit():\n"
        "    query = 'INSERT INTO secret_logs VALUES (1)'\n",
        encoding="utf-8",
    )

    # Register get_customer function
    func_node = RegistryNode(
        id="func:repository.py:get_customer",
        name="get_customer",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="repository.py", start_line=1, end_line=3),
        hash="hash_fn",
    )
    keeper.write_tool.write_node(func_node)

    dsm = DataServiceMapper(store=store, repo_root=str(tmp_path))
    output = dsm.execute(DataServiceMapperInput())

    # Verified code_to_table edge to 'customers'
    table_edges = [e for e in output.code_to_table_edges if e.type == SystemEdgeType.CODE_TO_TABLE]
    assert len(table_edges) >= 1
    assert any(e.target_id == "table:customers" and e.operation == "SELECT" for e in table_edges)

    # Unresolved query to unindexed 'secret_logs' (never guessed)
    unresolved_tables = {u.raw_target for u in output.unresolved_queue if u.edge_type == SystemEdgeType.CODE_TO_TABLE}
    assert "secret_logs" in unresolved_tables


def test_external_service_discovery_and_linking(store, tmp_path):
    """Verifies external service discovery from .env configs and client call linking."""
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))

    # Create .env config
    env_file = tmp_path / ".env"
    env_file.write_text(
        "REDIS_URL=redis://localhost:6379\n"
        "STRIPE_API_KEY=sk_test_12345\n",
        encoding="utf-8",
    )

    # Code making external client calls
    client_file = tmp_path / "gateway.py"
    client_file.write_text(
        "def cache_data(key, val):\n"
        "    redis_client.set(key, val)\n\n"
        "def send_email():\n"
        "    boto3.client('s3')\n",  # s3 is not in .env
        encoding="utf-8",
    )

    dsm = DataServiceMapper(store=store, repo_root=str(tmp_path))
    output = dsm.execute(DataServiceMapperInput())

    # Discovered services from .env
    service_names = {s.name for s in output.service_nodes}
    assert "redis" in service_names
    assert "stripe" in service_names

    # Verified call to redis
    service_edges = [e for e in output.service_to_service_edges if e.type == SystemEdgeType.SERVICE_TO_SERVICE]
    assert any(e.target_id == "service:redis" for e in service_edges)

    # Unresolved call to s3 (since s3 is not configured in .env / registry)
    unresolved_services = {u.raw_target for u in output.unresolved_queue if u.edge_type == SystemEdgeType.SERVICE_TO_SERVICE}
    assert "aws_s3" in unresolved_services


def test_map_and_register_integration(store, tmp_path):
    """
    End-to-end integration test:
    Structure Mapper registers code nodes -> Data & Service Mapper discovers APIs, tables, services,
    and edges -> Registry Keeper registers system nodes and attaches bidirectional edges.
    """
    keeper = RegistryKeeper(store=store, repo_root=str(tmp_path))
    mapper = StructureMapper(store=store, repo_root=str(tmp_path))
    dsm = DataServiceMapper(store=store, repo_root=str(tmp_path))

    # 1. Create realistic web application codebase in tmp_path
    schema_sql = tmp_path / "schema.sql"
    schema_sql.write_text(
        "CREATE TABLE items (\n"
        "    id INT PRIMARY KEY,\n"
        "    title TEXT\n"
        ");\n",
        encoding="utf-8",
    )

    app_py = tmp_path / "app.py"
    app_py.write_text(
        "class Router:\n"
        "    def get(self, r): return lambda f: f\n"
        "router = Router()\n\n"
        "@router.get('/items')\n"
        "def get_items():\n"
        "    sql = 'SELECT * FROM items'\n"
        "    return sql\n",
        encoding="utf-8",
    )

    # 2. Structure Mapper scans and registers code nodes (Router, get_items)
    mapper_out, _ = mapper.map_and_register(registry_keeper=keeper, repo_shard=".")
    assert any(n.name == "get_items" for n in mapper_out.nodes)

    # 3. Data & Service Mapper maps and registers system nodes and edges
    dsm_out, keeper_sys_out = dsm.map_and_register(registry_keeper=keeper)

    # Verify table 'items' discovered and registered
    assert any(t.name == "items" for t in dsm_out.table_nodes)
    items_table_node = store.get("table:items")
    assert items_table_node is not None
    assert items_table_node.type == NodeType.TABLE

    # Verify API 'GET /items' discovered and registered
    api_node = store.get("api:GET:/items")
    assert api_node is not None
    assert api_node.type == NodeType.API

    # Verify bidirectional edges attached:
    # api:GET:/items -> func:app.py:get_items (api_to_code)
    assert "outgoing_edges" in api_node.metadata
    assert any(e["type"] == "api_to_code" for e in api_node.metadata["outgoing_edges"])

    handler_func_node = store.get("func:app.py:get_items")
    assert handler_func_node is not None
    assert "incoming_edges" in handler_func_node.metadata
    assert any(e["source_id"] == "api:GET:/items" for e in handler_func_node.metadata["incoming_edges"])

    # func:app.py:get_items -> table:items (code_to_table)
    assert "outgoing_edges" in handler_func_node.metadata
    assert any(e["target_id"] == "table:items" for e in handler_func_node.metadata["outgoing_edges"])
