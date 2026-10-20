"""
Base abstractions for all agents in the Multi-Agent AI Platform.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.exceptions import UnauthorizedAccessError

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
    """

    def __init__(self, metadata: AgentMetadata):
        self.metadata = metadata
        self.logger = logging.getLogger(f"{self.metadata.layer}.{self.metadata.id}")

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
