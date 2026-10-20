"""
Unified logging and tracing system for the Multi-Agent AI Platform.
Provides structured JSONL file logs and formatted console output to track
all agent executions, inputs, decisions, tool calls, and outputs.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import threading
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

DEFAULT_LOG_DIR = os.environ.get("AGENT_LOG_DIR", "logs")
DEFAULT_LOG_FILE = os.environ.get("AGENT_LOG_FILE", os.path.join(DEFAULT_LOG_DIR, "agents.jsonl"))


class AgentLogRecord(BaseModel):
    """Structured log record representing an event in an agent's lifecycle."""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    level: str = "INFO"
    layer: str
    agent_id: str
    event: str
    message: str
    duration_ms: Optional[float] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class AgentLogger:
    """Thread-safe multi-agent logger writing to console and persistent JSONL storage."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self, log_file: Optional[str] = None, console_output: bool = True):
        self.log_file = Path(log_file or DEFAULT_LOG_FILE)
        self.console_output = console_output
        self._write_lock = threading.Lock()
        
        # Ensure log directory exists
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    @classmethod
    def get_logger(cls, log_file: Optional[str] = None) -> "AgentLogger":
        """Singleton accessor for central platform agent logger."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(log_file=log_file)
            return cls._instance

    def log(
        self,
        layer: str,
        agent_id: str,
        level: str,
        event: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ) -> AgentLogRecord:
        """Records a structured agent log entry."""
        record = AgentLogRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=level.upper(),
            layer=layer,
            agent_id=agent_id,
            event=event,
            message=message,
            duration_ms=duration_ms,
            data=data or {},
        )

        # Write to JSONL file
        self._write_to_file(record)

        # Output to console if enabled
        if self.console_output:
            self._write_to_console(record)

        return record

    def info(self, layer: str, agent_id: str, event: str, message: str, **kwargs) -> AgentLogRecord:
        return self.log(layer, agent_id, "INFO", event, message, data=kwargs)

    def warning(self, layer: str, agent_id: str, event: str, message: str, **kwargs) -> AgentLogRecord:
        return self.log(layer, agent_id, "WARNING", event, message, data=kwargs)

    def error(self, layer: str, agent_id: str, event: str, message: str, **kwargs) -> AgentLogRecord:
        return self.log(layer, agent_id, "ERROR", event, message, data=kwargs)

    def debug(self, layer: str, agent_id: str, event: str, message: str, **kwargs) -> AgentLogRecord:
        return self.log(layer, agent_id, "DEBUG", event, message, data=kwargs)

    def _write_to_file(self, record: AgentLogRecord) -> None:
        """Appends log record to disk JSONL file safely."""
        try:
            with self._write_lock:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record.model_dump()) + "\n")
        except Exception:
            pass

    def _write_to_console(self, record: AgentLogRecord) -> None:
        """Formats and writes record to stdout with visual cues."""
        time_str = record.timestamp.split("T")[1][:8]
        level_colors = {
            "INFO": "\033[92m",      # Green
            "WARNING": "\033[93m",   # Yellow
            "ERROR": "\033[91m",     # Red
            "DEBUG": "\033[94m",     # Blue
        }
        color = level_colors.get(record.level, "\033[0m")
        reset = "\033[0m"
        dur_str = f" ({record.duration_ms:.1f}ms)" if record.duration_ms is not None else ""

        line = (
            f"[{time_str}] {color}[{record.level:<7}]{reset} "
            f"[{record.layer.upper()}.{record.agent_id}] "
            f"[{record.event}] {record.message}{dur_str}"
        )
        print(line, flush=True)

    def get_recent_logs(
        self,
        limit: int = 50,
        agent_id: Optional[str] = None,
        layer: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[AgentLogRecord]:
        """Reads and filters log records from the persistent log file."""
        if not self.log_file.exists():
            return []

        records: List[AgentLogRecord] = []
        with self._write_lock:
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if agent_id and obj.get("agent_id") != agent_id:
                            continue
                        if layer and obj.get("layer") != layer:
                            continue
                        if level and obj.get("level") != level.upper():
                            continue
                        records.append(AgentLogRecord.model_validate(obj))
                    except Exception:
                        continue

        return records[-limit:]


# Global shared logger instance
agent_logger = AgentLogger.get_logger()
