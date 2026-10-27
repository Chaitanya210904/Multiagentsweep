"""
Data models for the Security Agent (Layer: Safety).
Defines security vulnerabilities, severity levels, OWASP Top 10 and CVE/CWE classifications,
SAST issues, exposed secrets, dependency CVEs, configuration audits, and auth/input reviews.
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class VulnerabilitySeverity(str, Enum):
    """Standard security vulnerability severity levels based on CVSS scoring."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VulnerabilityCategory(str, Enum):
    """Classification taxonomy for security issues."""
    SAST = "sast"                       # Code flaws: injection, bad crypto, path traversal, deserialization
    SECRET = "secret"                   # Exposed secrets, tokens, credentials, private keys
    DEPENDENCY_CVE = "dependency_cve"   # Vulnerable third-party dependencies with CVE IDs
    CONFIG_MISCONFIG = "config_misconfig" # Dockerfile, Kubernetes, env, or cloud misconfigurations
    AUTH_REVIEW = "auth_review"         # Missing authentication, authorization bypass, insecure session
    INPUT_VALIDATION = "input_validation" # Unvalidated parameters, unescaped user inputs, SSRF


class SecurityVulnerability(BaseModel):
    """
    A concrete security vulnerability pinpointed to an exact file and line number,
    with explicit OWASP, CWE, or CVE taxonomy references and actionable remediation guidance.
    """
    id: str = Field(description="Unique vulnerability finding identifier, e.g. SEC-001")
    title: str = Field(description="Concise human-readable vulnerability title")
    description: str = Field(description="Detailed explanation of the vulnerability and attack vector")
    category: VulnerabilityCategory = Field(description="Vulnerability category")
    severity: VulnerabilitySeverity = Field(description="Calculated CVSS-aligned severity level")
    file_path: str = Field(description="Repository-relative file path where the issue occurs")
    line_number: int = Field(ge=1, description="1-indexed line number where the issue begins")
    column_number: Optional[int] = Field(default=None, description="1-indexed column number if available")
    end_line_number: Optional[int] = Field(default=None, description="1-indexed line number where the issue ends")
    rule_id: str = Field(description="Canonical rule ID, e.g. 'semgrep:python.sql-injection', 'gitleaks:aws-key'")
    tool_source: str = Field(description="Tool that discovered finding: 'semgrep', 'gitleaks', 'trivy', 'auth_review'")
    owasp_category: Optional[str] = Field(
        default=None,
        description="OWASP Top 10 category (e.g. 'A03:2021-Injection', 'A01:2021-Broken Access Control')",
    )
    cve_id: Optional[str] = Field(default=None, description="CVE identifier if applicable (e.g. 'CVE-2023-32681')")
    cwe_id: Optional[str] = Field(default=None, description="CWE identifier (e.g. 'CWE-89' for SQL injection)")
    cvss_score: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="CVSS v3.1 base score")
    remediation: str = Field(description="Specific, actionable steps to patch or mitigate the vulnerability")
    code_snippet: Optional[str] = Field(default=None, description="Sanitized source line or redacted secret snippet")
    is_secret: bool = Field(default=False, description="Whether this finding represents an exposed secret")


class SecurityInput(BaseModel):
    """Input payload accepted by the Security Agent."""
    changed_code: List[Union[str, Path]] = Field(
        description="List of source code files that changed or need security review",
    )
    dependency_manifests: List[Union[str, Path]] = Field(
        default_factory=list,
        description="Dependency manifest files (e.g. requirements.txt, package.json, Pipfile, pyproject.toml)",
    )
    configs: List[Union[str, Path]] = Field(
        default_factory=list,
        description="Infrastructure and deployment configs (Dockerfile, k8s.yaml, docker-compose.yml, .env)",
    )
    cve_feeds: List[Union[str, Path, Dict[str, Any]]] = Field(
        default_factory=list,
        description="Optional custom CVE feeds, vulnerability lists, or database overrides",
    )
    fail_on_severity: Optional[VulnerabilitySeverity] = Field(
        default=VulnerabilitySeverity.HIGH,
        description="Threshold at or above which the security audit fails (e.g. HIGH or CRITICAL)",
    )


class SecurityOutput(BaseModel):
    """Output payload produced by the Security Agent."""
    vulnerabilities_with_severity_and_owasp_or_cve_reference: List[SecurityVulnerability] = Field(
        default_factory=list,
        description="Pinpointed security vulnerabilities with severity, line numbers, and OWASP/CVE references",
    )
    security_score: float = Field(
        ge=0.0,
        le=100.0,
        description="Calibrated security health score from 0.0 (catastrophic) to 100.0 (secure)",
    )
    security_grade: str = Field(
        description="Security rating grade: 'A' (no high/crit), 'B', 'C', 'D', 'F' (blockers present)",
    )
    critical_count: int = Field(default=0, ge=0, description="Count of CRITICAL severity vulnerabilities")
    high_count: int = Field(default=0, ge=0, description="Count of HIGH severity vulnerabilities")
    medium_count: int = Field(default=0, ge=0, description="Count of MEDIUM severity vulnerabilities")
    low_count: int = Field(default=0, ge=0, description="Count of LOW severity vulnerabilities")
    info_count: int = Field(default=0, ge=0, description="Count of INFO severity vulnerabilities")
    passed: bool = Field(
        description="Whether the codebase passes security policy (no vulnerabilities >= fail_on_severity)",
    )
    scanned_files_count: int = Field(default=0, ge=0, description="Total number of files evaluated")
    stats: Dict[str, Any] = Field(
        default_factory=dict,
        description="Breakdown statistics by category, tool, and OWASP bucket",
    )
