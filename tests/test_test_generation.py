"""
Tests for Agent 14: Test Generation (Layer: Optional).
Validates:
- Agent metadata conformance with specification.
- Strict 'can-edit' access enforcement and 'read-only' rejection.
- 'after approval' trigger gate (in-memory drafting vs disk write).
- TestRunnerTool syntax validation and real execution.
- Coverage gap ingestion from Code Quality and Impact Analyzer.
- Intelligent AST test synthesis (happy path, edge cases, pytest.raises exception handling).
- End-to-end autonomous test authoring, disk writing, and test runner execution.
"""

from pathlib import Path
import tempfile
import pytest

from agents.optional.test_generation_agent import (
    TEST_GENERATION_METADATA,
    TestGeneration,
    TestGenerationAgent,
)
from core.exceptions import UnauthorizedAccessError
from models.code_quality import FindingSeverity, QualityFinding, QualityFindingCategory
from models.registry import NodeLocation, NodeType, RegistryNode
from models.test_generation import (
    CodeUnderTest,
    CoverageGap,
    TestGenerationInput,
    TestGenerationOutput,
    TestType,
)
from storage.registry_store import CodeRegistryStore
from tools.test_runner_tool import TestRunnerTool


def test_test_generation_metadata():
    """Validates that Agent 14 metadata matches the exact declarative specification."""
    meta = TEST_GENERATION_METADATA
    assert meta.id == "test_generation"
    assert meta.name == "Test Generation"
    assert meta.layer == "optional"
    assert meta.role == "Test writer"
    assert meta.description == "Writes tests for coverage gaps."
    assert meta.access == "can-edit"
    assert meta.model_tier == "medium"
    assert meta.inputs == ["coverage_gaps", "code_under_test"]
    assert meta.outputs == ["new_test_files"]
    assert set(meta.tools) == {"test_runner", "registry.lookup"}
    assert meta.trigger == "after approval"
    assert meta.optional is True


def test_can_edit_access_enforcement():
    """Validates that 'can-edit' access is strictly enforced and 'read-only' is rejected."""
    agent = TestGenerationAgent()
    assert agent.access == "can-edit"

    # Should execute cleanly with can-edit access in dry-run
    inp = TestGenerationInput(
        code_under_test=[CodeUnderTest(file_path="sample.py", content="def add(a: int, b: int) -> int: return a + b\n")],
        approved=True,
        dry_run=True,
    )
    out = agent.execute(inp)
    assert isinstance(out, TestGenerationOutput)
    assert len(out.new_test_files) == 1

    # Tampering metadata to read-only must trigger UnauthorizedAccessError
    tampered_meta = agent.metadata.model_copy(update={"access": "read-only"})
    tampered_agent = TestGenerationAgent(metadata=tampered_meta)
    with pytest.raises(UnauthorizedAccessError) as exc_info:
        tampered_agent.execute(inp)
    assert "cannot perform actions requiring 'can-edit'" in str(exc_info.value)


def test_approval_gate_unapproved_draft():
    """Validates trigger 'after approval': unapproved requests draft in-memory without disk write."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir) / "tests"
        agent = TestGenerationAgent(repo_root=tmp_dir)

        sample_code = (
            "def calculate_discount(price: float, rate: float) -> float:\n"
            "    if rate < 0 or rate > 1:\n"
            "        raise ValueError('Invalid rate')\n"
            "    return price * (1.0 - rate)\n"
        )

        # 1. Unapproved execution
        inp = TestGenerationInput(
            code_under_test=[CodeUnderTest(file_path="services/discount.py", content=sample_code)],
            approved=False,
            output_dir=str(out_dir),
        )
        res = agent.execute(inp)

        assert res.approval_status == "awaiting_approval"
        assert len(res.new_test_files) == 1
        tf = res.new_test_files[0]
        assert tf.written_to_disk is False
        assert "valid" in tf.verification_status
        # Verify no file was created on disk
        assert not Path(tf.test_file_path).exists()


def test_test_runner_tool_syntax_and_execution():
    """Validates TestRunnerTool syntax validation and real pytest execution."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        runner = TestRunnerTool(repo_root=tmp_dir)

        # 1. Syntax check
        valid, err = runner.verify_syntax("def test_ok(): assert True\n")
        assert valid is True
        assert err is None

        invalid, err = runner.verify_syntax("def test_broken( assert True\n")
        assert invalid is False
        assert "SyntaxError" in err

        # 2. In-memory execution of passing test
        pass_code = (
            "import pytest\n"
            "def test_addition():\n"
            "    assert 2 + 3 == 5\n"
        )
        res_pass = runner.run_code(pass_code, temp_dir=Path(tmp_dir))
        assert res_pass.success is True
        assert res_pass.passed == 1
        assert res_pass.failed == 0

        # 3. In-memory execution of failing test
        fail_code = (
            "import pytest\n"
            "def test_failing_case():\n"
            "    assert 10 == 99\n"
        )
        res_fail = runner.run_code(fail_code, temp_dir=Path(tmp_dir))
        assert res_fail.success is False
        assert res_fail.failed == 1
        assert len(res_fail.failures_detail) > 0


