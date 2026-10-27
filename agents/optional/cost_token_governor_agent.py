"""
Agent 15: Cost & Token Governor (Layer: Optional).
Role: Budget controller.
Description: Sets token budgets and routes simple checks to small models.
Access: read-only
Trigger: on every task
Optional: True
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid

from agents.base import AgentMetadata, BaseAgent
from core.exceptions import UnauthorizedAccessError
from models.cost_token_governor import (
    AgentTokenUsage,
    CostReport,
    CostTokenGovernorInput,
    CostTokenGovernorOutput,
    ModelTier,
    RoutingDecision,
    TaskComplexity,
    TaskPlan,
    TaskPlanStep,
    TokenUsageSummary,
)
from tools.router_set_tool import RouterSetTool
from tools.usage_read_tool import UsageReadTool


COST_TOKEN_GOVERNOR_METADATA = AgentMetadata(
    id="cost_token_governor",
    name="Cost & Token Governor",
    layer="optional",
    role="Budget controller",
    description="Sets token budgets and routes simple checks to small models.",
    access="read-only",
    model_tier="small",
    inputs=[
        "task_plan",
        "token_usage",
    ],
    outputs=[
        "routing_decisions",
        "cost_report",
    ],
    tools=[
        "usage.read",
        "router.set",
    ],
    trigger="on every task",
    optional=True,
)


class CostTokenGovernorAgent(BaseAgent):
    """
    Cost & Token Governor Agent (Layer: Optional, Role: Budget controller).
    - Sets hard token budget caps on all multi-agent execution steps.
    - Routes simple, deterministic checks to small models (e.g. gemini-2.5-flash)
      saving up to 90%+ in token consumption and API expenditures.
    - Reads and aggregates historical and active token usage via 'usage.read'.
    - Enforces dynamic routing policies via 'router.set'.
    - Strictly enforces read-only access (reports and routing proposals only).
    """

    __test__ = False

    def __init__(
        self,
        metadata: Optional[AgentMetadata] = None,
        log_file: Optional[Union[str, Path]] = None,
    ):
        meta = (metadata or COST_TOKEN_GOVERNOR_METADATA).model_copy(deep=True)
        super().__init__(meta, log_file=str(log_file) if log_file else None)
        self.usage_tool = UsageReadTool(log_file=log_file)
        self.router_tool = RouterSetTool()

    def execute(
        self,
        payload: Union[CostTokenGovernorInput, Dict[str, Any]],
    ) -> CostTokenGovernorOutput:
        """
        Processes a task plan and token usage telemetry to formulate optimal
        routing decisions and generate an actionable cost & budget report.
        """
        # 1. Enforce strict read-only access
        self.require_access("read-only")

        # 2. Normalize input payload
        if isinstance(payload, dict):
            inp = CostTokenGovernorInput(**payload)
        else:
            inp = payload

        t0 = self.log_started({
            "budget_limit_usd": inp.budget_limit_usd,
            "aggressive_savings": inp.aggressive_savings,
        })

        # 3. Ingest and calculate token usage telemetry via tool: usage.read
        usage_telemetry = self.usage_tool.read_usage(
            raw_telemetry=inp.token_usage.model_dump() if isinstance(inp.token_usage, TokenUsageSummary)
            else inp.token_usage
        )

        # 4. Parse steps from task plan
        steps = self._extract_plan_steps(inp.task_plan)

        # 5. Route each task step via tool: router.set
        routing_decisions: List[RoutingDecision] = []
        total_down_routed = 0
        total_savings = 0.0
        projected_cost = 0.0

        for step in steps:
            decision = self.router_tool.route_step(
                step=step,
                aggressive_savings=inp.aggressive_savings,
            )
            routing_decisions.append(decision)

            if decision.down_routed:
                total_down_routed += 1
                total_savings += decision.estimated_savings_usd

            # Estimate cost for this routed step
            step_cost = self.usage_tool.estimate_step_cost(
                estimated_input_tokens=step.estimated_input_tokens,
                estimated_output_tokens=decision.max_output_tokens // 2,
                tier=decision.selected_model_tier,
            )
            projected_cost += step_cost

        # 6. Formulate Cost Report
        budget_limit = inp.budget_limit_usd or self._extract_plan_budget(inp.task_plan)
        consumed_pct = None
        is_exceeded = False
        if budget_limit and budget_limit > 0:
            consumed_pct = round((usage_telemetry.total_cost_usd / budget_limit) * 100.0, 2)
            is_exceeded = usage_telemetry.total_cost_usd > budget_limit

        recommendations = self._generate_recommendations(
            usage=usage_telemetry,
            decisions=routing_decisions,
            budget_limit=budget_limit,
            is_exceeded=is_exceeded,
        )

        cost_breakdown = {
            a_id: u.estimated_cost_usd
            for a_id, u in usage_telemetry.usage_by_agent.items()
        }

        cost_report = CostReport(
            report_id=f"rep_cost_{uuid.uuid4().hex[:8]}",
            total_tokens_consumed=usage_telemetry.total_tokens,
            total_cost_usd=usage_telemetry.total_cost_usd,
            budget_limit_usd=budget_limit,
            budget_consumed_pct=consumed_pct,
            is_budget_exceeded=is_exceeded,
            total_estimated_savings_usd=round(total_savings, 6),
            breakdown_by_agent=cost_breakdown,
            optimization_recommendations=recommendations,
        )

        output = CostTokenGovernorOutput(
            routing_decisions=routing_decisions,
            cost_report=cost_report,
            total_plan_steps=len(steps),
            total_down_routed_steps=total_down_routed,
            projected_plan_cost_usd=round(projected_cost, 6),
        )

        self.log_completed(t0, {
            "total_steps": len(steps),
            "down_routed_steps": total_down_routed,
            "total_savings_usd": round(total_savings, 6),
            "total_cost_usd": usage_telemetry.total_cost_usd,
            "is_budget_exceeded": is_exceeded,
        })

        return output

    def _extract_plan_steps(
        self,
        task_plan: Union[TaskPlan, Dict[str, Any], List[Union[TaskPlanStep, Dict[str, Any]]]],
    ) -> List[TaskPlanStep]:
        """Normalizes plan steps from various representation formats."""
        if isinstance(task_plan, TaskPlan):
            return task_plan.steps
        if isinstance(task_plan, list):
            steps: List[TaskPlanStep] = []
            for item in task_plan:
                if isinstance(item, TaskPlanStep):
                    steps.append(item)
                elif isinstance(item, dict):
                    steps.append(TaskPlanStep(**item))
            return steps
        if isinstance(task_plan, dict):
            raw_steps = task_plan.get("steps") or []
            return [TaskPlanStep(**s) if isinstance(s, dict) else s for s in raw_steps]
        return []

    def _extract_plan_budget(
        self,
        task_plan: Union[TaskPlan, Dict[str, Any], List[Any]],
    ) -> Optional[float]:
        """Extracts budget limit if defined on the task plan."""
        if isinstance(task_plan, TaskPlan):
            return task_plan.overall_budget_usd
        if isinstance(task_plan, dict):
            return task_plan.get("overall_budget_usd")
        return None

    def _generate_recommendations(
        self,
        usage: TokenUsageSummary,
        decisions: List[RoutingDecision],
        budget_limit: Optional[float],
        is_exceeded: bool,
    ) -> List[str]:
        """Synthesizes actionable recommendations to curb token usage."""
        recs: List[str] = []

        down_routed_count = sum(1 for d in decisions if d.down_routed)
        if down_routed_count > 0:
            recs.append(
                f"Down-routing active: {down_routed_count} simple check(s) routed to small models "
                f"saving estimated token costs."
            )

        # Highlight top spending agent
        if usage.usage_by_agent:
            top_agent = max(usage.usage_by_agent.values(), key=lambda a: a.total_tokens)
            if top_agent.total_tokens > 0:
                pct = (top_agent.total_tokens / max(1, usage.total_tokens)) * 100.0
                recs.append(
                    f"Top token consumer: '{top_agent.agent_id}' responsible for {pct:.1f}% "
                    f"of total tokens ({top_agent.total_tokens:,} tokens). Consider AST slicing."
                )

        if is_exceeded and budget_limit:
            recs.append(
                f"BUDGET CEILING BREACHED: Current spend (${usage.total_cost_usd:.4f}) "
                f"exceeds allocated limit (${budget_limit:.4f}). Apply aggressive down-routing."
            )
        elif budget_limit and usage.total_cost_usd > (budget_limit * 0.8):
            recs.append(
                f"BUDGET WARNING: Spending has reached {((usage.total_cost_usd / budget_limit) * 100):.1f}% "
                f"of limit (${budget_limit:.4f})."
            )

        recs.append(
            "Cache AST & relationship hashes to skip re-analyzing unmodified repository nodes."
        )
        return recs


CostTokenGovernor = CostTokenGovernorAgent
