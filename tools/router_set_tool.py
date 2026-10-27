"""
Tool: router.set
Configures dynamic model routing decisions, enforces token budgets,
and down-routes simple checks to small models to minimize token usage.
"""

from typing import Any, Dict, List, Optional
from models.cost_token_governor import ModelTier, RoutingDecision, TaskComplexity, TaskPlanStep
from tools.usage_read_tool import UsageReadTool


class RouterSetTool:
    """
    Intelligent Model Router and Token Budgeting Tool.
    Enforces token caps and selects the most cost-effective model tier
    suitable for the computational complexity of the task.
    """

    name = "router.set"
    description = (
        "Configures model routing rules, assigns token budget caps, "
        "and routes simple checks to small models to eliminate token waste."
    )

    MODEL_NAMES = {
        ModelTier.SMALL: "gemini-2.5-flash",
        ModelTier.MEDIUM: "gemini-2.5-pro",
        ModelTier.LARGE: "gemini-ultra",
    }

    # Default token budget caps by tier
    BUDGET_CAPS = {
        ModelTier.SMALL: {"max_input": 4096, "max_output": 1024},
        ModelTier.MEDIUM: {"max_input": 12288, "max_output": 3072},
        ModelTier.LARGE: {"max_input": 24576, "max_output": 6144},
    }

    def __init__(self):
        self.usage_tool = UsageReadTool()
        self.active_policies: Dict[str, Any] = {
            "down_route_simple_checks": True,
            "max_default_input_tokens": 8192,
            "max_default_output_tokens": 2048,
        }

    def set_policy(self, key: str, value: Any) -> None:
        """Sets a runtime routing configuration policy."""
        self.active_policies[key] = value

    def route_step(
        self,
        step: TaskPlanStep,
        aggressive_savings: bool = False,
    ) -> RoutingDecision:
        """
        Evaluates a task step and assigns the optimal model tier, token limits,
        and computes projected savings from down-routing.
        """
        nominal_tier = step.requested_tier or self._infer_default_tier(step.agent_id, step.task_type)
        complexity = step.complexity or self._infer_complexity(step.task_type, step.target_files)

        # 1. Routing Rule Engine
        selected_tier = nominal_tier
        rationale = f"Standard allocation for {step.agent_id} ({complexity.value} complexity)"
        down_routed = False

        if complexity == TaskComplexity.TRIVIAL:
            # Always route trivial checks (regex, formatting, symbol lookups) to SMALL
            selected_tier = ModelTier.SMALL
            down_routed = (nominal_tier != ModelTier.SMALL)
            rationale = "Trivial task routed to small model with compact token cap"

        elif complexity == TaskComplexity.SIMPLE:
            # AST mapping, single file linting, unit checks -> SMALL
            selected_tier = ModelTier.SMALL
            down_routed = (nominal_tier != ModelTier.SMALL)
            rationale = "Simple check routed to small model to optimize token throughput"

        elif complexity == TaskComplexity.MODERATE:
            if aggressive_savings:
                selected_tier = ModelTier.SMALL
                down_routed = (nominal_tier != ModelTier.SMALL)
                rationale = "Moderate task down-routed to small model under aggressive token savings"
            else:
                selected_tier = ModelTier.MEDIUM
                down_routed = (nominal_tier == ModelTier.LARGE)
                rationale = "Moderate complexity assigned to balanced medium reasoning model"

        else:  # COMPLEX
            selected_tier = nominal_tier if nominal_tier in (ModelTier.MEDIUM, ModelTier.LARGE) else ModelTier.MEDIUM
            rationale = "High complexity multi-component reasoning preserved on pro/medium model"

        # 2. Assign token budget caps
        caps = self.BUDGET_CAPS.get(selected_tier, self.BUDGET_CAPS[ModelTier.SMALL])
        max_in = min(caps["max_input"], max(2048, step.estimated_input_tokens * 2))
        max_out = caps["max_output"]

        # 3. Calculate estimated savings
        savings_usd = 0.0
        if down_routed:
            est_in = step.estimated_input_tokens
            est_out = max_out // 2
            nominal_cost = self.usage_tool.estimate_step_cost(est_in, est_out, nominal_tier)
            selected_cost = self.usage_tool.estimate_step_cost(est_in, est_out, selected_tier)
            savings_usd = max(0.0, round(nominal_cost - selected_cost, 6))

        return RoutingDecision(
            step_id=step.step_id,
            agent_id=step.agent_id,
            selected_model_tier=selected_tier,
            selected_model_name=self.MODEL_NAMES.get(selected_tier, "gemini-2.5-flash"),
            max_input_tokens=max_in,
            max_output_tokens=max_out,
            down_routed=down_routed,
            estimated_savings_usd=savings_usd,
            routing_rationale=rationale,
        )

    def _infer_default_tier(self, agent_id: str, task_type: str) -> ModelTier:
        """Infers default nominal model tier based on platform agent metadata."""
        small_agents = {
            "registry_keeper",
            "structure_mapper",
            "relationship_linker",
            "data_service_mapper",
            "impact_analyzer",
            "code_quality",
            "cost_token_governor",
        }
        medium_agents = {
            "architecture_review",
            "security",
            "observability",
            "scale_load",
            "tech_scout",
            "test_generation",
        }
        if agent_id in small_agents:
            return ModelTier.SMALL
        if agent_id in medium_agents:
            return ModelTier.MEDIUM
        return ModelTier.MEDIUM

    def _infer_complexity(self, task_type: str, target_files: List[str]) -> TaskComplexity:
        """Infers complexity from task type and scope of affected files."""
        t = task_type.lower()
        if "lookup" in t or "style" in t or "regex" in t:
            return TaskComplexity.TRIVIAL
        if "ast" in t or "lint" in t or "format" in t or "diff" in t:
            return TaskComplexity.SIMPLE if len(target_files) <= 5 else TaskComplexity.MODERATE
        if "review" in t or "architecture" in t or "refactor" in t:
            return TaskComplexity.COMPLEX
        if "sast" in t or "blast" in t or "trace" in t or "query" in t:
            return TaskComplexity.MODERATE
        return TaskComplexity.SIMPLE
