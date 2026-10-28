"""
Tests for Company Rules Agent (Layer: Safety).
Verifies rule document parsing, rule ID citation, line-number pinpointing,
severity classification, compliance score calculation, and read-only access control.
"""

from pathlib import Path
import pytest

from agents.safety.company_rules_agent import (
    COMPANY_RULES_METADATA,
    CompanyRulesAgent,
)
from core.exceptions import UnauthorizedAccessError
from models.company_rules import (
    CompanyRuleDefinition,
    CompanyRulesInput,
    RuleCategory,
    RuleSeverity,
)
from models.registry import NodeLocation, NodeType, RegistryNode
from storage.registry_store import CodeRegistryStore
from tools.rule_evaluator_tool import RuleEvaluatorTool
from tools.rule_parser_tool import RuleParserTool


def test_company_rules_metadata():
    """Validates metadata specification according to multi-agent architecture."""
    meta = COMPANY_RULES_METADATA
    assert meta.id == "company_rules"
    assert meta.name == "Company Rules"
    assert meta.layer == "safety"
    assert meta.role == "Rule compliance checker"
    assert meta.access == "read-only"
    assert meta.model_tier == "small"
    assert "changed_files" in meta.inputs
    assert "rule_files" in meta.inputs
    assert "violations" in meta.outputs
    assert "compliance_score" in meta.outputs
    assert "rules.parse" in meta.tools
    assert "rules.evaluate" in meta.tools
    assert meta.optional is False


def test_read_only_access_enforcement():
    """Ensures company_rules agent cannot perform registry mutations."""
    agent = CompanyRulesAgent()
    assert agent.access == "read-only"

    # Must raise UnauthorizedAccessError when mutation is requested
    with pytest.raises(UnauthorizedAccessError):
        agent.require_access("registry-write")


def test_rule_parser_tool_default_enterprise_rules():
    """Verifies parsing default enterprise policy rules."""
    parser = RuleParserTool()
    rules = parser.parse_rules()

    assert len(rules) >= 7
    rule_ids = {r.rule_id for r in rules}
    assert "RULE-SEC-001" in rule_ids  # Secrets
    assert "RULE-SEC-002" in rule_ids  # eval/exec
    assert "RULE-ARCH-001" in rule_ids # Direct SQL in API
    assert "RULE-PRIV-001" in rule_ids # PII logging
    assert "RULE-NAME-001" in rule_ids # Snake case
    assert "RULE-DEP-001" in rule_ids  # Insecure modules


def test_rule_parser_tool_custom_markdown_and_json(tmp_path):
    """Verifies parsing custom policy documents from Markdown and JSON."""
    parser = RuleParserTool()

    md_content = """# Company Security & Architecture Policy
## RULE-CUSTOM-001: Prohibit Plaintext Passwords [CRITICAL]
Category: security
Severity: critical
Description: Password variables must not be hardcoded.
Pattern: password\\s*=\\s*['"][^'"]+['"]
Files: *.py, *.js
Remediation: Store in secret vault.

## RULE-CUSTOM-002: Service Layer Requirement [HIGH]
Category: architecture
Severity: high
Description: Controllers must call service classes.
Pattern: def handle_request
Files: *controller*
Remediation: Delegate business logic to services.
"""
    policy_file = tmp_path / "company_policy.md"
    policy_file.write_text(md_content, encoding="utf-8")

    parsed = parser.parse_rules(rule_files_or_texts=[str(policy_file)])
    assert len(parsed) >= 2
    rule_map = {r.rule_id: r for r in parsed}

    assert "RULE-CUSTOM-001" in rule_map
    assert rule_map["RULE-CUSTOM-001"].severity == RuleSeverity.CRITICAL
    assert rule_map["RULE-CUSTOM-001"].category == RuleCategory.SECURITY

    assert "RULE-CUSTOM-002" in rule_map
    assert rule_map["RULE-CUSTOM-002"].severity == RuleSeverity.HIGH
    assert rule_map["RULE-CUSTOM-002"].category == RuleCategory.ARCHITECTURE


