"""
Data models for the Control Layer:
- Orchestrator Agent (Master Planner & Task Coordinator)
- Result Aggregator & Critic Agent (Finding Normalizer & False Alarm Pruner)
"""

from enum import Enum
import time
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from models.registry import RegistryNode


class TaskExecutionMode(str, Enum):
    """Execution dispatch mode for orchestration subtasks."""
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class SubTaskStatus(str, Enum):
    """Lifecycle status of a delegated subtask."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FindingCategory(str, Enum):
    """Standardized categories for normalized findings."""
    SECURITY = "security"
    QUALITY = "quality"
    ARCHITECTURE = "architecture"
    POLICY_COMPLIANCE = "policy_compliance"
    PERFORMANCE = "performance"
    RUNTIME_ANOMALY = "runtime_anomaly"


class NormalizedSeverity(str, Enum):
    """Harmonized severity scale across all agents."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class CriticFinding(BaseModel):
    """
    Harmonized finding synthesized across specialist agents.
    Includes false alarm assessment, cited rule/tool, and impact score.
    """
    finding_id: str = Field(description="Unique ID for the finding")
    source_agent: str = Field(description="Agent that originated the finding")
    tool_name: Optional[str] = Field(default=None, description="Specific tool or engine that detected it")
    rule_or_cve_id: Optional[str] = Field(default=None, description="Cited Rule ID, CWE, CVE, or OWASP tag")
    title: str = Field(description="Short human-readable summary")
    category: FindingCategory = Field(description="Category of the finding")
    severity: NormalizedSeverity = Field(description="Harmonized severity level")
    file_path: Optional[str] = Field(default=None, description="Target file path")
    line_number: Optional[int] = Field(default=None, description="Exact line number if applicable")
    code_snippet: Optional[str] = Field(default=None, description="Offending code line or block")
    description: str = Field(description="Detailed explanation of the issue")
    remediation_proposal: str = Field(description="Actionable remediation proposal for human approval")
    is_false_alarm: bool = Field(default=False, description="Flagged by Critic as a false alarm or duplicate")
    suppression_reason: Optional[str] = Field(default=None, description="Rationale if suppressed or pruned")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    impact_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Ranked business & blast radius impact score")


class OrchestratorSubTask(BaseModel):
    """A discrete unit of work planned and scheduled by the Orchestrator."""
    subtask_id: str = Field(description="Unique subtask identifier, e.g. 'subtask_1_security'")
    agent_id: str = Field(description="Target specialist agent ID (e.g. 'security', 'code_quality')")
    layer: str = Field(description="Layer of the target agent")
    description: str = Field(description="Human-readable subtask description")
    execution_mode: TaskExecutionMode = Field(default=TaskExecutionMode.PARALLEL)
    depends_on: List[str] = Field(default_factory=list, description="IDs of prerequisite subtasks")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Input parameters passed to the agent")
    status: SubTaskStatus = Field(default=SubTaskStatus.PENDING)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=2, ge=0)
    result: Optional[Any] = Field(default=None, description="Output payload produced by the agent")
    error: Optional[str] = Field(default=None, description="Error message if execution failed")
    duration_ms: Optional[float] = Field(default=None, description="Runtime duration in milliseconds")


class TaskPlanRequest(BaseModel):
    """User input or trigger initiating an orchestrated multi-agent review."""
    task_id: str = Field(default_factory=lambda: f"task_{int(time.time())}", description="Unique ID for this orchestrated workflow")
    task_title: str = Field(description="Title or high-level intent of the task")
    user_prompt: Optional[str] = Field(default=None, description="Natural language instructions from the user")
    target_files: List[str] = Field(default_factory=list, description="Specific changed files or scope")
    repo_root: Optional[str] = Field(default=None, description="Path to repository root")
    budget_limit_usd: Optional[float] = Field(default=None, description="Optional token budget ceiling")
    rule_files: List[str] = Field(default_factory=list, description="Optional uploaded rule/policy documents")
    require_human_approval: bool = Field(default=True, description="Strictly block automated edits until human approval")


class UnifiedReport(BaseModel):
    """
    Consolidated report compiled by the Result Aggregator & Critic.
    Ranks findings by impact, shows pruned false alarms, and presents options.
    """
    report_id: str = Field(description="Unique report ID")
    task_id: str = Field(description="Associated orchestrated task ID")
    executive_summary: str = Field(description="High-level synthesis for engineering leadership")
    overall_health_score: float = Field(ge=0.0, le=100.0, description="Composite system health score")
    total_findings_detected: int = Field(default=0, description="Raw finding count from all agents")
    false_alarms_pruned: int = Field(default=0, description="Duplicate or false positive findings pruned by Critic")
    active_findings_count: int = Field(default=0, description="Active verified findings requiring attention")
    critical_count: int = Field(default=0)
    high_count: int = Field(default=0)
    medium_count: int = Field(default=0)
    low_count: int = Field(default=0)
    info_count: int = Field(default=0)
    ranked_findings: List[CriticFinding] = Field(
        default_factory=list,
        description="Verified findings sorted by composite impact score in descending order",
    )
    pruned_findings: List[CriticFinding] = Field(
        default_factory=list,
        description="Findings filtered out as duplicates or false alarms with justifications",
    )
    conflicts_resolved: List[str] = Field(
        default_factory=list,
        description="Descriptions of conflicting agent recommendations unified by Critic",
    )
    remediation_options: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Structured remediation proposals for Human in the Loop selection",
    )
    agent_health_scores: Dict[str, float] = Field(
        default_factory=dict,
        description="Score breakdown by domain (security, quality, architecture, rules, runtime)",
    )


class OrchestratorOutput(BaseModel):
    """Final output from Orchestrator execution."""
    task_id: str
    status: str = Field(description="'COMPLETED', 'FAILED', or 'AWAITING_APPROVAL'")
    subtasks: List[OrchestratorSubTask] = Field(description="List of all planned and executed subtasks")
    unified_report: UnifiedReport = Field(description="Final unified critic report")
    total_duration_ms: float = Field(description="Total execution time across all agents")
    total_tokens_consumed: int = Field(default=0, description="Cumulative tokens burned")
    total_cost_usd: float = Field(default=0.0, description="Total financial spend in USD")
    human_approval_required: bool = Field(default=True, description="Enforces human-in-the-loop gate before edit")
