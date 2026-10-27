"""
Data models for the Cost & Token Governor Agent (Layer: Optional).
Role: Budget controller.
Description: Sets token budgets and routes simple checks to small models.
Access: read-only
Trigger: on every task
Optional: True
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class ModelTier(str, Enum):
    """Categorical classification of AI model tiers."""
    SMALL = "small"    # Fast, high-throughput models (e.g., gemini-2.5-flash)
    MEDIUM = "medium"  # Balanced reasoning models (e.g., gemini-2.5-pro / claude-sonnet)
    LARGE = "large"    # Deep reasoning / heavyweight models (e.g., gemini-ultra)


TestType_suppress_warning = False
ModelTier.__test__ = False


class TaskComplexity(str, Enum):
    """Complexity classification of a task or sub-step."""
    TRIVIAL = "trivial"    # Simple regex, single-entity lookup, style check
    SIMPLE = "simple"      # AST traversal, file shard mapping, standard linting
    MODERATE = "moderate"  # Cross-module edge linking, SAST analysis, blast radius
    COMPLEX = "complex"    # Multi-file refactor, architecture review, whole-repo synthesis


class TaskPlanStep(BaseModel):
    """
    A single step or agent invocation in a task execution plan.
    """
    __test__ = False
    step_id: str = Field(description="Unique step identifier, e.g. 'step_1_ast_scan'")
    agent_id: str = Field(description="Target agent ID, e.g. 'structure_mapper', 'architecture_review'")
    task_type: str = Field(
        default="general",
        description="Type of task: 'ast_scan', 'lint_check', 'blast_radius', 'sast_scan', 'refactor', 'test_gen'",
    )
    complexity: TaskComplexity = Field(
        default=TaskComplexity.SIMPLE,
        description="Assessed computational/reasoning complexity",
    )
    estimated_input_tokens: int = Field(
        default=1500,
        ge=0,
        description="Estimated prompt/input tokens required for this step",
    )
    target_files: List[str] = Field(
        default_factory=list,
        description="Target repository file paths involved in this step",
    )
    requested_tier: Optional[ModelTier] = Field(
        default=None,
        description="Nominal model tier requested by the agent specification or user",
    )


class TaskPlan(BaseModel):
    """
    Complete planned sequence of agent tasks and execution steps.
    """
    __test__ = False
    plan_id: str = Field(default="plan_default", description="Unique task plan identifier")
    title: str = Field(default="Multi-Agent Execution Plan", description="Human-readable title")
    steps: List[TaskPlanStep] = Field(
        default_factory=list,
        description="Ordered list of planned agent steps",
    )
    overall_budget_usd: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Maximum dollar budget ceiling allocated for this plan",
    )
    max_total_tokens: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum token ceiling allowed across all steps",
    )


class AgentTokenUsage(BaseModel):
    """
    Aggregated token consumption metrics for a specific agent.
    """
    __test__ = False
    agent_id: str = Field(description="Identifier of the agent")
    prompt_tokens: int = Field(default=0, ge=0, description="Input/prompt tokens consumed")
    completion_tokens: int = Field(default=0, ge=0, description="Output/completion tokens consumed")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed (prompt + completion)")
    estimated_cost_usd: float = Field(default=0.0, ge=0.0, description="Calculated expenditure in USD")
    calls_count: int = Field(default=0, ge=0, description="Number of agent invocations")


class TokenUsageSummary(BaseModel):
    """
    Historical or real-time token telemetry across all agents.
    """
    __test__ = False
    total_prompt_tokens: int = Field(default=0, ge=0)
    total_completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    usage_by_agent: Dict[str, AgentTokenUsage] = Field(
        default_factory=dict,
        description="Token metrics mapped by agent ID",
    )
    usage_by_tier: Dict[str, int] = Field(
        default_factory=dict,
        description="Token counts broken down by model tier",
    )


class RoutingDecision(BaseModel):
    """
    Dynamic model tier and token budget assignment for a task step.
    Routes simple checks to small models to minimize token usage and cost.
    """
    __test__ = False
    step_id: str = Field(description="Target step identifier")
    agent_id: str = Field(description="Target agent identifier")
    selected_model_tier: ModelTier = Field(description="Allocated model tier: small, medium, or large")
    selected_model_name: str = Field(description="Canonical model identifier (e.g., 'gemini-2.5-flash')")
    max_input_tokens: int = Field(description="Hard token budget cap for prompt/context")
    max_output_tokens: int = Field(description="Hard token budget cap for completion/response")
    down_routed: bool = Field(
        default=False,
        description="True if step was down-routed from a higher tier to save tokens and cost",
    )
    estimated_savings_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated dollar savings from down-routing or token capping",
    )
    routing_rationale: str = Field(description="Explanation of routing decision based on task complexity")


class CostReport(BaseModel):
    """
    Detailed cost, token budget utilization, and optimization report.
    """
    __test__ = False
    report_id: str = Field(description="Unique report identifier")
    total_tokens_consumed: int = Field(default=0, ge=0, description="Total tokens consumed across recorded runs")
    total_cost_usd: float = Field(default=0.0, ge=0.0, description="Total spend in USD")
    budget_limit_usd: Optional[float] = Field(default=None, description="Configured budget limit in USD")
    budget_consumed_pct: Optional[float] = Field(default=None, description="Percentage of budget limit consumed")
    is_budget_exceeded: bool = Field(default=False, description="True if spend exceeds configured budget ceiling")
    total_estimated_savings_usd: float = Field(default=0.0, ge=0.0, description="Total dollars saved via down-routing")
    breakdown_by_agent: Dict[str, float] = Field(
        default_factory=dict,
        description="Expenditure breakdown in USD by agent ID",
    )
    optimization_recommendations: List[str] = Field(
        default_factory=list,
        description="Actionable guidance to further curb token usage across agents",
    )


class CostTokenGovernorInput(BaseModel):
    """
    Input payload for the Cost & Token Governor Agent.
    Strictly accepts task_plan and token_usage as mandated by specification.
    """
    __test__ = False
    task_plan: Union[TaskPlan, Dict[str, Any], List[Union[TaskPlanStep, Dict[str, Any]]]] = Field(
        description="Planned task sequence or agent steps requiring token budgeting",
    )
    token_usage: Optional[Union[TokenUsageSummary, Dict[str, Any], List[Dict[str, Any]]]] = Field(
        default=None,
        description="Current or historical token telemetry from usage.read",
    )
    budget_limit_usd: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Optional budget limit ceiling for cost alerting",
    )
    aggressive_savings: bool = Field(
        default=False,
        description="If True, down-routes moderate complexity tasks to small models whenever possible",
    )


class CostTokenGovernorOutput(BaseModel):
    """
    Output payload produced by the Cost & Token Governor Agent.
    Outputs routing_decisions and cost_report as mandated by specification.
    """
    __test__ = False
    routing_decisions: List[RoutingDecision] = Field(
        default_factory=list,
        description="Dynamic model tier routing decisions and token limits per step",
    )
    cost_report: CostReport = Field(
        description="Comprehensive cost breakdown and budget telemetry",
    )
    total_plan_steps: int = Field(default=0, ge=0, description="Total steps budgeted")
    total_down_routed_steps: int = Field(default=0, ge=0, description="Count of steps routed to smaller models")
    projected_plan_cost_usd: float = Field(default=0.0, ge=0.0, description="Estimated total cost to execute plan")
