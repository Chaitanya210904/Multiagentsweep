"""
Comprehensive tests for Agent 10: Security (Layer: Safety).
Validates:
- Metadata compliance (id, name, layer, role, access, model_tier, inputs, outputs, tools, trigger)
- Strict read-only access enforcement (UnauthorizedAccessError)
- Semgrep SAST detection: SQLi, Command Injection, Insecure Deserialization, eval/exec, weak crypto
- Auth & input review: missing authentication decorators on state-changing endpoints
- Gitleaks secret scanner: AWS keys, GitHub tokens, Slack tokens, DB connection strings, and snippet redaction
- Trivy dependency CVE auditor: Python requirements.txt, Node.js package.json, version comparison
- Trivy config auditor: Dockerfile root user, unpinned tags, exposed SSH port, K8s privileged mode
- End-to-end security audit and score/grade calculation
"""

from pathlib import Path
import tempfile
import pytest

from agents.safety.security_agent import SECURITY_METADATA, SecurityAgent
from core.exceptions import UnauthorizedAccessError
from models.security import (
    SecurityInput,
    SecurityOutput,
    SecurityVulnerability,
    VulnerabilityCategory,
    VulnerabilitySeverity,
)
from storage.registry_store import CodeRegistryStore
from tools.gitleaks_tool import GitleaksTool
from tools.semgrep_tool import SemgrepTool
from tools.trivy_tool import TrivyTool


def test_security_metadata():
    """Validates Agent 10 metadata specification against system architecture roadmap."""
    meta = SECURITY_METADATA
    assert meta.id == "security"
    assert meta.name == "Security"
    assert meta.layer == "safety"
    assert meta.role == "Vulnerability scanner"
    assert meta.access == "read-only"
    assert meta.model_tier == "medium"
    assert "changed_code" in meta.inputs
    assert "dependency_manifests" in meta.inputs
    assert "configs" in meta.inputs
    assert "cve_feeds" in meta.inputs
    assert "vulnerabilities_with_severity_and_owasp_or_cve_reference" in meta.outputs
    assert set(meta.tools) == {"semgrep", "trivy", "gitleaks", "registry.lookup"}
    assert meta.trigger == "on changed code or dependencies"
    assert meta.optional is False


def test_read_only_access_enforcement():
    """Ensures agent execution strictly rejects non-read-only access permissions."""
    agent = SecurityAgent()
    agent.metadata.access = "read-write"

    payload = SecurityInput(changed_code=["app.py"])
    with pytest.raises(UnauthorizedAccessError) as exc_info:
        agent.execute(payload)

    assert "read-only" in str(exc_info.value)


def test_semgrep_sast_sql_and_command_injection():
    """Tests SAST detection for SQL injection, command injection, and deserialization flaws."""
    tool = SemgrepTool(use_cli_if_available=False)

    code = """
import os
import pickle
import hashlib

def get_user_data(cursor, user_id):
    # Vulnerability 1: SQL Injection via f-string
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    cursor.execute(query)

def run_backup(folder_name):
    # Vulnerability 2: Command Injection
    os.system("tar -czf backup.tar.gz " + folder_name)

def load_payload(raw_data):
    # Vulnerability 3: Insecure Deserialization
    return pickle.loads(raw_data)

def hash_secret(secret):
    # Vulnerability 4: Weak Cryptographic Hashing
    return hashlib.md5(secret.encode()).hexdigest()
"""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = f.name

    try:
        findings = tool.scan_files([f_path], repo_root=str(Path(f_path).parent))
        rule_ids = {item.rule_id for item in findings}

        assert "semgrep:python.sql-injection" in rule_ids
        assert "semgrep:python.command-injection" in rule_ids
        assert "semgrep:python.insecure-pickle" in rule_ids
        assert "semgrep:python.weak-hash-algorithm" in rule_ids

        # Verify SQLi details
        sqli = next(item for item in findings if item.rule_id == "semgrep:python.sql-injection")
        assert sqli.severity == VulnerabilitySeverity.CRITICAL
        assert sqli.cwe_id == "CWE-89"
        assert sqli.owasp_category == "A03:2021-Injection"
        assert sqli.line_number > 0
    finally:
        Path(f_path).unlink(missing_ok=True)


def test_semgrep_missing_auth_review():
    """Tests detection of state-changing routes lacking authentication decorators."""
    tool = SemgrepTool(use_cli_if_available=False)

    code = """
from flask import Flask, request

app = Flask(__name__)

def login_required(f):
    return f

# Vulnerable: State-changing endpoint without authentication
@app.route("/api/user/delete", methods=["POST"])
def delete_user():
    return {"status": "deleted"}

# Secure: Has login_required decorator
@app.route("/api/user/update", methods=["POST"])
@login_required
def update_user():
    return {"status": "updated"}
"""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = f.name

    try:
        findings = tool.scan_files([f_path], repo_root=str(Path(f_path).parent))
        auth_findings = [item for item in findings if item.rule_id == "semgrep:python.missing-endpoint-auth"]

        assert len(auth_findings) == 1
        assert "delete_user" in auth_findings[0].description
        assert auth_findings[0].severity == VulnerabilitySeverity.HIGH
        assert auth_findings[0].cwe_id == "CWE-306"
    finally:
        Path(f_path).unlink(missing_ok=True)


