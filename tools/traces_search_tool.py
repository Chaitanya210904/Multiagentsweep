"""
Tool: traces.search
Searches and analyzes distributed trace spans from OpenTelemetry, Jaeger, and Zipkin.
Identifies:
- Errored spans with exception events and HTTP 5xx codes
- Latency bottleneck spans exceeding execution thresholds
- Exact code file paths, line numbers, and function coordinates
- Database query statements and HTTP endpoints
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class TraceIncident(BaseModel):
    """Structured representation of a failed or bottlenecked distributed trace span."""
    trace_id: str = Field(description="OpenTelemetry trace ID")
    span_id: str = Field(description="OpenTelemetry span ID")
    parent_span_id: Optional[str] = Field(default=None, description="Parent span ID")
    name: str = Field(description="Span operation name (e.g. 'HTTP GET /checkout', 'SELECT users')")
    service_name: Optional[str] = Field(default=None, description="Service generating the span")
    duration_ms: float = Field(description="Span execution duration in milliseconds")
    status_code: str = Field(description="Span status code: 'ERROR', 'OK', or 'UNSET'")
    status_message: Optional[str] = Field(default=None, description="Error message from span status")
    file_path: Optional[str] = Field(default=None, description="Source code file path (code.filepath)")
    line_number: Optional[int] = Field(default=None, description="Source line number (code.lineno)")
    function_name: Optional[str] = Field(default=None, description="Function or method name (code.function)")
    http_route: Optional[str] = Field(default=None, description="HTTP route (http.route or http.target)")
    http_status_code: Optional[int] = Field(default=None, description="HTTP response status code")
    db_statement: Optional[str] = Field(default=None, description="Database query executed in span")
    exception_class: Optional[str] = Field(default=None, description="Exception type from span events")
    exception_message: Optional[str] = Field(default=None, description="Exception message from span events")
    is_bottleneck: bool = Field(default=False, description="Whether span is a critical latency bottleneck")


class TracesSearchTool:
    """Tool: traces.search - Distributed trace span searching and bottleneck detector."""

    name = "traces.search"
    description = (
        "Searches OpenTelemetry and distributed trace spans to identify failed executions, "
        "latency bottlenecks, and code coordinates (code.filepath, code.lineno)."
    )

    def search(
        self,
        traces_data: Union[str, Path, Dict[str, Any], List[Any]],
        query: Optional[str] = None,
        latency_threshold_ms: float = 500.0,
    ) -> List[TraceIncident]:
        """
        Parses OpenTelemetry OTLP or simplified trace collections and extracts
        errored or high-latency bottleneck spans.
        """
        raw_spans = self._extract_raw_spans(traces_data)
        incidents: List[TraceIncident] = []

        for span in raw_spans:
            inc = self._evaluate_span(span, query, latency_threshold_ms)
            if inc:
                incidents.append(inc)

        # Sort incidents by duration (slowest first) and errors
        incidents.sort(key=lambda s: (s.status_code == "ERROR", s.duration_ms), reverse=True)
        return incidents

    def _extract_raw_spans(self, traces_data: Union[str, Path, Dict[str, Any], List[Any]]) -> List[Dict[str, Any]]:
        """Extracts individual span dictionaries from various trace payload formats."""
        if isinstance(traces_data, (str, Path)) and Path(traces_data).is_file():
            try:
                content = json.loads(Path(traces_data).read_text(encoding="utf-8"))
                return self._extract_raw_spans(content)
            except Exception:
                return []

        if isinstance(traces_data, str):
            try:
                content = json.loads(traces_data)
                return self._extract_raw_spans(content)
            except Exception:
                return []

        if isinstance(traces_data, list):
            spans: List[Dict[str, Any]] = []
            for item in traces_data:
                spans.extend(self._extract_raw_spans(item))
            return spans

        if isinstance(traces_data, dict):
            # 1. OpenTelemetry OTLP format: resourceSpans -> scopeSpans -> spans
            if "resourceSpans" in traces_data:
                spans = []
                for rs in traces_data.get("resourceSpans", []):
                    service_name = None
                    for attr in rs.get("resource", {}).get("attributes", []):
                        if attr.get("key") == "service.name":
                            service_name = attr.get("value", {}).get("stringValue")
                    for ss in rs.get("scopeSpans", []):
                        for sp in ss.get("spans", []):
                            sp_copy = dict(sp)
                            if service_name and "service_name" not in sp_copy:
                                sp_copy["service_name"] = service_name
                            spans.append(sp_copy)
                return spans

            # 2. Simplified dictionary with 'spans' list
            if "spans" in traces_data and isinstance(traces_data["spans"], list):
                return traces_data["spans"]

            # 3. Single span dictionary
            if "span_id" in traces_data or "spanId" in traces_data or "name" in traces_data:
                return [traces_data]

        return []

    def _evaluate_span(
        self, span: Dict[str, Any], query: Optional[str], latency_threshold_ms: float
    ) -> Optional[TraceIncident]:
        """Evaluates a single span to determine if it represents an error or latency anomaly."""
        span_id = str(span.get("span_id") or span.get("spanId") or "span_unknown")
        trace_id = str(span.get("trace_id") or span.get("traceId") or "trace_unknown")
        parent_id = span.get("parent_span_id") or span.get("parentSpanId")
        name = str(span.get("name") or "operation")

        # Duration calculation
        duration_ms = 0.0
        if "duration_ms" in span:
            duration_ms = float(span["duration_ms"])
        elif "startTimeUnixNano" in span and "endTimeUnixNano" in span:
            start_nano = int(span["startTimeUnixNano"])
            end_nano = int(span["endTimeUnixNano"])
            duration_ms = (end_nano - start_nano) / 1_000_000.0
        elif "start_time" in span and "end_time" in span:
            duration_ms = (float(span["end_time"]) - float(span["start_time"])) * 1000.0

        # Status inspection
        raw_status = span.get("status", {})
        status_code = "OK"
        status_msg = None

        if isinstance(raw_status, dict):
            code_val = raw_status.get("code")
            if code_val in (2, "2", "ERROR", "STATUS_CODE_ERROR"):
                status_code = "ERROR"
            status_msg = raw_status.get("message") or raw_status.get("description")
        elif str(raw_status).upper() in ("ERROR", "2"):
            status_code = "ERROR"

        # Attributes flattening
        attrs: Dict[str, Any] = {}
        raw_attrs = span.get("attributes") or {}
        if isinstance(raw_attrs, list):
            # OTLP attributes: [{'key': '...', 'value': {'stringValue': '...'}}]
            for a in raw_attrs:
                k = a.get("key")
                v_dict = a.get("value", {})
                v = (
                    v_dict.get("stringValue")
                    or v_dict.get("intValue")
                    or v_dict.get("doubleValue")
                    or v_dict.get("boolValue")
                )
                if k and v is not None:
                    attrs[k] = v
        elif isinstance(raw_attrs, dict):
            attrs = raw_attrs

        # Extract HTTP & DB attributes
        http_status = attrs.get("http.status_code") or attrs.get("http.response_status_code")
        if http_status and int(http_status) >= 500:
            status_code = "ERROR"
            if not status_msg:
                status_msg = f"HTTP {http_status} Internal Server Error"

        http_route = attrs.get("http.route") or attrs.get("http.target") or attrs.get("url.path")
        db_stmt = attrs.get("db.statement") or attrs.get("db.query")
        service_name = span.get("service_name") or attrs.get("service.name")

        # Code location attributes
        file_path = attrs.get("code.filepath") or attrs.get("code.file")
        line_num = int(attrs.get("code.lineno") or attrs.get("code.line", 1)) if file_path else None
        func_name = attrs.get("code.function")

        # Exception events
        exc_class = None
        exc_message = None
        events = span.get("events", [])
        for ev in events:
            if ev.get("name") == "exception":
                ev_attrs = ev.get("attributes", {})
                if isinstance(ev_attrs, list):
                    for a in ev_attrs:
                        if a.get("key") == "exception.type":
                            exc_class = a.get("value", {}).get("stringValue")
                        elif a.get("key") == "exception.message":
                            exc_message = a.get("value", {}).get("stringValue")
                elif isinstance(ev_attrs, dict):
                    exc_class = ev_attrs.get("exception.type")
                    exc_message = ev_attrs.get("exception.message")
                status_code = "ERROR"

        is_bottleneck = duration_ms >= latency_threshold_ms

        # Keep span if it failed OR represents a latency bottleneck
        if status_code != "ERROR" and not is_bottleneck:
            return None

        if query:
            full_text = f"{name} {file_path} {func_name} {status_msg} {db_stmt}".lower()
            if query.lower() not in full_text:
                return None

        return TraceIncident(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_id,
            name=name,
            service_name=service_name,
            duration_ms=round(duration_ms, 2),
            status_code=status_code,
            status_message=status_msg,
            file_path=file_path,
            line_number=line_num,
            function_name=func_name,
            http_route=http_route,
            http_status_code=int(http_status) if http_status else None,
            db_statement=db_stmt,
            exception_class=exc_class,
            exception_message=exc_message,
            is_bottleneck=is_bottleneck,
        )