def test_ingest_coverage_gaps_from_code_quality():
    """Validates ingesting QualityFinding items with COVERAGE_GAP category."""
    agent = TestGenerationAgent()

    finding = QualityFinding(
        id="cov:gap:orders.py:25",
        category=QualityFindingCategory.COVERAGE_GAP,
        severity=FindingSeverity.MAJOR,
        file_path="orders.py",
        line_number=25,
        end_line_number=35,
        rule_id="coverage:uncovered-lines",
        tool_source="coverage",
        message="10 lines (25-35) in orders.py are uncovered",
        remediation="Write tests covering checkout logic",
    )

    code = (
        "def place_order(order_id: str, amount: float) -> bool:\n"
        "    if amount <= 0:\n"
        "        raise ValueError('Invalid amount')\n"
        "    return True\n"
    )

    inp = TestGenerationInput(
        code_under_test=[CodeUnderTest(file_path="orders.py", content=code)],
        coverage_gaps=[finding],
        approved=True,
        dry_run=True,
    )
    out = agent.execute(inp)

    assert out.total_tests_generated >= 2
    assert out.total_gaps_addressed == 1
    tf = out.new_test_files[0]
    assert any("place_order" in c.name for c in tf.test_cases)


def test_ingest_untested_nodes_from_impact_analyzer():
    """Validates ingesting untested node IDs from Impact Analyzer."""
    store = CodeRegistryStore()
    node = RegistryNode(
        id="func:billing.py:compute_tax",
        name="compute_tax",
        type=NodeType.FUNCTION,
        location=NodeLocation(path="billing.py", start_line=1, end_line=5, signature="compute_tax(amount: float)"),
        hash="test_hash_123",
    )
    store.write_node(node, access_token="registry-write", source_agent="test")

    agent = TestGenerationAgent(registry_store=store)
    code = (
        "def compute_tax(amount: float) -> float:\n"
        "    if amount < 0:\n"
        "        raise ValueError('Negative amount')\n"
        "    return amount * 0.08\n"
    )

    inp = TestGenerationInput(
        code_under_test=[CodeUnderTest(file_path="billing.py", content=code)],
        coverage_gaps=["func:billing.py:compute_tax"],
        approved=True,
        dry_run=True,
    )
    out = agent.execute(inp)

    assert out.total_tests_generated >= 2
    assert "billing.py" in out.new_test_files[0].source_file_path


def test_synthesizes_branch_and_exception_tests():
    """Validates AST analysis detects exceptions and branches, synthesizing pytest.raises."""
    agent = TestGenerationAgent()

    sample_code = (
        "def authenticate(username: str, token: str) -> bool:\n"
        "    if not username:\n"
        "        raise ValueError('Empty username')\n"
        "    if not token:\n"
        "        raise PermissionError('Empty token')\n"
        "    return username == 'admin' and token == 'secret'\n"
    )

    inp = TestGenerationInput(
        code_under_test=[CodeUnderTest(file_path="auth/verifier.py", content=sample_code)],
        approved=True,
        dry_run=True,
    )
    out = agent.execute(inp)

    assert len(out.new_test_files) == 1
    tf = out.new_test_files[0]
    test_names = [tc.name for tc in tf.test_cases]

    # Verify happy path, edge case, and exception test cases are generated
    assert any("happy_path" in n for n in test_names)
    assert any("edge_cases" in n for n in test_names)
    assert any("raises" in n for n in test_names)

    # Check content contains pytest.raises
    assert "pytest.raises(ValueError)" in tf.content or "pytest.raises(PermissionError)" in tf.content


def test_end_to_end_test_generation_pipeline():
    """Validates full agent flow: real file on disk, approved disk write, test_runner execution."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Path(tmp_dir)

        # 1. Create a real module under test
        src_dir = repo / "calculator"
        src_dir.mkdir(parents=True, exist_ok=True)
        mod_file = src_dir / "math_ops.py"
        mod_file.write_text(
            "def add_numbers(a: int, b: int) -> int:\n"
            "    return a + b\n\n"
            "def divide_numbers(a: float, b: float) -> float:\n"
            "    if b == 0:\n"
            "        raise ZeroDivisionError('Division by zero')\n"
            "    return a / b\n",
            encoding="utf-8",
        )

        out_tests_dir = repo / "tests" / "generated"

        # 2. Run TestGenerationAgent with approved=True, dry_run=False
        agent = TestGenerationAgent(repo_root=repo)
        inp = TestGenerationInput(
            code_under_test=[str(mod_file.relative_to(repo))],
            coverage_gaps=[
                CoverageGap(file_path=str(mod_file.relative_to(repo)), start_line=1, end_line=6, reason="Untested math ops")
            ],
            approved=True,
            dry_run=False,
            output_dir=str(out_tests_dir),
        )
        res = agent.execute(inp)

        # 3. Assert outputs
        assert res.approval_status == "approved"
        assert res.total_tests_generated >= 3
        assert len(res.new_test_files) == 1

        tf = res.new_test_files[0]
        assert tf.written_to_disk is True
        assert Path(tf.test_file_path).exists()
        assert tf.verification_status == "passed"
        assert tf.test_runner_result is not None
        assert tf.test_runner_result.get("passed", 0) >= 1