def test_gitleaks_secret_detection_and_redaction():
    """Tests secret detection, credential extraction, and snippet redaction."""
    tool = GitleaksTool(use_cli_if_available=False)

    code = """
# Real credential patterns
AWS_KEY = "AKIA1234567890ABCDEF"
GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
SLACK_TOKEN = "xoxb-123456789012-1234567890123-abcdef123456"
DB_CONN = "postgres://dbadmin:SuperSecretP@ss99@db.production.internal:5432/app"
"""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        f_path = f.name

    try:
        findings = tool.scan_files([f_path], repo_root=str(Path(f_path).parent))
        rule_ids = {item.rule_id for item in findings}

        assert "gitleaks:aws-access-key-id" in rule_ids
        assert "gitleaks:github-pat" in rule_ids
        assert "gitleaks:slack-token" in rule_ids
        assert "gitleaks:database-connection-url" in rule_ids

        # Ensure all are categorized as SECRET and CRITICAL/HIGH
        for item in findings:
            assert item.category == VulnerabilityCategory.SECRET
            assert item.is_secret is True
            # Verify redaction: full secret must NOT be in snippet
            assert "AKIA1234567890ABCDEF" not in item.code_snippet
            assert "*" in item.code_snippet
    finally:
        Path(f_path).unlink(missing_ok=True)


def test_trivy_dependency_manifest_cve_scan():
    """Tests auditing requirements.txt and package.json for known package CVEs."""
    tool = TrivyTool(use_cli_if_available=False)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        req_file = tmp_path / "requirements.txt"
        req_file.write_text(
            "requests==2.28.1\n"
            "urllib3==1.26.15\n"
            "cryptography==41.0.1\n"
            "safe-pkg==1.0.0\n"
        )

        pkg_file = tmp_path / "package.json"
        pkg_file.write_text("""{
            "dependencies": {
                "lodash": "4.17.20",
                "express": "4.18.1"
            }
        }""")

        findings = tool.scan_manifests_and_configs(
            manifest_paths=[str(req_file), str(pkg_file)],
            config_paths=[],
            repo_root=tmp_dir,
        )

        cve_ids = {item.cve_id for item in findings if item.cve_id}
        assert "CVE-2023-32681" in cve_ids  # requests < 2.31.0
        assert "CVE-2023-45803" in cve_ids  # urllib3 < 1.26.18
        assert "CVE-2021-23337" in cve_ids  # lodash < 4.17.21
        assert "CVE-2024-29041" in cve_ids  # express < 4.19.2


def test_trivy_dockerfile_and_k8s_config_misconfigs():
    """Tests container and Kubernetes infrastructure misconfiguration auditing."""
    tool = TrivyTool(use_cli_if_available=False)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM python:latest\n"
            "EXPOSE 22\n"
            "CMD ['python', 'app.py']\n"
        )

        k8s_yaml = tmp_path / "deployment.k8s.yaml"
        k8s_yaml.write_text(
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: web\n"
            "        securityContext:\n"
            "          privileged: true\n"
        )

        findings = tool.scan_manifests_and_configs(
            manifest_paths=[],
            config_paths=[str(dockerfile), str(k8s_yaml)],
            repo_root=tmp_dir,
        )

        rule_ids = {item.rule_id for item in findings}
        assert "trivy:docker.unpinned-base-image" in rule_ids
        assert "trivy:docker.ssh-port-exposed" in rule_ids
        assert "trivy:docker.runs-as-root" in rule_ids
        assert "trivy:k8s.privileged-container" in rule_ids


def test_end_to_end_security_audit():
    """Runs end-to-end security audit pipeline across code, manifests, and configs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 1. Source code with vulnerability & secret
        app_code = tmp_path / "app.py"
        app_code.write_text(
            "import os\n"
            "api_key = 'dummy_secret_auth_token_for_test_only'\n"
            "def run_cmd(cmd):\n"
            "    os.system(cmd)\n"
        )

        # 2. Vulnerable manifest
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==2.28.1\n")

        # 3. Dockerfile
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM alpine:latest\n")

        agent = SecurityAgent(repo_root=tmp_path)
        inp = SecurityInput(
            changed_code=[app_code],
            dependency_manifests=[req_file],
            configs=[dockerfile],
            fail_on_severity=VulnerabilitySeverity.HIGH,
        )

        out = agent.execute(inp)

        assert isinstance(out, SecurityOutput)
        assert len(out.vulnerabilities_with_severity_and_owasp_or_cve_reference) >= 3
        assert out.critical_count >= 1  # OS command injection
        assert out.high_count >= 1      # Leaked API key or root Docker
        assert out.passed is False      # Fails because critical/high present
        assert out.security_grade in ("D", "F")
        assert out.security_score < 70.0
