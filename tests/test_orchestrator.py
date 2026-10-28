"""
Tests for Orchestrator Agent (Layer: Control).
Verifies subtask planning, sequential and parallel agent dispatch,
retry and error recovery, budget consultation, and human-in-the-loop gate enforcement.
"""

from pathlib import Path
import pytest

from agents.control.orchestrator import (
    ORCHESTRATOR_METADATA,
    OrchestratorAgent,
)
from core.exceptions import UnauthorizedAccessError
from models.control import (
    OrchestratorSubTask,
    SubTaskStatus,
    TaskExecutionMode,
    TaskPlanRequest,
)


def test_orchestrator_metadata():
    """Validates Orchestrator Agent metadata specifications."""
    meta = ORCHESTRATOR_METADATA
    assert meta.id == "orchestrator"
    assert meta.name == "Orchestrator Agent"
    assert meta.layer == "control"
    assert meta.role == "Master Coordinator & Planner"
    assert meta.access == "read-only"
    assert meta.model_tier == "large"
    assert "task_request" in meta.inputs
    assert "unified_report" in meta.outputs
    assert "orchestrator.plan" in meta.tools
    assert "orchestrator.dispatch" in meta.tools
    assert meta.optional is False


def test_orchestrator_read_only_access_enforcement():
    """Ensures orchestrator agent cannot perform unauthorized registry mutations."""
    orchestrator = OrchestratorAgent()
    assert orchestrator.access == "read-only"

    with pytest.raises(UnauthorizedAccessError):
        orchestrator.require_access("registry-write")


def test_orchestrator_plans_subtasks_with_dependencies():
    """Verifies decomposition into discrete sequential and parallel subtasks."""
    orchestrator = OrchestratorAgent()
    req = TaskPlanRequest(
        task_id="task_test_audit",
        task_title="Full Codebase Security and Maintainability Audit",
        require_human_approval=True,
    )

    subtasks = orchestrator._plan_subtasks(req)
    assert len(subtasks) >= 10

    subtask_ids = [s.subtask_id for s in subtasks]
    assert "subtask_1_map" in subtask_ids
    assert "subtask_2_link" in subtask_ids
    assert "subtask_4_impact" in subtask_ids
    assert "subtask_7_security" in subtask_ids
    assert "subtask_8_rules" in subtask_ids

    # Verify dependency links
    st_link = next(s for s in subtasks if s.subtask_id == "subtask_2_link")
    assert "subtask_1_map" in st_link.depends_on

    st_impact = next(s for s in subtasks if s.subtask_id == "subtask_4_impact")
    assert "subtask_2_link" in st_impact.depends_on

    # Verify parallel execution modes for specialist checkers
    st_sec = next(s for s in subtasks if s.subtask_id == "subtask_7_security")
    assert st_sec.execution_mode == TaskExecutionMode.PARALLEL


def test_orchestrator_subtask_retry_and_recovery():
    """Verifies that subtask execution retries on transient errors and recovers."""
    orchestrator = OrchestratorAgent()
    subtask = OrchestratorSubTask(
        subtask_id="test_subtask",
        agent_id="test_agent",
        layer="test",
        description="Fails once then succeeds",
        max_retries=2,
    )

    attempts = {"count": 0}

    def flaky_function():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectionError("Transient network glitch")
        return {"status": "ok", "attempt": attempts["count"]}

    orchestrator._dispatch_with_retry(subtask, flaky_function)

    assert subtask.status == SubTaskStatus.COMPLETED
    assert subtask.retry_count == 1
    assert subtask.result == {"status": "ok", "attempt": 2}


def test_orchestrator_enforces_human_in_the_loop_gate(tmp_path):
    """Ensures Orchestrator marks final state as AWAITING_APPROVAL and blocks auto-edits."""
    # Create minimal repository file
    code_file = tmp_path / "main.py"
    code_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    orchestrator = OrchestratorAgent(repo_root=str(tmp_path))

    req = TaskPlanRequest(
        task_id="task_audit_approval",
        task_title="Verify Human in the loop gate",
        target_files=["main.py"],
        repo_root=str(tmp_path),
        require_human_approval=True,
    )

    out = orchestrator.execute(req)

    assert out.status == "AWAITING_APPROVAL"
    assert out.human_approval_required is True
    assert out.unified_report is not None
    assert out.unified_report.executive_summary is not None
    assert "Human-in-the-Loop" in out.unified_report.executive_summary
