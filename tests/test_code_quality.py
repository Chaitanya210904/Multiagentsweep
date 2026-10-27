"""
Comprehensive tests for Agent 9: Code Quality (Layer: Quality, Role: Maintainability checker).
Verifies:
1. Agent metadata, layer, role, read-only access enforcement
2. SonarQube tool (cognitive complexity, long functions, too many parameters, broad exceptions, duplication)
3. Ruff tool (unused imports F401, line lengths E501, style issues)
4. ESLint tool (no-var, no-eval, eqeqeq)
5. Coverage Parser tool (uncovered lines on changed files)
6. Technical debt estimation and maintainability rating (A/B/C/D/E)
7. End-to-end integration across multi-language code and test coverage reports
"""

import json
from pathlib import Path
import pytest
from tempfile import TemporaryDirectory

from agents.quality.code_quality import (
    CODE_QUALITY_METADATA,
    CodeQuality,
)
from core.exceptions import UnauthorizedAccessError
from models.code_quality import (
    CodeQualityInput,
    CodeQualityOutput,
    FindingSeverity,
    QualityFinding,
    QualityFindingCategory,
)
from storage.registry_store import CodeRegistryStore
from tools.coverage_parser import CoverageParserTool
from tools.eslint_tool import ESLintTool
from tools.ruff_tool import RuffTool
from tools.sonarqube_tool import SonarQubeTool


def test_code_quality_metadata():
    """Validates code quality agent metadata against the formal specification."""
    meta = CODE_QUALITY_METADATA
    assert meta.id == "code_quality"
    assert meta.name == "Code Quality"
    assert meta.layer == "quality"
    assert meta.role == "Maintainability checker"
    assert meta.description == "Finds complexity, duplication, smells, test coverage gaps and style issues."
    assert meta.access == "read-only"
    assert meta.model_tier == "small"
    assert "changed_files" in meta.inputs
    assert "graph_neighbors" in meta.inputs
    assert "coverage_reports" in meta.inputs
    assert "findings_with_file_and_line" in meta.outputs
    assert "sonarqube" in meta.tools
    assert "ruff" in meta.tools
    assert "eslint" in meta.tools
    assert "registry.lookup" in meta.tools
    assert meta.trigger == "on changed files"
    assert meta.optional is False


def test_read_only_access_enforcement():
    """Ensures CodeQuality strictly operates in read-only mode."""
    store = CodeRegistryStore(persistence_path=":memory:")
    agent = CodeQuality(store=store)
    agent.require_access("read-only")

    custom_meta = CODE_QUALITY_METADATA.model_copy(deep=True)
    custom_meta.access = "read-write"
    write_agent = CodeQuality(store=store, metadata=custom_meta)
    with pytest.raises(UnauthorizedAccessError):
        write_agent.require_access("read-only")


def test_sonarqube_complexity_and_smells():
    """Tests SonarQube tool detecting complexity, parameter count, and broad exceptions."""
    sonar = SonarQubeTool(max_complexity=4, max_function_lines=20, max_parameters=3)

    code = """
def complex_function(a, b, c, d, e):
    # Too many parameters (5 > 3)
    try:
        if a > 0:
            if b > 0:
                if c > 0:
                    for i in range(10):
                        print(i)
        elif a < 0:
            while b < 0:
                b += 1
    except Exception:
        # Broad exception caught without re-raising
        pass
"""
    findings = sonar.analyze_file("src/complex.py", code)

    # 1. Parameter count smell
    param_smell = next((f for f in findings if f.rule_id == "sonar:too-many-parameters"), None)
    assert param_smell is not None
    assert param_smell.line_number == 2
    assert param_smell.category == QualityFindingCategory.CODE_SMELL

    # 2. Complexity finding
    comp_finding = next((f for f in findings if f.rule_id == "sonar:cognitive-complexity"), None)
    assert comp_finding is not None
    assert comp_finding.category == QualityFindingCategory.COMPLEXITY

    # 3. Broad exception smell
    exc_smell = next((f for f in findings if f.rule_id == "sonar:no-broad-exception"), None)
    assert exc_smell is not None
    assert exc_smell.severity == FindingSeverity.CRITICAL


def test_sonarqube_duplication_detection():
    """Tests cross-file duplicate code block discovery."""
    sonar = SonarQubeTool(min_duplicate_lines=5)

    dup_block = """
total = 0
for item in items:
    if item.is_valid:
        total += item.price
return total
"""
    file1 = f"def calc_a(items):\n{dup_block}\n"
    file2 = f"def calc_b(items):\n{dup_block}\n"

    findings = sonar.detect_duplications({
        "services/service_a.py": file1,
        "services/service_b.py": file2,
    })

    assert len(findings) >= 1
    dup = findings[0]
    assert dup.category == QualityFindingCategory.DUPLICATION
    assert dup.rule_id == "sonar:duplicated-blocks"
    assert dup.file_path in ("services/service_a.py", "services/service_b.py")


