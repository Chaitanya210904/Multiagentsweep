"""
Unit and integration tests for Agent 12: Scale & Load (Layer: Runtime).
Role: Capacity analyst.
Description: Finds N+1 queries, missing indexes and caching gaps, runs load tests, and estimates capacity.
Access: read-only
"""

import pytest

from agents.runtime.scale_load_agent import SCALE_LOAD_METADATA, ScaleLoadAgent
from core.exceptions import UnauthorizedAccessError
from models.registry import NodeLocation, NodeStatus, NodeType, RegistryNode
from models.scale_load import (
    BottleneckSeverity,
    BottleneckType,
    CapacityStatus,
    ScaleLoadInput,
    TrafficTarget,
)
from storage.registry_store import CodeRegistryStore
from tools.k6_tool import K6Tool
from tools.locust_tool import LocustTool


def test_scale_load_metadata():
    """Validates that Agent 12 metadata strictly matches the specifications."""
    meta = SCALE_LOAD_METADATA
    assert meta.id == "scale_load"
    assert meta.name == "Scale & Load"
    assert meta.layer == "runtime"
    assert meta.role == "Capacity analyst"
    assert meta.description == "Finds N+1 queries, missing indexes and caching gaps, runs load tests, and estimates capacity."
    assert meta.access == "read-only"
    assert meta.model_tier == "medium"
    assert "graph_hot_paths" in meta.inputs
    assert "query_logs" in meta.inputs
    assert "k6_or_locust_scripts" in meta.inputs
    assert "traffic_target" in meta.inputs
    assert "bottlenecks" in meta.outputs
    assert "load_test_results" in meta.outputs
    assert "capacity_estimate" in meta.outputs
    assert meta.tools == ["k6", "locust", "graph.traverse"]
    assert meta.trigger == "on request and before release"
    assert meta.optional is False


def test_read_only_access_enforcement():
    """Verifies that Scale & Load enforces strict read-only access."""
    store = CodeRegistryStore()
    agent = ScaleLoadAgent(registry_store=store)

    # Valid execution under read-only
    inp = ScaleLoadInput(
        graph_hot_paths=[],
        query_logs=[],
        k6_or_locust_scripts=[],
        traffic_target=TrafficTarget(target_rps=50.0),
    )
    out = agent.execute(inp)
    assert out is not None

    # Simulate unauthorized access escalation attempt
    with pytest.raises(UnauthorizedAccessError):
        agent.require_access("read-write")


def test_n_plus_one_query_detection():
    """Tests identification of N+1 query loops from SQL execution logs."""
    store = CodeRegistryStore()
    agent = ScaleLoadAgent(registry_store=store)

    # Simulated N+1 query: 1 parent query followed by 12 child queries in a loop
    queries = [
        {"sql": "SELECT * FROM orders WHERE user_id = 101", "duration_ms": 15.0, "caller_file": "services/order_service.py", "caller_line": 30},
    ]
    for i in range(12):
        queries.append({
            "sql": f"SELECT * FROM order_items WHERE order_id = {1000 + i}",
            "duration_ms": 12.0,
            "caller_file": "services/order_service.py",
            "caller_line": 45,
        })

    inp = ScaleLoadInput(
        query_logs=queries,
        traffic_target=TrafficTarget(target_rps=100.0),
    )
    out = agent.execute(inp)

    n1_bottlenecks = [b for b in out.bottlenecks if b.type == BottleneckType.N_PLUS_ONE_QUERY]
    assert len(n1_bottlenecks) >= 1

    n1 = n1_bottlenecks[0]
    assert n1.table_name == "order_items"
    assert n1.execution_count == 12
    assert n1.total_time_ms >= 140.0
    assert "order_id" in n1.query_pattern
    assert "eager loading" in n1.remediation.lower() or "bulk retrieval" in n1.remediation.lower()
    assert n1.file_path == "services/order_service.py"
    assert n1.line_number == 45


def test_missing_index_detection_and_ddl_generation():
    """Tests identification of missing indexes from sequential scans and slow filtered queries."""
    store = CodeRegistryStore()
    agent = ScaleLoadAgent(registry_store=store)

    queries = [
        {
            "sql": "SELECT * FROM customers WHERE email = 'test@example.com'",
            "duration_ms": 250.0,
            "plan": "Seq Scan on customers (cost=0.00..4520.12 rows=1 width=128)",
            "caller_file": "services/auth_service.py",
            "caller_line": 85,
        }
    ]

    inp = ScaleLoadInput(
        query_logs=queries,
        traffic_target=TrafficTarget(target_rps=50.0),
    )
    out = agent.execute(inp)

    idx_bottlenecks = [b for b in out.bottlenecks if b.type == BottleneckType.MISSING_INDEX]
    assert len(idx_bottlenecks) >= 1

    idx = idx_bottlenecks[0]
    assert idx.table_name == "customers"
    assert idx.severity in (BottleneckSeverity.HIGH, BottleneckSeverity.CRITICAL)
    assert any("CREATE INDEX" in ev for ev in idx.evidence)
    assert len(out.capacity_estimate.recommended_indexes) >= 1
    assert "CREATE INDEX idx_customers_email ON customers (email);" in out.capacity_estimate.recommended_indexes[0]