def test_rule_evaluator_tool_detects_violations_with_line_numbers(tmp_path):
    """Verifies RuleEvaluatorTool matches patterns and extracts exact line numbers."""
    evaluator = RuleEvaluatorTool()

    code_content = """import os

def calculateTotal():
    # Line 4 has a hardcoded secret
    api_key = "abcdef1234567890"
    
    # Line 7 has dangerous eval
    result = eval("2 + 2")
    return result
"""
    src_file = tmp_path / "service.py"
    src_file.write_text(code_content, encoding="utf-8")

    rules = [
        CompanyRuleDefinition(
            rule_id="RULE-SEC-001",
            title="No Hardcoded Secrets",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            description="API keys must not be hardcoded.",
            pattern=r'api_key\s*=\s*["\'][A-Za-z0-9]{8,}["\']',
            remediation="Use env vars.",
        ),
        CompanyRuleDefinition(
            rule_id="RULE-SEC-002",
            title="No Dangerous Eval",
            category=RuleCategory.SECURITY,
            severity=RuleSeverity.CRITICAL,
            description="Do not use eval.",
            pattern=r'\beval\s*\(',
            remediation="Use safe parser.",
        ),
        CompanyRuleDefinition(
            rule_id="RULE-NAME-001",
            title="Enforce Snake Case",
            category=RuleCategory.NAMING,
            severity=RuleSeverity.MEDIUM,
            description="Use snake_case for functions.",
            pattern=r'def\s+[a-z]+[A-Z][a-zA-Z0-9]*\s*\(',
            remediation="Rename to snake_case.",
        ),
    ]

    violations, score, passed, counts = evaluator.evaluate_rules(
        files=[str(src_file)],
        rules=rules,
        fail_on_severity=RuleSeverity.HIGH,
        repo_root=str(tmp_path),
    )

    assert len(violations) == 3
    assert counts[RuleSeverity.CRITICAL.value] == 2
    assert counts[RuleSeverity.MEDIUM.value] == 1
    assert passed is False  # Because critical violations exist

    # Check line numbers and cited rule IDs
    rule_ids = {v.rule_id: v for v in violations}
    assert "RULE-SEC-001" in rule_ids
    assert rule_ids["RULE-SEC-001"].line_number == 5
    assert 'api_key = "abcdef1234567890"' in rule_ids["RULE-SEC-001"].code_snippet

    assert "RULE-SEC-002" in rule_ids
    assert rule_ids["RULE-SEC-002"].line_number == 8

    assert "RULE-NAME-001" in rule_ids
    assert rule_ids["RULE-NAME-001"].line_number == 3


def test_compliance_score_and_severity_breakdown(tmp_path):
    """Verifies compliance score degrades based on severity penalties."""
    evaluator = RuleEvaluatorTool()

    # Clean file
    clean_code = "def clean_function():\n    return 42\n"
    clean_file = tmp_path / "clean.py"
    clean_file.write_text(clean_code, encoding="utf-8")

    rules = [
        CompanyRuleDefinition(
            rule_id="RULE-SEC-001",
            title="Secrets",
            severity=RuleSeverity.CRITICAL,
            description="No secrets",
            pattern=r"secret_key\s*=",
            remediation="fix",
        )
    ]

    violations, score, passed, counts = evaluator.evaluate_rules(
        files=[str(clean_file)],
        rules=rules,
        fail_on_severity=RuleSeverity.HIGH,
    )
    assert len(violations) == 0
    assert score == 100.0
    assert passed is True


def test_company_rules_agent_enrichment_with_registry(tmp_path):
    """Ensures agent enriches findings with Registry Keeper code node context."""
    store = CodeRegistryStore()
    node = RegistryNode(
        id="file:auth_handler.py",
        name="auth_handler.py",
        type=NodeType.FILE,
        location=NodeLocation(path="auth_handler.py", start_line=1, end_line=20),
        signature="auth_handler.py",
        hash="test_hash_123",
        summary="Authentication Controller",
    )
    store.write_node(node, access_token="registry-write", source_agent="test")

    agent = CompanyRulesAgent(registry_store=store, repo_root=str(tmp_path))

    bad_code = "import os\n\ndef login():\n    password = 'HardcodedPassword123'\n    return True\n"
    target_file = tmp_path / "auth_handler.py"
    target_file.write_text(bad_code, encoding="utf-8")

    out = agent.execute(CompanyRulesInput(
        changed_files=["auth_handler.py"],
        repo_root=str(tmp_path),
    ))

    assert len(out.violations) >= 1
    # Check that context from registry was enriched
    viol = next(v for v in out.violations if v.rule_id == "RULE-SEC-001")
    assert "file:auth_handler.py" in viol.infraction_message


def test_end_to_end_company_rules_audit(tmp_path):
    """End-to-end integration test of Company Rules pipeline."""
    agent = CompanyRulesAgent(repo_root=str(tmp_path))

    policy_md = """## RULE-POLICY-010: Prohibit Raw SQL Queries [HIGH]
Category: architecture
Severity: high
Description: No raw SQL in controllers.
Pattern: SELECT\\s+.+\\s+FROM
Files: *.py
Remediation: Use ORM models.
"""
    policy_file = tmp_path / "policy.md"
    policy_file.write_text(policy_md, encoding="utf-8")

    code_file = tmp_path / "app.py"
    code_file.write_text("def get_users():\n    query = 'SELECT * FROM users'\n    return query\n", encoding="utf-8")

    out = agent.execute(CompanyRulesInput(
        changed_files=["app.py"],
        rule_files=[str(policy_file)],
        repo_root=str(tmp_path),
        fail_on_severity=RuleSeverity.HIGH,
    ))

    assert out.rules_checked_count >= 1
    assert out.files_scanned_count == 1
    assert len(out.violations) >= 1
    assert out.passed is False
    assert out.high_count >= 1

    # Check cited rule ID
    v = out.violations[0]
    assert v.rule_id == "RULE-POLICY-010"
    assert v.line_number == 2
    assert "policy" in out.summary.lower()