def test_ruff_tool_unused_import_and_style():
    """Tests Ruff tool identifying unused imports and style violations."""
    with TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text(
            """import math
import os
import sys

def calculate():
    return math.sqrt(16)
""",
            encoding="utf-8",
        )

        ruff = RuffTool()
        findings = ruff.check_files([str(test_file)])

        # 'os' and 'sys' should be flagged as unused imports (F401)
        f401_findings = [f for f in findings if "F401" in f.rule_id]
        assert len(f401_findings) >= 2
        unused_names = [f.message for f in f401_findings]
        assert any("os" in m for m in unused_names)
        assert any("sys" in m for m in unused_names)


def test_eslint_tool_js_smells():
    """Tests ESLint tool detecting var, eval, and loose equality in JS."""
    with TemporaryDirectory() as tmpdir:
        js_file = Path(tmpdir) / "app.js"
        js_file.write_text(
            """
var userName = "Alice";
if (userName == "Alice") {
    eval("console.log(userName)");
}
""",
            encoding="utf-8",
        )

        eslint = ESLintTool()
        findings = eslint.check_files([str(js_file)])

        rule_ids = {f.rule_id for f in findings}
        assert "eslint:no-var" in rule_ids
        assert "eslint:eqeqeq" in rule_ids
        assert "eslint:no-eval" in rule_ids


def test_coverage_parser_uncovered_lines():
    """Tests coverage parser pinpointing uncovered lines in changed files."""
    cov_tool = CoverageParserTool()

    # Sample coverage.py JSON format
    cov_data = {
        "files": {
            "src/calculator.py": {
                "missing_lines": [10, 11, 12, 25, 26],
                "summary": {"num_statements": 30, "covered_lines": 25},
            },
            "src/unchanged.py": {
                "missing_lines": [5, 6, 7],
                "summary": {"num_statements": 10, "covered_lines": 7},
            },
        }
    }

    with TemporaryDirectory() as tmpdir:
        cov_file = Path(tmpdir) / "coverage.json"
        cov_file.write_text(json.dumps(cov_data), encoding="utf-8")

        summary, findings = cov_tool.parse_reports(
            reports=[cov_file],
            changed_files=["src/calculator.py"],
            repo_root=Path(tmpdir),
        )

        assert summary is not None
        assert summary.changed_files_coverage_pct > 0.0

        # Should produce findings for 10-12 and 25-26 on src/calculator.py, but not src/unchanged.py
        assert len(findings) == 2
        assert all(f.category == QualityFindingCategory.COVERAGE_GAP for f in findings)
        assert findings[0].line_number == 10
        assert findings[0].end_line_number == 12
        assert findings[1].line_number == 25
        assert findings[1].end_line_number == 26


def test_end_to_end_code_quality_audit():
    """
    End-to-end integration test for Code Quality Agent:
    Audits a workspace containing complexity, smells, style issues, and test coverage gaps.
    Verifies maintainability rating, technical debt, and pinpointed file:line findings.
    """
    store = CodeRegistryStore(persistence_path=":memory:")

    with TemporaryDirectory() as tmpdir:
        py_file = Path(tmpdir) / "user_service.py"
        py_file.write_text(
            """import os
import sys

def process_transaction(user_id, amount, currency, account_type, is_priority, promo_code):
    # Too many parameters (> 5)
    try:
        if amount > 1000:
            if currency == "USD":
                return amount * 1.05
    except Exception:
        pass
    return amount
""",
            encoding="utf-8",
        )

        cov_file = Path(tmpdir) / "coverage.json"
        cov_data = {
            "files": {
                "user_service.py": {
                    "missing_lines": [10, 11, 12],
                    "summary": {"num_statements": 15, "covered_lines": 12},
                }
            }
        }
        cov_file.write_text(json.dumps(cov_data), encoding="utf-8")

        cq = CodeQuality(store=store, repo_root=tmpdir)
        output = cq.execute(
            CodeQualityInput(
                changed_files=[py_file],
                coverage_reports=[cov_file],
                max_parameters=5,
            )
        )

        assert len(output.findings_with_file_and_line) > 0
        assert output.technical_debt_minutes > 0
        assert output.maintainability_rating in ("A", "B", "C", "D", "E")

        # Verify findings categories present
        cats = {f.category for f in output.findings_with_file_and_line}
        assert QualityFindingCategory.CODE_SMELL in cats
        assert QualityFindingCategory.COVERAGE_GAP in cats

        # Verify all findings have valid line numbers >= 1
        for f in output.findings_with_file_and_line:
            assert f.line_number >= 1
            assert f.rule_id != ""
            assert f.remediation != ""
