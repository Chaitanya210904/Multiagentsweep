"""
Comprehensive tests for Agent 11: Observability (Layer: Runtime).
Validates:
- Metadata compliance (id, name, layer, role, access, model_tier, inputs, outputs, tools, trigger)
- Strict read-only access enforcement (UnauthorizedAccessError)
- Prometheus metric anomaly detection (error rate spikes, p99 latency, CPU saturation, DB slowdowns)
- Logs search tool: Python/JS stack trace parsing, exception class extraction, OTLP log attributes
- Traces search tool: failed spans, latency bottlenecks, code location attributes
- Root cause synthesis: exact code node linkage via Code Registry (file and line number matching)
- End-to-end operational observability audit and system health status calculation
"""

from pathlib import Path
import tempfile
import pytest

from agents.runtime.observability_agent import OBSERVABILITY_METADATA, ObservabilityAgent
from core.exceptions import UnauthorizedAccessError
from models.observability import (
    AnomalySeverity,
    AnomalyType,
    MetricAnomaly,
    ObservabilityInput,
    ObservabilityOutput,
    ProbableRootCause,
)
from models.registry import NodeLocation, NodeStatus, NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore
from tools.logs_search_tool import LogsSearchTool
from tools.prometheus_query_tool import PrometheusQueryTool
from tools.traces_search_tool import TracesSearchTool


def test_observability_metadata():
    """Validates Agent 11 metadata specification against system architecture roadmap."""
    meta = OBSERVABILITY_METADATA
    assert meta.id == "observability"
    assert meta.name == "Observability"
    assert meta.layer == "runtime"
    assert meta.role == "Logs, metrics and traces reader"
    assert meta.access == "read-only"
    assert meta.model_tier == "medium"
    assert "opentelemetry_and_prometheus_data" in meta.inputs
    assert "service_map" in meta.inputs
    assert "error_and_latency_anomalies" in meta.outputs
    assert "probable_root_cause_linked_to_nodes" in meta.outputs
    assert set(meta.tools) == {"prometheus.query", "logs.search", "traces.search", "registry.lookup"}
    assert meta.trigger == "timer and on alert"
    assert meta.optional is False


def test_read_only_access_enforcement():
    """Ensures agent execution strictly rejects non-read-only access permissions."""
    agent = ObservabilityAgent()
    agent.metadata.access = "read-write"

    payload = ObservabilityInput(opentelemetry_and_prometheus_data={})
    with pytest.raises(UnauthorizedAccessError) as exc_info:
        agent.execute(payload)

    assert "read-only" in str(exc_info.value)


def test_prometheus_query_tool_anomalies():
    """Tests detection of metric anomalies: error spikes, latency degradation, CPU, and DB pressure."""
    tool = PrometheusQueryTool()

    metrics_samples = [
        # 1. Error rate spike (14.2% vs baseline 0.5%)
        {
            "metric_name": "http_requests_error_rate_pct",
            "service_name": "checkout-service",
            "endpoint_route": "/api/v1/checkout",
            "current_value": 14.2,
            "baseline_value": 0.5,
        },
        # 2. Latency spike (1650ms vs threshold 500ms)
        {
            "metric_name": "http_request_duration_seconds",
            "service_name": "search-service",
            "endpoint_route": "/api/v1/search",
            "current_value": 1.65,  # 1.65s = 1650ms
            "baseline_value": 0.20,
        },
        # 3. CPU Saturation (94%)
        {
            "metric_name": "system_cpu_usage_pct",
            "service_name": "worker-pool",
            "current_value": 94.0,
            "baseline_value": 45.0,
        },
        # 4. Database query slowdown (3.8s)
        {
            "metric_name": "db_query_duration_seconds",
            "service_name": "postgres-orders",
            "current_value": 3.8,
            "baseline_value": 0.05,
        },
    ]

    anomalies = tool.query(
        metrics_data=metrics_samples,
        error_rate_threshold_pct=1.0,
        latency_threshold_ms=500.0,
    )

    types = {a.anomaly_type for a in anomalies}
    assert AnomalyType.ERROR_RATE_SPIKE in types
    assert AnomalyType.LATENCY_SPIKE in types
    assert AnomalyType.CPU_SATURATION in types
    assert AnomalyType.DATABASE_SLOWDOWN in types

    # Check error spike details
    err_anom = next(a for a in anomalies if a.anomaly_type == AnomalyType.ERROR_RATE_SPIKE)
    assert err_anom.severity == AnomalySeverity.CRITICAL
    assert err_anom.service_name == "checkout-service"
    assert err_anom.deviation_factor > 10.0


