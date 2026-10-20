"""
Base abstractions for all agents in the Multi-Agent AI Platform.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

import time
from core.exceptions import UnauthorizedAccessError
from core.logger import AgentLogger, AgentLogRecord

logger = logging.getLogger(__name__)


class AgentMetadata(BaseModel):
    """Declarative specification for an agent in the platform."""
    id: str
    name: str
    layer: str
    role: str
    description: str
    access: str
    model_tier: str
    inputs: List[str]
    outputs: List[str]
    tools: List[str]
    trigger: str
    optional: bool = False


class BaseAgent(ABC):
    """
    Abstract base class for all agents across all layers:
    Control, Graph, Understanding, Quality, Safety, Runtime, Action, Optional.
    Provides automatic structured event logging and execution telemetry.
    """

    def __init__(self, metadata: AgentMetadata, log_file: Optional[str] = None):
        self.metadata = metadata
        self.logger = logging.getLogger(f"{self.metadata.layer}.{self.metadata.id}")
        self.tracer = AgentLogger.get_logger(log_file=log_file)

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def layer(self) -> str:
        return self.metadata.layer

    @property
    def access(self) -> str:
        return self.metadata.access

    def has_access(self, required_permission: str) -> bool:
        """Checks if this agent possesses the required access permission."""
        return self.metadata.access == required_permission

    def require_access(self, required_permission: str) -> None:
        """Raises UnauthorizedAccessError if the agent lacks required permission."""
        if not self.has_access(required_permission):
            raise UnauthorizedAccessError(
                f"Agent '{self.id}' with access '{self.access}' cannot perform "
                f"actions requiring '{required_permission}'."
            )

    def log_event(
        self,
        event: str,
        message: str,
        level: str = "INFO",
        duration_ms: Optional[float] = None,
        **data,
    ) -> AgentLogRecord:
        """Records an event with structured metadata into central agent log."""
        return self.tracer.log(
            layer=self.layer,
            agent_id=self.id,
            level=level,
            event=event,
            message=message,
            duration_ms=duration_ms,
            data=data,
        )

    def log_started(self, inputs_summary: Optional[Dict[str, Any]] = None) -> float:
        """Logs execution commencement and returns monotonic start timestamp."""
        t0 = time.time()
        self.log_event(
            event="agent.started",
            message=f"{self.name} started execution",
            level="INFO",
            inputs=inputs_summary or {},
        )
        return t0

    def log_completed(self, start_time: float, outputs_summary: Optional[Dict[str, Any]] = None) -> None:
        """Logs successful execution completion with duration."""
        duration_ms = (time.time() - start_time) * 1000
        self.log_event(
            event="agent.completed",
            message=f"{self.name} finished successfully in {duration_ms:.1f}ms",
            level="INFO",
            duration_ms=duration_ms,
            outputs=outputs_summary or {},
        )

    def log_failed(self, start_time: float, error: Exception) -> None:
        """Logs execution failure with error details."""
        duration_ms = (time.time() - start_time) * 1000
        self.log_event(
            event="agent.failed",
            message=f"{self.name} failed: {str(error)}",
            level="ERROR",
            duration_ms=duration_ms,
            error_type=type(error).__name__,
        )

    @abstractmethod
    def execute(self, inputs: Any) -> Any:
        """
        Executes the agent's core responsibility given its designated inputs.
        Must be implemented by every agent.
        """
        pass

    def get_spec(self) -> Dict[str, Any]:
        """Returns the dictionary representation of the agent specification."""
        return self.metadata.model_dump()
