"""
Tests for Agent 15: Cost & Token Governor (Layer: Optional).
Validates:
- Agent metadata conformance with declarative specification.
- Strict read-only access control enforcement.
- Tool: usage.read token consumption aggregation and tier pricing calculations.
- Tool: router.set dynamic model routing, token budget caps, and down-routing simple checks.
- Budget ceiling breach detection and warning alerts.
- Aggressive token savings mode.
- End-to-end task plan budgeting, routing decisions, and cost reporting.
"""

import json
from pathlib import Path
import tempfile
import pytest

from agents.optional.cost_token_governor_agent import (
    COST_TOKEN_GOVERNOR_METADATA,
    CostTokenGovernor,
    CostTokenGovernorAgent,
)
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


def test_cost_token_governor_metadata():
    """Validates that Agent 15 metadata matches the exact declarative specification."""
    meta = COST_TOKEN_GOVERNOR_METADATA
    assert meta.id == "cost_token_governor"
    assert meta.name == "Cost & Token Governor"
    assert meta.layer == "optional"
    assert meta.role == "Budget controller"
    assert meta.description == "Sets token budgets and routes simple checks to small models."
    assert meta.access == "read-only"
    assert meta.model_tier == "small"
    assert meta.inputs == ["task_plan", "token_usage"]
    assert meta.outputs == ["routing_decisions", "cost_report"]
    assert set(meta.tools) == {"usage.read", "router.set"}
    assert meta.trigger == "on every task"
    assert meta.optional is True


def test_read_only_access_enforcement():
    """Validates that read-only access is strictly enforced and write access is rejected."""
    agent = CostTokenGovernorAgent()
    assert agent.access == "read-only"

    plan = TaskPlan(
        plan_id="p1",
        steps=[TaskPlanStep(step_id="s1", agent_id="structure_mapper", task_type="ast_scan", complexity=TaskComplexity.SIMPLE)],
    )
    inp = CostTokenGovernorInput(task_plan=plan)

    # Clean execution with read-only permission
    out = agent.execute(inp)
    assert isinstance(out, CostTokenGovernorOutput)
    assert len(out.routing_decisions) == 1

    # Tampered agent with 'can-edit' must raise UnauthorizedAccessError
    tampered_meta = agent.metadata.model_copy(update={"access": "can-edit"})
    tampered_agent = CostTokenGovernorAgent(metadata=tampered_meta)
    with pytest.raises(UnauthorizedAccessError) as exc_info:
        tampered_agent.execute(inp)
    assert "cannot perform actions requiring 'read-only'" in str(exc_info.value)


def test_usage_read_tool_pricing_calculation():
    """Validates accurate pricing math across small, medium, and large tiers."""
    tool = UsageReadTool()

    # Small tier: $0.075/1M input, $0.30/1M output
    cost_small = tool.calculate_cost(prompt_tokens=1_000_000, completion_tokens=1_000_000, tier=ModelTier.SMALL)
    assert pytest.approx(cost_small, 0.0001) == 0.375

    # Medium tier: $1.00/1M input, $4.00/1M output
    cost_med = tool.calculate_cost(prompt_tokens=1_000_000, completion_tokens=1_000_000, tier=ModelTier.MEDIUM)
    assert pytest.approx(cost_med, 0.0001) == 5.00

    # Large tier: $5.00/1M input, $15.00/1M output
    cost_large = tool.calculate_cost(prompt_tokens=1_000_000, completion_tokens=1_000_000, tier=ModelTier.LARGE)
    assert pytest.approx(cost_large, 0.0001) == 20.00