def test_logs_search_stack_trace_extraction():
    """Tests log searching and stack trace parsing for Python and JSON logs."""
    tool = LogsSearchTool()

    # Raw text traceback
    raw_log = """
2026-10-27 22:00:01 [ERROR] [checkout.handler] Failed processing customer order
Traceback (most recent call last):
  File "/app/services/checkout.py", line 42, in process_order
    user_balance = account["balance"]
KeyError: 'balance'
"""

    incidents = tool.search(raw_log)
    assert len(incidents) >= 1

    inc = incidents[0]
    assert inc.file_path == "/app/services/checkout.py"
    assert inc.line_number == 42
    assert inc.function_name == "process_order"
    assert inc.exception_class == "KeyError"
    assert "balance" in inc.error_message


def test_logs_search_structured_otlp_records():
    """Tests parsing of OpenTelemetry structured log records with correlation attributes."""
    tool = LogsSearchTool()

    otlp_records = [
        {
            "SeverityText": "ERROR",
            "Body": "Database query timed out after 5000ms",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "span_id": "00f067aa0ba902b7",
            "attributes": {
                "service.name": "payment-gateway",
                "code.filepath": "gateway/client.py",
                "code.lineno": 88,
                "code.function": "execute_charge",
            },
        }
    ]

    incidents = tool.search(otlp_records)
    assert len(incidents) == 1
    assert incidents[0].file_path == "gateway/client.py"
    assert incidents[0].line_number == 88
    assert incidents[0].function_name == "execute_charge"
    assert incidents[0].trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_traces_search_spans_and_bottlenecks():
    """Tests analyzing distributed trace spans for errors, exceptions, and latency bottlenecks."""
    tool = TracesSearchTool()

    spans = [
        # Failed span with exception
        {
            "trace_id": "trace-101",
            "span_id": "span-201",
            "name": "POST /api/v1/charge",
            "duration_ms": 120.0,
            "status": {"code": 2, "message": "Stripe API Connection Refused"},
            "attributes": {
                "service.name": "payment-service",
                "http.route": "/api/v1/charge",
                "http.status_code": 502,
                "code.filepath": "services/payment.py",
                "code.lineno": 115,
                "code.function": "charge_card",
            },
            "events": [
                {
                    "name": "exception",
                    "attributes": {
                        "exception.type": "ConnectionRefusedError",
                        "exception.message": "Cannot connect to host api.stripe.com:443",
                    },
                }
            ],
        },
        # Slow bottleneck span (850ms > 500ms threshold)
        {
            "trace_id": "trace-102",
            "span_id": "span-202",
            "name": "SELECT * FROM orders",
            "duration_ms": 850.0,
            "status": {"code": "OK"},
            "attributes": {
                "service.name": "order-service",
                "db.statement": "SELECT * FROM orders WHERE customer_id = 9999 FOR UPDATE",
                "code.filepath": "models/order.py",
                "code.lineno": 50,
            },
        },
    ]

    incidents = tool.search(spans, latency_threshold_ms=500.0)
    assert len(incidents) == 2

    # Verify error span
    err_span = next(s for s in incidents if s.status_code == "ERROR")
    assert err_span.exception_class == "ConnectionRefusedError"
    assert err_span.file_path == "services/payment.py"
    assert err_span.line_number == 115

    # Verify bottleneck span
    slow_span = next(s for s in incidents if s.is_bottleneck)
    assert slow_span.duration_ms == 850.0
    assert "SELECT * FROM orders" in slow_span.db_statement


