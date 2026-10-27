"""
Data models for the Observability Agent (Layer: Runtime).
Defines error and latency anomalies, telemetry ingest structures (Prometheus metrics,
OpenTelemetry logs and distributed traces), and probable root-cause linking to code nodes.
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class AnomalyType(str, Enum):
    """Categorical classification of operational performance anomalies."""
    ERROR_RATE_SPIKE = "error_rate_spike"
    LATENCY_SPIKE = "latency_spike"
    CPU_SATURATION = "cpu_saturation"
    MEMORY_LEAK_SPIKE = "memory_leak_spike"
    DATABASE_SLOWDOWN = "database_slowdown"
    DEPENDENCY_OUTAGE = "dependency_outage"


class AnomalySeverity(str, Enum):
    """Severity tier for detected runtime problems."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MetricAnomaly(BaseModel):
    """
    Anomalous operational metric detected from Prometheus or OpenTelemetry feeds,
    such as elevated 5xx error rates, p99 latency spikes, or memory pressure.
    """
    id: str = Field(description="Unique identifier for the anomaly, e.g. ANOM-001")
    metric_name: str = Field(description="Prometheus metric name, e.g. 'http_requests_total', 'http_request_duration_seconds'")
    anomaly_type: AnomalyType = Field(description="Type of runtime anomaly")
    severity: AnomalySeverity = Field(description="Impact severity tier")
    service_name: Optional[str] = Field(default=None, description="Name of the affected service or component")
    endpoint_route: Optional[str] = Field(default=None, description="HTTP route or RPC method impacted (e.g. '/api/v1/checkout')")
    current_value: float = Field(description="Current observed metric value")
    baseline_value: float = Field(description="Expected normal baseline metric value")
    deviation_factor: float = Field(description="Ratio of observed value over baseline (e.g. 4.2x)")
    description: str = Field(description="Human-readable explanation of the metric breach")
    timestamp: Optional[str] = Field(default=None, description="ISO timestamp of anomaly occurrence")


class ProbableRootCause(BaseModel):
    """
    Synthesized root cause connecting runtime exceptions, slow traces,
    or metric spikes directly to a specific canonical Code Registry node.
    """
    cause_id: str = Field(description="Unique root cause identifier, e.g. RC-001")
    title: str = Field(description="Concise description of the failure condition")
    severity: AnomalySeverity = Field(description="Root cause severity level")
    linked_node_id: Optional[str] = Field(
        default=None,
        description="Canonical ID of the exact RegistryNode responsible (e.g. 'func:services/payment.py:process_charge')",
    )
    file_path: Optional[str] = Field(default=None, description="Source code file where failure originated")
    line_number: Optional[int] = Field(default=None, description="1-indexed source line number from stack trace or trace span")
    exception_class: Optional[str] = Field(default=None, description="Exception type (e.g. 'ConnectionRefusedError', 'KeyError')")
    error_message: Optional[str] = Field(default=None, description="Primary error message extracted from logs")
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Algorithmic confidence (0.0 to 1.0) linking this code node to the runtime failure",
    )
    trace_id: Optional[str] = Field(default=None, description="Associated OpenTelemetry trace ID if available")
    span_id: Optional[str] = Field(default=None, description="Failing or slowest OpenTelemetry span ID")
    evidence: List[str] = Field(
        default_factory=list,
        description="Corroborating telemetry evidence (log snippets, stack frames, slow trace spans)",
    )
    remediation_suggestion: str = Field(description="Actionable guidance on how to fix or mitigate the failure")


class ObservabilityInput(BaseModel):
    """Input payload accepted by the Observability Agent."""
    opentelemetry_and_prometheus_data: Union[str, Path, Dict[str, Any], List[Union[str, Path, Dict[str, Any]]]] = Field(
        description="Telemetry bundle containing Prometheus metrics, OpenTelemetry structured logs, and distributed traces, or file path/string",
    )
    service_map: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional service topology map linking services, endpoints, and database tables",
    )
    latency_threshold_ms: float = Field(
        default=500.0,
        ge=10.0,
        description="Threshold in milliseconds for span/request latency spike detection (default: 500ms)",
    )
    error_rate_threshold_pct: float = Field(
        default=1.0,
        ge=0.0,
        le=100.0,
        description="Threshold percentage for error rate anomaly detection (default: 1.0%)",
    )


class ObservabilityOutput(BaseModel):
    """Output payload produced by the Observability Agent."""
    error_and_latency_anomalies: List[MetricAnomaly] = Field(
        default_factory=list,
        description="Detected metric spikes, latency regressions, and operational deviations",
    )
    probable_root_cause_linked_to_nodes: List[ProbableRootCause] = Field(
        default_factory=list,
        description="Pinpointed root causes connected to exact code registry nodes and line numbers",
    )
    total_spans_analyzed: int = Field(default=0, ge=0, description="Count of OpenTelemetry trace spans evaluated")
    total_log_entries_analyzed: int = Field(default=0, ge=0, description="Count of log records ingested and parsed")
    total_metrics_evaluated: int = Field(default=0, ge=0, description="Count of metric timeseries points evaluated")
    affected_services: List[str] = Field(default_factory=list, description="List of unique services experiencing issues")
    health_status: str = Field(description="Overall system runtime status: 'HEALTHY', 'DEGRADED', or 'CRITICAL'")
    stats: Dict[str, Any] = Field(
        default_factory=dict,
        description="Statistical summary of anomalies by type, severity, and root causes",
    )
