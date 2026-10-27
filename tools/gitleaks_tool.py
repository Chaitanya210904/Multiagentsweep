"""
Tool: gitleaks
Performs automated secret detection across source files, configs, and environment files.
Supports invoking the official Gitleaks CLI when installed, with an advanced built-in
regex pattern and Shannon entropy analysis engine fallback.
Detects:
- AWS Access Keys & Secrets
- GitHub Personal Access Tokens
- Private Keys (RSA, OpenSSH, PGP)
- Slack Bot & User Tokens
- Stripe API Keys
- Database Connection Strings with Passwords
- Hardcoded Passwords and High-Entropy API Keys
- JWT Authentication Tokens
"""

import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from models.security import SecurityVulnerability, VulnerabilityCategory, VulnerabilitySeverity


class GitleaksTool:
    """Tool: gitleaks - Automated secret and credential detection engine."""

    name = "gitleaks"
    description = (
        "Scans source code and configs for hardcoded credentials, API keys, "
        "tokens, private keys, and high-entropy secrets (CWE-798)."
    )

    # Curated regex rules matching Gitleaks standard rulebook
    SECRET_RULES: List[Dict[str, Any]] = [
        {
            "id": "aws-access-key-id",
            "title": "AWS Access Key ID",
            "pattern": re.compile(r"\b((?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{16})\b"),
            "severity": VulnerabilitySeverity.CRITICAL,
            "cwe": "CWE-798",
            "remediation": "Revoke AWS IAM key immediately and migrate to IAM Roles or AWS Secrets Manager.",
        },
        {
            "id": "github-pat",
            "title": "GitHub Personal Access Token",
            "pattern": re.compile(r"\b(gh[pous]_[A-Za-z0-9_]{36,255}|github_pat_[A-Za-z0-9_]{82})\b"),
            "severity": VulnerabilitySeverity.CRITICAL,
            "cwe": "CWE-798",
            "remediation": "Revoke token from GitHub Developer Settings and use environment variables.",
        },
        {
            "id": "private-key",
            "title": "Unencrypted Private Key Block",
            "pattern": re.compile(r"-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----"),
            "severity": VulnerabilitySeverity.CRITICAL,
            "cwe": "CWE-312",
            "remediation": "Remove private key from source control immediately and rotate key pairs.",
        },
        {
            "id": "slack-token",
            "title": "Slack API Token",
            "pattern": re.compile(r"\b(xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*)\b"),
            "severity": VulnerabilitySeverity.HIGH,
            "cwe": "CWE-798",
            "remediation": "Revoke Slack token in Slack App Management and inject via secret manager.",
        },
        {
            "id": "stripe-api-key",
            "title": "Stripe API Key",
            "pattern": re.compile(r"\b(?:sk|pk)_(?:live|test)_[0-9a-zA-Z]{24,34}\b"),
            "severity": VulnerabilitySeverity.HIGH,
            "cwe": "CWE-798",
            "remediation": "Rotate Stripe API key from Stripe Dashboard and load via runtime environment.",
        },
        {
            "id": "database-connection-url",
            "title": "Database Connection String with Embedded Password",
            "pattern": re.compile(r"\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis)://[^:\s]+:([^@\s]+)@[^/\s]+"),
            "severity": VulnerabilitySeverity.CRITICAL,
            "cwe": "CWE-798",
            "remediation": "Extract database credentials into environment variables or use IAM database auth.",
        },
        {
            "id": "jwt-token",
            "title": "Hardcoded JSON Web Token (JWT)",
            "pattern": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
            "severity": VulnerabilitySeverity.HIGH,
            "cwe": "CWE-798",
            "remediation": "Do not hardcode JWT tokens in source code; retrieve via OAuth authentication flow.",
        },
        {
            "id": "generic-secret-assignment",
            "title": "Hardcoded Credential / Secret Variable",
            "pattern": re.compile(
                r"""(?i)\b(?:api_key|apikey|secret_key|client_secret|auth_token|access_token|password|passwd|private_token)\s*[:=]\s*['"]([A-Za-z0-9_\-+/]{16,})['"]"""
            ),
            "severity": VulnerabilitySeverity.HIGH,
            "cwe": "CWE-798",
            "remediation": "Store secrets in an external secrets manager or `.env` file excluded via `.gitignore`.",
        },
    ]

    def __init__(self, use_cli_if_available: bool = True):
        self.use_cli_if_available = use_cli_if_available
        self._has_cli = bool(shutil.which("gitleaks")) if use_cli_if_available else False

    def scan_files(self, file_paths: List[str], repo_root: Optional[str] = None) -> List[SecurityVulnerability]:
        """Scans the given files for leaked credentials and secrets."""
        vulnerabilities: List[SecurityVulnerability] = []
        root = Path(repo_root) if repo_root else Path.cwd()

        if self._has_cli and file_paths:
            cli_res = self._run_gitleaks_cli(file_paths, root)
            if cli_res is not None:
                return cli_res

        # Fallback to internal secret rule engine
        for f in file_paths:
            p = Path(f) if Path(f).is_absolute() else root / f
            if not p.is_file():
                continue
            rel_path = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            vulnerabilities.extend(self._scan_content(rel_path, content))

        return vulnerabilities

    def _run_gitleaks_cli(self, file_paths: List[str], root: Path) -> Optional[List[SecurityVulnerability]]:
        """Invokes official gitleaks CLI if available."""
        try:
            report_file = root / ".gitleaks_report.json"
            cmd = ["gitleaks", "detect", "--no-git", "--report-format", "json", "--report-path", str(report_file)]
            subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
            if report_file.exists():
                try:
                    data = json.loads(report_file.read_text(encoding="utf-8"))
                    findings: List[SecurityVulnerability] = []
                    for idx, item in enumerate(data, start=1):
                        rule = item.get("RuleID", "gitleaks-secret")
                        path_str = item.get("File", "")
                        line_num = item.get("StartLine", 1)
                        secret_val = item.get("Secret", "")
                        redacted = self._redact_secret(secret_val)
                        findings.append(
                            SecurityVulnerability(
                                id=f"SEC-LEAK-{idx:03d}",
                                title=f"Exposed Secret: {item.get('Description', rule)}",
                                description=f"Gitleaks detected hardcoded secret matching rule `{rule}`.",
                                category=VulnerabilityCategory.SECRET,
                                severity=VulnerabilitySeverity.CRITICAL,
                                file_path=path_str,
                                line_number=line_num,
                                rule_id=f"gitleaks:{rule}",
                                tool_source="gitleaks",
                                owasp_category="A07:2021-Identification and Authentication Failures",
                                cwe_id="CWE-798",
                                cvss_score=9.1,
                                remediation="Revoke the exposed secret immediately and store credentials securely.",
                                code_snippet=redacted,
                                is_secret=True,
                            )
                        )
                    return findings
                finally:
                    if report_file.exists():
                        report_file.unlink()
        except Exception:
            return None
        return None

    def _scan_content(self, file_path: str, content: str) -> List[SecurityVulnerability]:
        """Scans text content line by line using secret detection patterns and entropy heuristics."""
        findings: List[SecurityVulnerability] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Ignore comments in source code that say 'example' or 'test'
            if stripped.startswith(("#", "//", "/*", "*")) and any(
                dummy in stripped.lower() for dummy in ("dummy", "example", "placeholder", "fake")
            ):
                continue

            for rule in self.SECRET_RULES:
                match = rule["pattern"].search(line)
                if match:
                    raw_secret = match.group(0)
                    # Filter out short or dummy values
                    if any(dummy in raw_secret.lower() for dummy in ("example", "your_secret", "dummy")):
                        continue

                    # If generic secret rule, verify high entropy to eliminate common words/placeholders
                    if rule["id"] == "generic-secret-assignment":
                        secret_val = match.group(1) if match.lastindex else raw_secret
                        if self._calculate_shannon_entropy(secret_val) < 3.0:
                            continue

                    redacted_snippet = self._redact_snippet(line, raw_secret)
                    findings.append(
                        SecurityVulnerability(
                            id=f"SEC-LEAK-{idx}-{rule['id'][:6]}",
                            title=f"Exposed {rule['title']}",
                            description=(
                                f"Detected hardcoded credential or secret matching rule `{rule['id']}`. "
                                "Hardcoding secrets in source files exposes critical credentials to anyone "
                                "with repository read access and risks accidental credential compromise."
                            ),
                            category=VulnerabilityCategory.SECRET,
                            severity=rule["severity"],
                            file_path=file_path,
                            line_number=idx,
                            rule_id=f"gitleaks:{rule['id']}",
                            tool_source="gitleaks",
                            owasp_category="A07:2021-Identification and Authentication Failures",
                            cwe_id=rule["cwe"],
                            cvss_score=8.9 if rule["severity"] == VulnerabilitySeverity.HIGH else 9.8,
                            remediation=rule["remediation"],
                            code_snippet=redacted_snippet,
                            is_secret=True,
                        )
                    )
                    break  # One finding per line is sufficient

        return findings

    @staticmethod
    def _calculate_shannon_entropy(s: str) -> float:
        """Calculates Shannon entropy in bits per character to gauge randomness."""
        if not s:
            return 0.0
        entropy = 0.0
        length = len(s)
        for char in set(s):
            prob = s.count(char) / length
            entropy -= prob * math.log2(prob)
        return entropy

    @staticmethod
    def _redact_secret(secret: str) -> str:
        """Masks the core portion of a secret while keeping the prefix recognizable."""
        if len(secret) <= 8:
            return "********"
        prefix = secret[:4]
        suffix = secret[-2:]
        return f"{prefix}{'*' * (len(secret) - 6)}{suffix}"

    def _redact_snippet(self, line: str, secret: str) -> str:
        """Replaces secret inside source line with redacted asterisks."""
        redacted = self._redact_secret(secret)
        return line.replace(secret, redacted).strip()
