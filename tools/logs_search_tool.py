"""
Tool: logs.search
Searches and parses application log streams, OpenTelemetry structured log records,
and plain text log files.
Extracts:
- Error and fatal log entries
- Stack trace frames with exact file paths, line numbers, and function names
- Exception class names and error descriptions
- Distributed trace IDs and span IDs for cross-telemetry correlation
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field


class LogIncident(BaseModel):
    """Structured representation of an operational log error or exception event."""
    file_path: Optional[str] = Field(default=None, description="Source code file extracted from stack trace or attributes")
    line_number: Optional[int] = Field(default=None, description="1-indexed line number where exception was raised")
    function_name: Optional[str] = Field(default=None, description="Name of the function or method executing when error occurred")
    exception_class: Optional[str] = Field(default=None, description="Exception class (e.g. 'OperationalError', 'KeyError')")
    error_message: str = Field(description="Error message or exception text")
    severity: str = Field(default="ERROR", description="Log level: ERROR, CRITICAL, or FATAL")
    trace_id: Optional[str] = Field(default=None, description="OpenTelemetry trace ID if present")
    span_id: Optional[str] = Field(default=None, description="OpenTelemetry span ID if present")
    service_name: Optional[str] = Field(default=None, description="Service or logger name")
    timestamp: Optional[str] = Field(default=None, description="Log timestamp")
    raw_log: str = Field(description="Original unparsed log message or stack trace snippet")


class LogsSearchTool:
    """Tool: logs.search - Log parsing and stack trace extraction engine."""

    name = "logs.search"
    description = (
        "Searches log records and extracts error events, stack traces, "
        "file paths, line numbers, exception classes, and correlation trace IDs."
    )

    # Regex patterns for multi-language stack trace extraction
    # Python: File "/path/to/file.py", line 42, in my_func
    PYTHON_FRAME = re.compile(r'File\s+["\']([^"\']+)["\'],\s+line\s+(\d+)(?:,\s+in\s+([a-zA-Z0-9_<>\.]+))?')
    # JavaScript: at Object.myFunc (/path/to/file.js:42:15) or at /path/to/file.js:42:15
    JS_FRAME = re.compile(r'at\s+(?:([a-zA-Z0-9_<>\.\s]+)\s+\()?([^:()\s]+):(\d+):(\d+)\)?')
    # Java: at com.pkg.MyClass.myMethod(MyFile.java:42)
    JAVA_FRAME = re.compile(r'at\s+([a-zA-Z0-9_\.]+)\.([a-zA-Z0-9_<>\$]+)\(([^:]+):(\d+)\)')
    # Generic Exception Line: e.g. ZeroDivisionError: division by zero or java.lang.NullPointerException: ...
    EXCEPTION_LINE = re.compile(r'\b([A-Za-z0-9_\.]*(?:Exception|Error|Panic|Fault|Failure))\b:\s*(.*)')

    ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL", "SEVERE", "PANIC"}

    def search(
        self,
        logs_data: Union[str, Path, Dict[str, Any], List[Any]],
        query: Optional[str] = None,
        service_filter: Optional[str] = None,
    ) -> List[LogIncident]:
        """
        Parses log data (strings, dictionaries, OpenTelemetry JSON, or log file paths)
        and extracts structured error incidents.
        """
        incidents: List[LogIncident] = []

        # 1. Handle file path
        if isinstance(logs_data, (str, Path)) and Path(logs_data).is_file():
            try:
                content = Path(logs_data).read_text(encoding="utf-8", errors="replace")
                return self._parse_text_logs(content, query, service_filter)
            except Exception:
                return []

        # 2. Handle string block
        if isinstance(logs_data, str):
            return self._parse_text_logs(logs_data, query, service_filter)

        # 3. Handle dictionary (OpenTelemetry or structured JSON)
        if isinstance(logs_data, dict):
            # Check if it has a list of records under 'logs', 'records', 'items'
            records = logs_data.get("logs") or logs_data.get("records") or logs_data.get("items") or [logs_data]
            for r in records:
                inc = self._parse_structured_record(r, query, service_filter)
                if inc:
                    incidents.append(inc)
            return incidents

        # 4. Handle list of records or strings
        if isinstance(logs_data, list):
            for item in logs_data:
                if isinstance(item, dict):
                    inc = self._parse_structured_record(item, query, service_filter)
                    if inc:
                        incidents.append(inc)
                elif isinstance(item, str):
                    incidents.extend(self._parse_text_logs(item, query, service_filter))

        return incidents

    def _parse_structured_record(
        self, record: Dict[str, Any], query: Optional[str], service_filter: Optional[str]
    ) -> Optional[LogIncident]:
        """Parses a structured JSON or OpenTelemetry log record."""
        # Check level
        level = (
            record.get("level")
            or record.get("severity")
            or record.get("SeverityText")
            or record.get("log_level")
            or "INFO"
        ).upper()

        if level not in self.ERROR_LEVELS and "error" not in level.lower():
            # Only process errors/warnings
            return None

        # Check message body
        msg = str(record.get("message") or record.get("msg") or record.get("Body") or "")
        exc = str(record.get("exc_info") or record.get("exception") or record.get("stacktrace") or "")
        full_text = f"{msg}\n{exc}".strip()

        if query and query.lower() not in full_text.lower():
            return None

        # Extract attributes & correlation IDs
        attrs = record.get("attributes") or record.get("Attributes") or {}
        trace_id = str(record.get("trace_id") or record.get("TraceId") or attrs.get("trace_id") or "") or None
        span_id = str(record.get("span_id") or record.get("SpanId") or attrs.get("span_id") or "") or None
        service = str(record.get("service") or attrs.get("service.name") or "") or None
        timestamp = str(record.get("timestamp") or record.get("time") or "") or None

        if service_filter and service and service_filter.lower() not in service.lower():
            return None

        # Parse stack trace frames from full text
        file_path, line_no, func_name = self._extract_stack_frame(full_text)
        if not file_path and "code.filepath" in attrs:
            file_path = str(attrs["code.filepath"])
            line_no = int(attrs.get("code.lineno", 1))
            func_name = str(attrs.get("code.function", ""))

        # Extract exception class
        exc_class, exc_msg = self._extract_exception(full_text)

        return LogIncident(
            file_path=file_path,
            line_number=line_no,
            function_name=func_name,
            exception_class=exc_class or "RuntimeError",
            error_message=exc_msg or msg or "Unspecified runtime exception",
            severity=level,
            trace_id=trace_id,
            span_id=span_id,
            service_name=service,
            timestamp=timestamp,
            raw_log=full_text,
        )

    def _parse_text_logs(
        self, text: str, query: Optional[str], service_filter: Optional[str]
    ) -> List[LogIncident]:
        """Parses multi-line text logs or console stack traces."""
        incidents: List[LogIncident] = []

        # Try to parse line-delimited JSON first (NDJSON)
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    data = json.loads(s)
                    inc = self._parse_structured_record(data, query, service_filter)
                    if inc:
                        incidents.append(inc)
                except Exception:
                    pass

        if incidents:
            return incidents

        # Otherwise, treat as raw text with possible stack trace blocks
        # Split on standard timestamp or log-level boundaries
        blocks = re.split(r'\n(?=\d{4}-\d{2}-\d{2}|\[\d{2}:\d{2}:\d{2}\]|(?:INFO|ERROR|WARN|CRITICAL)\s)', text)
        if len(blocks) <= 1:
            # Fall back to splitting on Traceback blocks
            blocks = re.split(r'\n(?=Traceback \(most recent call last\):)', text)

        for b in blocks:
            b_strip = b.strip()
            if not b_strip:
                continue

            is_error = (
                any(lvl in b_strip.upper() for lvl in self.ERROR_LEVELS)
                or "Traceback (most recent call last):" in b_strip
                or "Exception:" in b_strip
                or "Error:" in b_strip
            )

            if not is_error:
                continue

            if query and query.lower() not in b_strip.lower():
                continue

            file_path, line_no, func_name = self._extract_stack_frame(b_strip)
            exc_class, exc_msg = self._extract_exception(b_strip)

            # Extract trace ID if formatted in log line
            trace_match = re.search(r'\b(?:trace_id|traceId)=([a-f0-9]{16,32})\b', b_strip)
            trace_id = trace_match.group(1) if trace_match else None

            incidents.append(
                LogIncident(
                    file_path=file_path,
                    line_number=line_no,
                    function_name=func_name,
                    exception_class=exc_class or "RuntimeError",
                    error_message=exc_msg or b_strip.splitlines()[0],
                    severity="ERROR",
                    trace_id=trace_id,
                    raw_log=b_strip,
                )
            )

        return incidents

    def _extract_stack_frame(self, text: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        """
        Extracts the innermost (most relevant application) stack frame
        from Python, JS, or Java stack traces.
        """
        # 1. Try Python frames
        py_matches = list(self.PYTHON_FRAME.finditer(text))
        if py_matches:
            # Iterate backwards to find application frame (skip python stdlib/site-packages if possible)
            for m in reversed(py_matches):
                f_path = m.group(1)
                line_no = int(m.group(2))
                func_name = m.group(3)
                if not any(lib in f_path for lib in ("lib/python", "site-packages", "dist-packages")):
                    return f_path, line_no, func_name
            # Fallback to last match
            last = py_matches[-1]
            return last.group(1), int(last.group(2)), last.group(3)

        # 2. Try JavaScript frames
        js_matches = list(self.JS_FRAME.finditer(text))
        if js_matches:
            for m in reversed(js_matches):
                func_name = m.group(1)
                f_path = m.group(2)
                line_no = int(m.group(3))
                if "node_modules" not in f_path:
                    return f_path, line_no, func_name
            last = js_matches[-1]
            return last.group(2), int(last.group(3)), last.group(1)

        # 3. Try Java frames
        java_matches = list(self.JAVA_FRAME.finditer(text))
        if java_matches:
            last = java_matches[-1]
            pkg = last.group(1)
            method = last.group(2)
            f_name = last.group(3)
            line_no = int(last.group(4))
            return f_name, line_no, f"{pkg}.{method}"

        return None, None, None

    def _extract_exception(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """Extracts exception class name and message text from exception line."""
        matches = list(self.EXCEPTION_LINE.finditer(text))
        if matches:
            last = matches[-1]
            return last.group(1).strip(), last.group(2).strip()
        return None, None
