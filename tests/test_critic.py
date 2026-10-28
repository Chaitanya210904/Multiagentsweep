"""
Tests for Result Aggregator and Critic Agent (Layer: Control).
Verifies finding normalization, false alarm pruning, duplicate suppression,
conflict resolution, impact score ranking, and health score synthesis.
"""

from pathlib import Path
import pytest

from agents.control.critic import CRITIC_METADATA, ResultAggregatorCriticAgent
from models.code_quality import QualityFinding, CodeQualityOutput
from models.company_rules import CompanyRulesOutput, RuleCategory, RuleSeverity, RuleViolation
from models.control import FindingCategory, NormalizedSeverity
from models.security import (
    SecurityOutput,
    SecurityVulnerability,
    VulnerabilityCategory,
    VulnerabilitySeverity,
)


def test_critic_metadata():
    """Validates Critic agent metadata specifications."""
    meta = CRITIC_METADATA
    assert meta.id == "result_aggregator_critic"
    assert meta.name == "Result Aggregation & Critic"
    assert meta.layer == "control"
    assert meta.role == "Consolidator & Quality Gate"
    assert meta.access == "read-only"
    assert meta.model_tier == "medium"
    assert "specialist_outputs" in meta.inputs
    assert "unified_report" in meta.outputs
    assert "critic.deduplicate" in meta.tools


def test_critic_normalizes_heterogeneous_specialist_findings(tmp_path):
    """Verifies Critic translates diverse agent findings into unified CriticFinding models."""
    critic = ResultAggregatorCriticAgent(repo_root=str(tmp_path))

    # Sample security finding
    sec_vuln = SecurityVulnerability(
        id="vuln_1",
        title="SQL Injection Vulnerability",
        description="User input directly concatenated into SQL query",
        category=VulnerabilityCategory.SAST,
        severity=VulnerabilitySeverity.HIGH,
        rule_id="semgrep:python.sql-injection",
        tool_source="semgrep",
        cwe_id="CWE-89",
        owasp_category="A03:2021-Injection",
        file_path="src/user_api.py",
        line_number=42,
        code_snippet="cursor.execute('SELECT * FROM users WHERE id = ' + user_id)",
        remediation="Use parameterized queries.",
        confidence=0.95,
    )
    sec_out = SecurityOutput(
        vulnerabilities=[sec_vuln],
        vulnerabilities_with_severity_and_owasp_or_cve_reference=[sec_vuln],
        security_score=75.0,
        security_grade="C",
        critical_count=0,
        high_count=1,
        medium_count=0,
        low_count=0,
        info_count=0,
        passed=False,
    )

    # Sample company rules finding
    rule_viol = RuleViolation(
        violation_id="viol_1",
        rule_id="RULE-SEC-001",
        rule_title="No Hardcoded Secrets",
        severity=RuleSeverity.CRITICAL,
        category=RuleCategory.SECURITY,
        file_path="src/config.py",
        line_number=10,
        code_snippet="api_key = 'abcdef123'",
        infraction_message="API key hardcoded",
        remediation="Use env vars.",
    )
    rules_out = CompanyRulesOutput(
        violations=[rule_viol],
        compliance_score=85.0,
        rules_checked_count=5,
        files_scanned_count=2,
        passed=False,
        critical_count=1,
        high_count=0,
        medium_count=0,
        low_count=0,
        info_count=0,
        summary="Policy violated",
    )

    # Create dummy files so they aren't marked as non-existent
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "user_api.py").write_text("cursor.execute(...)", encoding="utf-8")
    (tmp_path / "src" / "config.py").write_text("api_key = 'abcdef123'", encoding="utf-8")

    report = critic.execute({
        "specialist_outputs": {
            "security": sec_out,
            "company_rules": rules_out,
        },
        "target_files": ["src/user_api.py", "src/config.py"],
    })

    assert report.total_findings_detected == 2
    assert report.active_findings_count == 2
    assert report.false_alarms_pruned == 0
    assert report.critical_count == 1
    assert report.high_count == 1

    # Verify normalization
    categories = {f.category for f in report.ranked_findings}
    assert FindingCategory.SECURITY in categories
    assert FindingCategory.POLICY_COMPLIANCE in categories