def test_root_cause_linking_to_registry_code_nodes():
    """Validates connecting runtime log exception directly to canonical RegistryNode."""
    store = CodeRegistryStore()

    # Register an application function node in the registry
    target_node = RegistryNode(
        id="func:services/order_service.py:create_order",
        name="create_order",
        type=NodeType.FUNCTION,
        location=NodeLocation(
            path="services/order_service.py",
            start_line=30,
            end_line=60,
        ),
        signature="def create_order(cart_id: str, user_id: str) -> Order",
        hash="hash123",
        status=NodeStatus.ACTIVE,
    )
    store.write_node(target_node, access_token="registry-write", source_agent="registry_keeper")

    agent = ObservabilityAgent(registry_store=store)

    # Ingest runtime exception occurring at line 45 (inside create_order function: lines 30-60)
    log_text = """
2026-10-27 22:05:00 [ERROR] Order processing crashed
Traceback (most recent call last):
  File "services/order_service.py", line 45, in create_order
    item = cart["items"][0]
IndexError: list index out of range
"""

    payload = ObservabilityInput(
        opentelemetry_and_prometheus_data={"logs": log_text}
    )

    out = agent.execute(payload)

    assert len(out.probable_root_cause_linked_to_nodes) == 1
    rc = out.probable_root_cause_linked_to_nodes[0]

    # Verify exact linkage
    assert rc.linked_node_id == "func:services/order_service.py:create_order"
    assert rc.file_path == "services/order_service.py"
    assert rc.line_number == 45
    assert rc.exception_class == "IndexError"
    assert rc.confidence_score >= 0.90
    assert "create_order" in rc.remediation_suggestion


def test_end_to_end_observability_pipeline():
    """Runs end-to-end audit correlating metrics, logs, and distributed traces."""
    store = CodeRegistryStore()

    # Register API endpoint node
    api_node = RegistryNode(
        id="api:POST:/api/v1/checkout",
        name="checkout_api",
        type=NodeType.API,
        location=NodeLocation(
            path="api/checkout.py",
            start_line=10,
            end_line=50,
            endpoint_method="POST",
            endpoint_route="/api/v1/checkout",
        ),
        signature="@app.post('/api/v1/checkout')",
        hash="apihash",
        status=NodeStatus.ACTIVE,
    )
    store.write_node(api_node, access_token="registry-write", source_agent="registry_keeper")

    agent = ObservabilityAgent(registry_store=store)

    telemetry_bundle = {
        "metrics": [
            {
                "metric_name": "http_request_duration_seconds",
                "service_name": "checkout-svc",
                "endpoint_route": "/api/v1/checkout",
                "current_value": 2.5,  # 2500ms
                "baseline_value": 0.2,
            }
        ],
        "logs": [
            """
2026-10-27 22:10:00 [ERROR] Checkout failed
Traceback (most recent call last):
  File "api/checkout.py", line 25, in checkout_handler
    db.execute_query(sql)
psycopg2.OperationalError: server closed the connection unexpectedly
"""
        ],
        "traces": [
            {
                "trace_id": "tr-999",
                "span_id": "sp-999",
                "name": "POST /api/v1/checkout",
                "duration_ms": 2500.0,
                "status": {"code": 2, "message": "Internal Server Error"},
                "attributes": {
                    "http.route": "/api/v1/checkout",
                    "http.status_code": 500,
                    "code.filepath": "api/checkout.py",
                    "code.lineno": 25,
                },
            }
        ],
    }

    inp = ObservabilityInput(
        opentelemetry_and_prometheus_data=telemetry_bundle,
        latency_threshold_ms=500.0,
        error_rate_threshold_pct=1.0,
    )

    out = agent.execute(inp)

    assert isinstance(out, ObservabilityOutput)
    assert out.health_status in ("DEGRADED", "CRITICAL")
    assert len(out.error_and_latency_anomalies) >= 1
    assert len(out.probable_root_cause_linked_to_nodes) >= 1

    primary_rc = out.probable_root_cause_linked_to_nodes[0]
    assert primary_rc.linked_node_id == "api:POST:/api/v1/checkout"
    assert primary_rc.file_path == "api/checkout.py"
    assert primary_rc.line_number == 25
    assert "OperationalError" in primary_rc.exception_class
    assert primary_rc.confidence_score >= 0.85