def test_usage_read_tool_log_ingestion():
    """Validates parsing token consumption records from agents.jsonl logs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_file = Path(tmp_dir) / "agents.jsonl"
        records = [
            {"agent_id": "structure_mapper", "data": {"prompt_tokens": 1200, "completion_tokens": 300}},
            {"agent_id": "structure_mapper", "data": {"prompt_tokens": 800, "completion_tokens": 200}},
            {"agent_id": "architecture_review", "data": {"prompt_tokens": 5000, "completion_tokens": 1500}},
        ]
        with open(log_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        tool = UsageReadTool(log_file=log_file)
        summary = tool.read_usage()

        assert summary.total_prompt_tokens == 7000
        assert summary.total_completion_tokens == 2000
        assert summary.total_tokens == 9000
        assert "structure_mapper" in summary.usage_by_agent
        assert summary.usage_by_agent["structure_mapper"].total_tokens == 2500
        assert summary.total_cost_usd > 0.0


def test_router_set_routes_simple_checks_to_small_models():
    """Validates router.set dynamically routes simple/trivial checks to small models."""
    router = RouterSetTool()

    # 1. Simple AST scan step with medium requested tier
    simple_step = TaskPlanStep(
        step_id="step_ast",
        agent_id="code_quality",
        task_type="lint_check",
        complexity=TaskComplexity.SIMPLE,
        estimated_input_tokens=3000,
        requested_tier=ModelTier.MEDIUM,
    )
    decision = router.route_step(simple_step)

    # Must be down-routed to SMALL model (e.g. gemini-2.5-flash)
    assert decision.selected_model_tier == ModelTier.SMALL
    assert decision.selected_model_name == "gemini-2.5-flash"
    assert decision.down_routed is True
    assert decision.estimated_savings_usd > 0.0
    assert decision.max_input_tokens <= 8192

    # 2. Complex Architecture review step
    complex_step = TaskPlanStep(
        step_id="step_arch",
        agent_id="architecture_review",
        task_type="architecture_review",
        complexity=TaskComplexity.COMPLEX,
        estimated_input_tokens=12000,
        requested_tier=ModelTier.MEDIUM,
    )
    decision_complex = router.route_step(complex_step)
    assert decision_complex.selected_model_tier == ModelTier.MEDIUM
    assert decision_complex.down_routed is False


def test_cost_token_governor_budget_limit_breach():
    """Validates that governor detects budget limit breaches and issues warning recommendations."""
    agent = CostTokenGovernorAgent()

    # Mock high telemetry spend ($12.50)
    mock_usage = {
        "usage_by_agent": {
            "tech_scout": {"prompt_tokens": 10_000_000, "completion_tokens": 1_000_000, "model_tier": "medium"}
        }
    }

    inp = CostTokenGovernorInput(
        task_plan=[
            TaskPlanStep(step_id="s1", agent_id="tech_scout", task_type="tech_research", complexity=TaskComplexity.COMPLEX)
        ],
        token_usage=mock_usage,
        budget_limit_usd=10.00,  # $10 budget limit vs $14 spend
    )
    res = agent.execute(inp)
    rep = res.cost_report

    assert rep.is_budget_exceeded is True
    assert rep.budget_consumed_pct > 100.0
    assert any("BUDGET CEILING BREACHED" in r for r in rep.optimization_recommendations)


def test_aggressive_savings_mode():
    """Validates aggressive savings down-routes moderate complexity tasks to small models."""
    agent = CostTokenGovernorAgent()

    plan = TaskPlan(
        plan_id="p_aggressive",
        steps=[
            TaskPlanStep(
                step_id="s_mod",
                agent_id="security",
                task_type="sast_scan",
                complexity=TaskComplexity.MODERATE,
                estimated_input_tokens=6000,
                requested_tier=ModelTier.MEDIUM,
            )
        ],
    )

    # 1. Standard mode: moderate task stays on MEDIUM
    out_std = agent.execute(CostTokenGovernorInput(task_plan=plan, aggressive_savings=False))
    assert out_std.routing_decisions[0].selected_model_tier == ModelTier.MEDIUM
    assert out_std.routing_decisions[0].down_routed is False

    # 2. Aggressive mode: moderate task down-routed to SMALL
    out_agg = agent.execute(CostTokenGovernorInput(task_plan=plan, aggressive_savings=True))
    assert out_agg.routing_decisions[0].selected_model_tier == ModelTier.SMALL
    assert out_agg.routing_decisions[0].down_routed is True
    assert out_agg.routing_decisions[0].estimated_savings_usd > 0.0


def test_end_to_end_cost_token_governor_pipeline():
    """Validates complete task plan budgeting, down-routing, and cost report formulation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        log_file = Path(tmp_dir) / "agents.jsonl"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"agent_id": "structure_mapper", "data": {"prompt_tokens": 1500, "completion_tokens": 300}}) + "\n")
            f.write(json.dumps({"agent_id": "impact_analyzer", "data": {"prompt_tokens": 2000, "completion_tokens": 400}}) + "\n")

        agent = CostTokenGovernorAgent(log_file=log_file)

        plan = TaskPlan(
            plan_id="e2e_plan",
            overall_budget_usd=5.00,
            steps=[
                TaskPlanStep(step_id="step_1", agent_id="structure_mapper", task_type="ast_scan", complexity=TaskComplexity.SIMPLE, estimated_input_tokens=2000, requested_tier=ModelTier.SMALL),
                TaskPlanStep(step_id="step_2", agent_id="relationship_linker", task_type="code_edges", complexity=TaskComplexity.SIMPLE, estimated_input_tokens=2500, requested_tier=ModelTier.MEDIUM),
                TaskPlanStep(step_id="step_3", agent_id="code_quality", task_type="lint_check", complexity=TaskComplexity.TRIVIAL, estimated_input_tokens=1500, requested_tier=ModelTier.MEDIUM),
                TaskPlanStep(step_id="step_4", agent_id="architecture_review", task_type="architecture_review", complexity=TaskComplexity.COMPLEX, estimated_input_tokens=10000, requested_tier=ModelTier.MEDIUM),
            ],
        )

        inp = CostTokenGovernorInput(
            task_plan=plan,
            budget_limit_usd=5.00,
            aggressive_savings=False,
        )
        out = agent.execute(inp)

        # Assert plan metrics
        assert out.total_plan_steps == 4
        # Steps 2 and 3 should be down-routed to SMALL from MEDIUM
        assert out.total_down_routed_steps == 2
        assert out.projected_plan_cost_usd > 0.0

        # Assert Cost Report
        rep = out.cost_report
        assert rep.total_tokens_consumed > 0
        assert rep.total_cost_usd > 0.0
        assert rep.budget_limit_usd == 5.00
        assert rep.is_budget_exceeded is False
        assert rep.total_estimated_savings_usd > 0.0
        assert len(rep.optimization_recommendations) >= 2
        assert "structure_mapper" in rep.breakdown_by_agent