def test_critic_prunes_overlapping_duplicate_findings(tmp_path):
    """Verifies that duplicate findings on the exact same file and line are pruned."""
    critic = ResultAggregatorCriticAgent(repo_root=str(tmp_path))

    # Real file
    test_file = tmp_path / "auth.py"
    test_file.write_text("password = 'SecretPassword123'\n", encoding="utf-8")

    # Finding from Security
    sec_vuln = SecurityVulnerability(
        id="vuln_sec",
        title="Hardcoded Password Detected",
        description="Plaintext password in configuration",
        category=VulnerabilityCategory.SECRET,
        severity=VulnerabilitySeverity.HIGH,
        rule_id="gitleaks:generic-api-key",
        tool_source="gitleaks",
        cwe_id="CWE-798",
        file_path=str(test_file),
        line_number=1,
        code_snippet="password = 'SecretPassword123'",
        remediation="Use Vault.",
        confidence=0.99,
        is_secret=True,
    )
    sec_out = SecurityOutput(
        vulnerabilities=[sec_vuln],
        vulnerabilities_with_severity_and_owasp_or_cve_reference=[sec_vuln],
        security_score=70.0,
        security_grade="C",
        critical_count=0,
        high_count=1,
        medium_count=0,
        low_count=0,
        info_count=0,
        passed=False,
    )

    # Overlapping finding from Company Rules on the exact same line
    rule_viol = RuleViolation(
        violation_id="viol_rule",
        rule_id="RULE-SEC-001",
        rule_title="Prohibit Hardcoded Credentials",
        severity=RuleSeverity.HIGH,
        category=RuleCategory.SECURITY,
        file_path=str(test_file),
        line_number=1,
        code_snippet="password = 'SecretPassword123'",
        infraction_message="Password variable hardcoded",
        remediation="Store in vault.",
    )
    rules_out = CompanyRulesOutput(
        violations=[rule_viol],
        compliance_score=75.0,
        rules_checked_count=5,
        files_scanned_count=1,
        passed=False,
        critical_count=0,
        high_count=1,
        medium_count=0,
        low_count=0,
        info_count=0,
        summary="Policy violated",
    )

    report = critic.execute({
        "specialist_outputs": {
            "security": sec_out,
            "company_rules": rules_out,
        },
    })

    assert report.total_findings_detected == 2
    assert report.false_alarms_pruned == 1  # Exactly 1 duplicate pruned!
    assert report.active_findings_count == 1
    assert len(report.pruned_findings) == 1
    assert "duplicate" in report.pruned_findings[0].suppression_reason.lower()


def test_critic_prunes_stale_findings_for_nonexistent_files(tmp_path):
    """Verifies that findings targeting files that do not exist are pruned as false alarms."""
    critic = ResultAggregatorCriticAgent(repo_root=str(tmp_path))

    # Point to a deleted / non-existent file
    sec_vuln = SecurityVulnerability(
        id="vuln_deleted",
        title="SQL Injection in Deleted File",
        description="Command injection in deleted file",
        category=VulnerabilityCategory.SAST,
        severity=VulnerabilitySeverity.CRITICAL,
        rule_id="semgrep:python.eval-injection",
        tool_source="semgrep",
        cwe_id="CWE-89",
        file_path="src/deleted_legacy_controller.py",
        line_number=15,
        code_snippet="eval(cmd)",
        remediation="Fix it.",
        confidence=0.9,
    )
    sec_out = SecurityOutput(
        vulnerabilities=[sec_vuln],
        vulnerabilities_with_severity_and_owasp_or_cve_reference=[sec_vuln],
        security_score=50.0,
        security_grade="F",
        critical_count=1,
        high_count=0,
        medium_count=0,
        low_count=0,
        info_count=0,
        passed=False,
    )

    report = critic.execute({
        "specialist_outputs": {"security": sec_out},
    })

    assert report.total_findings_detected == 1
    assert report.false_alarms_pruned == 1
    assert report.active_findings_count == 0
    assert "no longer exists" in report.pruned_findings[0].suppression_reason


def test_critic_ranks_findings_by_impact_score(tmp_path):
    """Verifies that active findings are sorted descending by composite impact score."""
    critic = ResultAggregatorCriticAgent(repo_root=str(tmp_path))

    f1 = tmp_path / "low_issue.py"
    f1.write_text("x = 1\n", encoding="utf-8")
    f2 = tmp_path / "crit_issue.py"
    f2.write_text("x = 2\n", encoding="utf-8")

    # Critical security vuln
    v_crit = SecurityVulnerability(
        id="vuln_crit",
        title="Critical Vulnerability",
        description="OS command injection via unsanitized input",
        category=VulnerabilityCategory.SAST,
        severity=VulnerabilitySeverity.CRITICAL,
        rule_id="semgrep:python.os-system",
        tool_source="semgrep",
        cwe_id="CWE-78",
        file_path=str(f2),
        line_number=1,
        code_snippet="os.system(cmd)",
        remediation="Use subprocess.",
        confidence=1.0,
    )
    # Low security issue
    v_low = SecurityVulnerability(
        id="vuln_low",
        title="Low Informational Notice",
        description="Debug print statement left in production",
        category=VulnerabilityCategory.SAST,
        severity=VulnerabilitySeverity.LOW,
        rule_id="semgrep:python.debug-print",
        tool_source="semgrep",
        cwe_id="CWE-200",
        file_path=str(f1),
        line_number=1,
        code_snippet="print(x)",
        remediation="Clean up debug print.",
        confidence=0.8,
    )

    sec_out = SecurityOutput(
        vulnerabilities=[v_low, v_crit],
        vulnerabilities_with_severity_and_owasp_or_cve_reference=[v_low, v_crit],
        security_score=80.0,
        security_grade="B",
        critical_count=1,
        high_count=0,
        medium_count=0,
        low_count=1,
        info_count=0,
        passed=False,
    )

    report = critic.execute({
        "specialist_outputs": {"security": sec_out},
    })

    assert len(report.ranked_findings) == 2
    # Critical item must be ranked #1
    assert report.ranked_findings[0].title == "Critical Vulnerability"
    assert report.ranked_findings[0].impact_score > report.ranked_findings[1].impact_score