def test_caching_gap_detection():
    """Tests detection of caching gaps for high-frequency repetitive read queries."""
    store = CodeRegistryStore()
    agent = ScaleLoadAgent(registry_store=store)

    # 10 identical SELECT queries on product metadata
    queries = [
        {"sql": "SELECT name, price, description FROM products WHERE id = 42", "duration_ms": 25.0}
        for _ in range(8)
    ]

    inp = ScaleLoadInput(
        query_logs=queries,
        traffic_target=TrafficTarget(target_rps=100.0),
    )
    out = agent.execute(inp)

    cache_bottlenecks = [b for b in out.bottlenecks if b.type == BottleneckType.CACHING_GAP]
    assert len(cache_bottlenecks) >= 1
    c_btnk = cache_bottlenecks[0]
    assert c_btnk.table_name == "products"
    assert c_btnk.execution_count == 8
    assert "Redis" in c_btnk.remediation or "cache" in c_btnk.remediation.lower()


def test_k6_tool_script_parsing_and_thresholds():
    """Tests K6Tool parsing of JavaScript k6 script options and threshold evaluation."""
    k6_tool = K6Tool()

    script = """
    import http from 'k6/http';
    import { check } from 'k6';

    export const options = {
      vus: 25,
      duration: '30s',
      thresholds: {
        'http_req_duration': ['p(95)<300'],
        'http_req_failed': ['rate<0.01'],
      },
    };

    export default function () {
      const res = http.get('http://api.local/v1/checkout');
      check(res, { 'status is 200': (r) => r.status === 200 });
    }
    """

    res = k6_tool.execute_or_eval(script_or_path=script)
    assert res.engine == "k6"
    assert res.vus_or_users == 25
    assert res.duration_seconds == 30.0
    assert res.metrics.requests_total > 0
    assert res.metrics.rps > 0.0
    assert res.metrics.latency_p95_ms > 0.0


def test_locust_tool_stats_csv_parsing():
    """Tests LocustTool parsing of standard Locust CSV stats output."""
    locust_tool = LocustTool()

    csv_content = """Type,Name,Request Count,Failure Count,Median Response Time,Average Response Time,Min Response Time,Max Response Time,Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%
GET,/api/v1/catalog,250,5,45.0,52.4,12.0,210.0,4096,25.0,0.5,45.0,48.0,52.0,58.0,75.0,92.0,140.0,180.0,205.0,210.0,210.0
None,Total,250,5,45.0,52.4,12.0,210.0,4096,25.0,0.5,45.0,48.0,52.0,58.0,75.0,92.0,140.0,180.0,205.0,210.0,210.0
"""

    res = locust_tool.execute_or_eval(script_or_path=csv_content, users=20, duration_seconds=10.0)
    assert res.engine == "locust"
    assert res.metrics.requests_total == 250
    assert res.metrics.requests_failed == 5
    assert res.metrics.latency_p50_ms == 45.0
    assert res.metrics.latency_p95_ms == 92.0
    assert res.metrics.latency_p99_ms == 180.0
    assert res.metrics.rps == 25.0
    assert res.thresholds_passed is True


def test_end_to_end_capacity_analysis_pipeline():
    """Tests end-to-end capacity analysis linking graph hot paths, query bottlenecks, and capacity SLA."""
    store = CodeRegistryStore()

    # Register API node and Table node
    api_node = RegistryNode(
        id="api:GET:/api/v1/orders",
        name="get_orders",
        type=NodeType.API,
        location=NodeLocation(
            path="api/orders.py",
            start_line=10,
            end_line=50,
            endpoint_method="GET",
            endpoint_route="/api/v1/orders",
        ),
        signature="def get_orders(): ...",
        hash="apihash",
        status=NodeStatus.ACTIVE,
    )
    store.write_node(api_node, access_token="registry-write", source_agent="registry_keeper")

    table_node = RegistryNode(
        id="table:orders",
        name="orders",
        type=NodeType.TABLE,
        location=NodeLocation(path="db/schema.sql", start_line=1, end_line=20),
        signature="CREATE TABLE orders",
        hash="tblhash",
        status=NodeStatus.ACTIVE,
    )
    store.write_node(table_node, access_token="registry-write", source_agent="registry_keeper")

    agent = ScaleLoadAgent(registry_store=store)

    # 20 N+1 queries on order_items
    query_log = [
        {"sql": "SELECT * FROM orders WHERE status = 'PENDING'", "duration_ms": 80.0, "caller_file": "api/orders.py", "caller_line": 25}
    ]
    for _ in range(15):
        query_log.append({
            "sql": "SELECT * FROM order_items WHERE order_id = ?",
            "duration_ms": 30.0,
            "caller_file": "api/orders.py",
            "caller_line": 35,
        })

    inp = ScaleLoadInput(
        graph_hot_paths=["api:GET:/api/v1/orders"],
        query_logs=query_log,
        traffic_target=TrafficTarget(
            target_rps=500.0,  # High target SLA
            target_p99_latency_ms=100.0,
            peak_concurrent_users=50,
        ),
    )

    out = agent.execute(inp)

    assert len(out.bottlenecks) >= 1
    assert out.capacity_estimate is not None
    assert out.capacity_estimate.target_rps == 500.0
    # Because target RPS is 500 and single instance max RPS is around 40-70 under N+1 load:
    assert out.capacity_estimate.status in (CapacityStatus.CAPACITY_DEFICIT, CapacityStatus.CAPACITY_MARGINAL)
    assert out.capacity_estimate.estimated_required_instances >= 1
    assert out.capacity_estimate.caching_throughput_multiplier > 1.0
    assert "Capacity Analysis Status" in out.summary
