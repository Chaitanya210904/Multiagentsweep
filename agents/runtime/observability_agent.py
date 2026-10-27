"""
Agent 11: Observability (Layer: Runtime).
Role: Logs, metrics and traces reader.
Description: Reads logs, metrics and traces and links problems back to code nodes.
Access: read-only
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agents.base import AgentMetadata, BaseAgent
from core.exceptions import UnauthorizedAccessError
from models.observability import (
    AnomalySeverity,
    AnomalyType,
    MetricAnomaly,
    ObservabilityInput,
    ObservabilityOutput,
    ProbableRootCause,
)
from models.registry import NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore
from tools.logs_search_tool import LogIncident, LogsSearchTool
from tools.prometheus_query_tool import PrometheusQueryTool
from tools.registry_lookup_tool import RegistryLookupTool
from tools.traces_search_tool import TraceIncident, TracesSearchTool


OBSERVABILITY_METADATA = AgentMetadata(
    id="observability",
    name="Observability",
    layer="runtime",
    role="Logs, metrics and traces reader",
    description="Reads logs, metrics and traces and links problems back to code nodes.",
    access="read-only",
    model_tier="medium",
    inputs=[
        "opentelemetry_and_prometheus_data",
        "service_map",
    ],
    outputs=[
        "error_and_latency_anomalies",
        "probable_root_cause_linked_to_nodes",
    ],
    tools=[
        "prometheus.query",
        "logs.search",
        "traces.search",
        "registry.lookup",
    ],
    trigger="timer and on alert",
    optional=False,
)


class ObservabilityAgent(BaseAgent):
    """
    Observability Agent: Telemetry Reader & Root Cause Linker (Layer: Runtime).
    - Metric Analysis: Prometheus error rates, latency percentiles, CPU saturation
    - Log Analysis: OpenTelemetry structured logs, stack traces, and exception extraction
    - Trace Analysis: Distributed spans, latency bottlenecks, and code coordinates
    - Graph Linkage: Connects operational failures directly to canonical Code Registry nodes
    - Strict read-only enforcement
    """

    def __init__(
        self,
        metadata: Optional[AgentMetadata] = None,
        registry_store: Optional[CodeRegistryStore] = None,
        repo_root: Optional[Union[str, Path]] = None,
        prometheus_url: Optional[str] = None,
        log_file: Optional[str] = None,
    ):
        meta = (metadata or OBSERVABILITY_METADATA).model_copy(deep=True)
        super().__init__(meta, log_file=log_file)
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.registry_store = registry_store or CodeRegistryStore()
        self.lookup_tool = RegistryLookupTool(store=self.registry_store)

        # Initialize operational telemetry analysis tools
        self.prom_tool = PrometheusQueryTool(prometheus_url=prometheus_url)
        self.logs_tool = LogsSearchTool()
        self.traces_tool = TracesSearchTool()

    def execute(self, inputs: ObservabilityInput) -> ObservabilityOutput:
        """
        Executes operational telemetry correlation across metrics, logs, and distributed traces.
        Enforces read-only access and links discovered failures to canonical registry code nodes.
        """
        self.require_access("read-only")

        if isinstance(inputs, dict):
            inputs = ObservabilityInput.model_validate(inputs)

        t0 = self.log_started({
            "latency_threshold_ms": inputs.latency_threshold_ms,
            "error_rate_threshold_pct": inputs.error_rate_threshold_pct,
            "has_service_map": bool(inputs.service_map),
        })

        try:
            # 1. Unpack telemetry bundles (metrics, logs, traces)
            raw_metrics, raw_logs, raw_traces = self._partition_telemetry_data(
                inputs.opentelemetry_and_prometheus_data
            )

            # 2. Tool 1: Prometheus Metric Anomaly Detection
            self.log_event(
                event="tool.prometheus",
                message="Evaluating Prometheus and OpenTelemetry metric timeseries",
                metrics_count=len(raw_metrics) if isinstance(raw_metrics, list) else 1,
            )
            metric_anomalies = self.prom_tool.query(
                metrics_data=raw_metrics,
                error_rate_threshold_pct=inputs.error_rate_threshold_pct,
                latency_threshold_ms=inputs.latency_threshold_ms,
            )

            # 3. Tool 2: Logs Search & Stack Trace Extraction
            self.log_event(
                event="tool.logs",
                message="Searching logs for runtime exceptions and stack traces",
            )
            log_incidents = self.logs_tool.search(logs_data=raw_logs)

            # 4. Tool 3: Distributed Traces Search & Bottleneck Detection
            self.log_event(
                event="tool.traces",
                message="Searching distributed trace spans for errors and latency bottlenecks",
            )
            trace_incidents = self.traces_tool.search(
                traces_data=raw_traces,
                latency_threshold_ms=inputs.latency_threshold_ms,
            )

            # 5. Tool 4: Synthesize Root Causes & Link to Code Registry Nodes
            probable_root_causes = self._synthesize_root_causes(
                log_incidents=log_incidents,
                trace_incidents=trace_incidents,
                metric_anomalies=metric_anomalies,
            )

            # 6. Deduplicate & Sort Root Causes by confidence and severity
            severity_order = {
                AnomalySeverity.CRITICAL: 0,
                AnomalySeverity.HIGH: 1,
                AnomalySeverity.MEDIUM: 2,
                AnomalySeverity.LOW: 3,
                AnomalySeverity.INFO: 4,
            }
            probable_root_causes.sort(
                key=lambda rc: (severity_order.get(rc.severity, 5), -rc.confidence_score)
            )

            # Collect affected services
            affected_services: Set[str] = set()
            for anom in metric_anomalies:
                if anom.service_name:
                    affected_services.add(anom.service_name)
            for inc in log_incidents:
                if inc.service_name:
                    affected_services.add(inc.service_name)
            for tr in trace_incidents:
                if tr.service_name:
                    affected_services.add(tr.service_name)

            # Overall health assessment
            has_crit = any(rc.severity == AnomalySeverity.CRITICAL for rc in probable_root_causes) or any(
                m.severity == AnomalySeverity.CRITICAL for m in metric_anomalies
            )
            has_high = any(rc.severity == AnomalySeverity.HIGH for rc in probable_root_causes) or any(
                m.severity == AnomalySeverity.HIGH for m in metric_anomalies
            )

            if has_crit:
                health_status = "CRITICAL"
            elif has_high:
                health_status = "DEGRADED"
            else:
                health_status = "HEALTHY"

            stats = {
                "metric_anomalies_count": len(metric_anomalies),
                "log_incidents_count": len(log_incidents),
                "trace_incidents_count": len(trace_incidents),
                "root_causes_count": len(probable_root_causes),
                "linked_to_nodes_count": sum(1 for rc in probable_root_causes if rc.linked_node_id),
            }

            self.log_completed(
                start_time=t0,
                outputs_summary={
                    "health_status": health_status,
                    "anomalies_count": len(metric_anomalies),
                    "root_causes_count": len(probable_root_causes),
                    "affected_services": list(affected_services),
                },
            )

            return ObservabilityOutput(
                error_and_latency_anomalies=metric_anomalies,
                probable_root_cause_linked_to_nodes=probable_root_causes,
                total_spans_analyzed=len(trace_incidents),
                total_log_entries_analyzed=len(log_incidents),
                total_metrics_evaluated=len(metric_anomalies),
                affected_services=sorted(list(affected_services)),
                health_status=health_status,
                stats=stats,
            )

        except Exception as e:
            self.log_failed(t0, e)
            raise

    # --------------------------------------------------------------------------
    # Subroutines: Telemetry Ingest & Partitioning
    # --------------------------------------------------------------------------

    def _partition_telemetry_data(
        self, data: Union[str, Path, Dict[str, Any], List[Any]]
    ) -> Tuple[Any, Any, Any]:
        """Splits incoming telemetry payload into metrics, logs, and traces."""
        metrics_payload = []
        logs_payload = []
        traces_payload = []

        if isinstance(data, (str, Path)):
            p = Path(data)
            if p.is_file():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    return self._partition_telemetry_data(loaded)
                except Exception:
                    # Treat as raw log text file
                    return ([], [str(p)], [])
            else:
                try:
                    loaded = json.loads(str(data))
                    return self._partition_telemetry_data(loaded)
                except Exception:
                    return ([], [str(data)], [])

        elif isinstance(data, dict):
            # Check for explicit root keys
            if "metrics" in data:
                metrics_payload = data["metrics"]
            if "logs" in data:
                logs_payload = data["logs"]
            if "traces" in data:
                traces_payload = data["traces"]

            # OpenTelemetry OTLP standard wrappers
            if "resourceMetrics" in data:
                metrics_payload = data["resourceMetrics"]
            if "resourceLogs" in data:
                logs_payload = data["resourceLogs"]
            if "resourceSpans" in data:
                traces_payload = data["resourceSpans"]

            # If no root keys matched, inspect dictionary contents
            if not metrics_payload and not logs_payload and not traces_payload:
                if any(k in data for k in ("spans", "span_id", "trace_id", "traceId")):
                    traces_payload = data
                elif any(k in data for k in ("records", "exc_info", "stacktrace")):
                    logs_payload = data
                elif any(k in data for k in ("metric_name", "value", "current_value")):
                    metrics_payload = data
                else:
                    # Pass as general feed to all
                    metrics_payload = data
                    logs_payload = data
                    traces_payload = data

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (str, Path)) and Path(item).is_file():
                    p = Path(item)
                    fname = p.name.lower()
                    if "metric" in fname or "prom" in fname:
                        metrics_payload.append(str(p))
                    elif "log" in fname:
                        logs_payload.append(str(p))
                    elif "trace" in fname:
                        traces_payload.append(str(p))
                    else:
                        logs_payload.append(str(p))
                elif isinstance(item, dict):
                    if any(k in item for k in ("spans", "span_id", "trace_id")):
                        traces_payload.append(item)
                    elif any(k in item for k in ("message", "exc_info", "stacktrace")):
                        logs_payload.append(item)
                    else:
                        metrics_payload.append(item)
                else:
                    logs_payload.append(item)

        return metrics_payload, logs_payload, traces_payload

    # --------------------------------------------------------------------------
    # Subroutines: Root Cause Synthesis & Code Node Linkage
    # --------------------------------------------------------------------------

    def _synthesize_root_causes(
        self,
        log_incidents: List[LogIncident],
        trace_incidents: List[TraceIncident],
        metric_anomalies: List[MetricAnomaly],
    ) -> List[ProbableRootCause]:
        """
        Cross-correlates log stack traces, failed trace spans, and metric spikes,
        linking each failure back to exact canonical nodes in the Code Registry.
        """
        root_causes: List[ProbableRootCause] = []
        seen_keys: Set[str] = set()

        # 1. Process Log Incidents (High-fidelity source code line attribution)
        for idx, inc in enumerate(log_incidents, start=1):
            linked_node: Optional[RegistryNode] = None
            confidence = 0.50
            rel_path = None

            if inc.file_path:
                rel_path = self._relativize_path(inc.file_path)
                linked_node, confidence = self._match_code_node(
                    file_path=rel_path,
                    line_number=inc.line_number,
                    function_name=inc.function_name,
                )

            dedup_key = f"{rel_path or inc.service_name}:{inc.line_number}:{inc.exception_class}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            sev = (
                AnomalySeverity.CRITICAL
                if inc.severity in ("CRITICAL", "FATAL")
                or "ConnectionRefused" in inc.exception_class
                or "OperationalError" in inc.exception_class
                else AnomalySeverity.HIGH
            )

            title = (
                f"Uncaught {inc.exception_class} in {linked_node.name if linked_node else (inc.function_name or 'runtime')}"
            )

            evidence = [
                f"Exception: {inc.exception_class}: {inc.error_message}",
                f"Stack location: {rel_path or inc.file_path}:{inc.line_number or 1} (in {inc.function_name or 'top-level'})",
            ]
            if inc.trace_id:
                evidence.append(f"Trace Correlation ID: {inc.trace_id}")

            remediation = self._formulate_remediation(inc.exception_class, inc.error_message, linked_node)

            root_causes.append(
                ProbableRootCause(
                    cause_id=f"RC-LOG-{idx:03d}",
                    title=title,
                    severity=sev,
                    linked_node_id=linked_node.id if linked_node else None,
                    file_path=rel_path or inc.file_path,
                    line_number=inc.line_number,
                    exception_class=inc.exception_class,
                    error_message=inc.error_message,
                    confidence_score=round(confidence, 2),
                    trace_id=inc.trace_id,
                    span_id=inc.span_id,
                    evidence=evidence,
                    remediation_suggestion=remediation,
                )
            )

        # 2. Process Trace Incidents (Distributed service & bottleneck linkage)
        for idx, tr in enumerate(trace_incidents, start=1):
            # Check if this trace span corresponds to an already identified root cause
            matched_existing = next((rc for rc in root_causes if rc.trace_id and rc.trace_id == tr.trace_id), None)
            if matched_existing:
                matched_existing.evidence.append(
                    f"Span '{tr.name}' failed with status {tr.status_code} ({tr.duration_ms:.1f}ms)"
                )
                continue

            rel_path = self._relativize_path(tr.file_path) if tr.file_path else None
            linked_node = None
            confidence = 0.60

            if rel_path:
                linked_node, confidence = self._match_code_node(
                    file_path=rel_path,
                    line_number=tr.line_number,
                    function_name=tr.function_name,
                )
            elif tr.http_route:
                # Search registry for matching API Endpoint node
                linked_node = self._match_api_node(tr.http_route)
                if linked_node:
                    confidence = 0.75
                    rel_path = linked_node.location.path

            dedup_key = f"{rel_path or tr.http_route or tr.name}:{tr.line_number}:{tr.status_code}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            is_err = tr.status_code == "ERROR"
            sev = AnomalySeverity.HIGH if is_err else AnomalySeverity.MEDIUM
            title = (
                f"Failed trace execution in {linked_node.name if linked_node else tr.name}"
                if is_err
                else f"Latency bottleneck ({tr.duration_ms:.1f}ms) in {linked_node.name if linked_node else tr.name}"
            )

            evidence = [
                f"Span name: '{tr.name}' (Service: {tr.service_name or 'unknown'})",
                f"Duration: {tr.duration_ms:.1f}ms (Status: {tr.status_code})",
            ]
            if tr.db_statement:
                evidence.append(f"Executed SQL: {tr.db_statement}")
            if tr.status_message:
                evidence.append(f"Status message: {tr.status_message}")

            root_causes.append(
                ProbableRootCause(
                    cause_id=f"RC-TRC-{idx:03d}",
                    title=title,
                    severity=sev,
                    linked_node_id=linked_node.id if linked_node else None,
                    file_path=rel_path or (linked_node.location.path if linked_node else None),
                    line_number=tr.line_number or (linked_node.location.start_line if linked_node else None),
                    exception_class=tr.exception_class or ("LatencyBottleneck" if tr.is_bottleneck else "SpanError"),
                    error_message=tr.status_message or tr.exception_message or f"Execution took {tr.duration_ms:.1f}ms",
                    confidence_score=round(confidence, 2),
                    trace_id=tr.trace_id,
                    span_id=tr.span_id,
                    evidence=evidence,
                    remediation_suggestion=(
                        "Inspect slow queries, add missing database indexes, or introduce caching."
                        if tr.db_statement
                        else "Review function implementation for blocking synchronous I/O or downstream timeout issues."
                    ),
                )
            )

        # 3. Correlate Metric Anomalies with API nodes
        for idx, anom in enumerate(metric_anomalies, start=1):
            if anom.endpoint_route:
                api_node = self._match_api_node(anom.endpoint_route)
                # Check if already covered
                if api_node and not any(rc.linked_node_id == api_node.id for rc in root_causes):
                    root_causes.append(
                        ProbableRootCause(
                            cause_id=f"RC-MET-{idx:03d}",
                            title=f"{anom.anomaly_type.value.replace('_', ' ').title()} on endpoint {anom.endpoint_route}",
                            severity=anom.severity,
                            linked_node_id=api_node.id,
                            file_path=api_node.location.path,
                            line_number=api_node.location.start_line,
                            exception_class=anom.anomaly_type.value,
                            error_message=anom.description,
                            confidence_score=0.70,
                            evidence=[
                                f"Observed metric: {anom.metric_name} = {anom.current_value} (baseline: {anom.baseline_value})",
                                f"Deviation factor: {anom.deviation_factor}x",
                            ],
                            remediation_suggestion="Inspect recent deployments affecting this endpoint and verify downstream dependencies.",
                        )
                    )

        return root_causes

    def _match_code_node(
        self, file_path: str, line_number: Optional[int], function_name: Optional[str]
    ) -> Tuple[Optional[RegistryNode], float]:
        """Looks up canonical RegistryNode enclosing the error file and line number."""
        nodes = self.lookup_tool.get_by_path(file_path)
        if not nodes:
            # Try fuzzy match on filename
            fname = Path(file_path).name
            matching = [n for n in self.registry_store.list_all() if n.location.path.endswith(fname)]
            if matching:
                nodes = matching

        if not nodes:
            return None, 0.40

        # 1. Exact match: line number falls inside function/class/api start_line and end_line
        if line_number:
            for n in nodes:
                if n.type in (NodeType.FUNCTION, NodeType.CLASS, NodeType.API):
                    if (
                        n.location.start_line is not None
                        and n.location.start_line <= line_number <= (n.location.end_line or line_number)
                    ):
                        return n, 0.95

        # 2. Match by function or class name
        if function_name:
            for n in nodes:
                if n.name.lower() == function_name.lower():
                    return n, 0.85

        # 3. Match file-level node
        file_node = next((n for n in nodes if n.type == NodeType.FILE), nodes[0])
        return file_node, 0.70

    def _match_api_node(self, route: str) -> Optional[RegistryNode]:
        """Finds API node corresponding to an HTTP endpoint path."""
        clean_route = route.split("?")[0].rstrip("/")
        for n in self.registry_store.list_all():
            if n.type == NodeType.API:
                if n.location.endpoint_route and n.location.endpoint_route.rstrip("/") == clean_route:
                    return n
                if clean_route in n.id:
                    return n
        return None

    def _relativize_path(self, path_str: str) -> str:
        """Converts absolute file paths to repository-relative paths."""
        try:
            p = Path(path_str)
            if p.is_relative_to(self.repo_root):
                return str(p.relative_to(self.repo_root))
            return str(p)
        except Exception:
            return str(path_str)

    @staticmethod
    def _formulate_remediation(
        exception_class: str, error_message: str, node: Optional[RegistryNode]
    ) -> str:
        """Formulates targeted remediation guidance based on the exception type."""
        exc_lower = exception_class.lower()
        node_name = node.name if node else "handler"

        if "connectionrefused" in exc_lower or "operationalerror" in exc_lower:
            return f"Verify database connection pool parameters, host networking, and retry policies in `{node_name}`."
        if "keyerror" in exc_lower:
            return f"Check dictionary payload validation in `{node_name}`; use `.get()` with defaults or Pydantic validation."
        if "zerodivision" in exc_lower:
            return f"Add denominator guard condition (`if denominator != 0:`) inside `{node_name}`."
        if "timeout" in exc_lower:
            return f"Tune HTTP/RPC client timeout settings and wrap external requests with circuit breakers in `{node_name}`."
        if "nullpointer" in exc_lower or "attributeerror" in exc_lower:
            return f"Add null/None check before property dereference in `{node_name}`."
        return f"Review exception handling and wrap critical section in `{node_name}` with error recovery logic."


# Backward-compatible alias
Observability = ObservabilityAgent
