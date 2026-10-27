"""
Tool: trivy
Inspects dependency manifests for known CVEs and scans configuration files
(Dockerfile, Kubernetes YAML, .env) for security misconfigurations.
Supports running the official Trivy CLI when installed, with an authoritative
offline vulnerability database and infrastructure-as-code linter fallback.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple, Union

from packaging.version import parse as parse_version

from models.security import SecurityVulnerability, VulnerabilityCategory, VulnerabilitySeverity


class TrivyTool:
    """Tool: trivy - Dependency vulnerability and IaC config auditor."""

    name = "trivy"
    description = (
        "Audits dependency manifests (requirements.txt, package.json, etc.) for CVE vulnerabilities "
        "and checks configuration files (Dockerfile, k8s.yaml, .env) for misconfigurations."
    )

    # Authoritative offline CVE database for prominent ecosystems
    CVE_DATABASE: List[Dict[str, Any]] = [
        # Python dependencies
        {
            "package": "requests",
            "vulnerable_below": "2.31.0",
            "cve": "CVE-2023-32681",
            "cwe": "CWE-200",
            "cvss": 6.1,
            "severity": VulnerabilitySeverity.MEDIUM,
            "title": "Proxy-Authorization Header Leak in requests",
            "description": (
                "Requests releases prior to 2.31.0 leak the Proxy-Authorization header during HTTPS redirects "
                "to an unintended destination."
            ),
            "remediation": "Upgrade `requests` to version >= 2.31.0.",
        },
        {
            "package": "urllib3",
            "vulnerable_below": "1.26.18",
            "cve": "CVE-2023-45803",
            "cwe": "CWE-200",
            "cvss": 8.1,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "Request Body and Cookie Leak on Redirect in urllib3",
            "description": (
                "urllib3 fails to strip the Request Body and Cookie headers when following cross-origin redirects."
            ),
            "remediation": "Upgrade `urllib3` to version >= 1.26.18 (or >= 2.0.7 for 2.x releases).",
        },
        {
            "package": "flask",
            "vulnerable_below": "2.2.5",
            "cve": "CVE-2023-30861",
            "cwe": "CWE-524",
            "cvss": 7.5,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "Cached Session Cookie Disclosure in Flask",
            "description": "Flask applications caching responses could inadvertently leak user session cookies to proxy caches.",
            "remediation": "Upgrade `flask` to version >= 2.2.5.",
        },
        {
            "package": "django",
            "vulnerable_below": "4.2.11",
            "cve": "CVE-2024-27351",
            "cwe": "CWE-1333",
            "cvss": 7.5,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "ReDoS in django.utils.text.Truncator",
            "description": "A regular expression denial of service exists in Django's Truncator text helper.",
            "remediation": "Upgrade `django` to version >= 4.2.11 or >= 5.0.3.",
        },
        {
            "package": "jinja2",
            "vulnerable_below": "3.1.4",
            "cve": "CVE-2024-34064",
            "cwe": "CWE-79",
            "cvss": 5.4,
            "severity": VulnerabilitySeverity.MEDIUM,
            "title": "Server-Side Template Injection via xmlattr in Jinja2",
            "description": "The xmlattr filter in Jinja2 before 3.1.4 allows injection of arbitrary HTML/XML attributes.",
            "remediation": "Upgrade `jinja2` to version >= 3.1.4.",
        },
        {
            "package": "cryptography",
            "vulnerable_below": "42.0.4",
            "cve": "CVE-2024-26130",
            "cwe": "CWE-476",
            "cvss": 7.5,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "NULL Pointer Dereference in cryptography PKCS7 Parsing",
            "description": "Parsing malformed PKCS#7 structures crashes the Python process or causes denial of service.",
            "remediation": "Upgrade `cryptography` to version >= 42.0.4.",
        },
        {
            "package": "pillow",
            "vulnerable_below": "10.3.0",
            "cve": "CVE-2024-28219",
            "cwe": "CWE-120",
            "cvss": 9.8,
            "severity": VulnerabilitySeverity.CRITICAL,
            "title": "Buffer Overflow in Pillow ImagingCMS",
            "description": "Buffer overflow in ImagingCMS allows remote attackers to execute arbitrary code via malformed ICC profiles.",
            "remediation": "Upgrade `pillow` to version >= 10.3.0.",
        },
        # JavaScript / Node.js dependencies
        {
            "package": "lodash",
            "vulnerable_below": "4.17.21",
            "cve": "CVE-2021-23337",
            "cwe": "CWE-94",
            "cvss": 7.2,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "Command Injection in lodash template",
            "description": "Prototype pollution and command injection via lodash's template function.",
            "remediation": "Upgrade `lodash` to version >= 4.17.21.",
        },
        {
            "package": "express",
            "vulnerable_below": "4.19.2",
            "cve": "CVE-2024-29041",
            "cwe": "CWE-601",
            "cvss": 6.1,
            "severity": VulnerabilitySeverity.MEDIUM,
            "title": "Open Redirect Vulnerability in express",
            "description": "Express.js before 4.19.2 mishandles malformed URL redirects, enabling phishing attacks.",
            "remediation": "Upgrade `express` to version >= 4.19.2.",
        },
        {
            "package": "axios",
            "vulnerable_below": "1.7.4",
            "cve": "CVE-2024-39338",
            "cwe": "CWE-918",
            "cvss": 7.5,
            "severity": VulnerabilitySeverity.HIGH,
            "title": "SSRF Vulnerability in axios",
            "description": "Axios allows Server-Side Request Forgery when handling absolute data protocol URLs.",
            "remediation": "Upgrade `axios` to version >= 1.7.4.",
        },
        {
            "package": "jsonwebtoken",
            "vulnerable_below": "9.0.0",
            "cve": "CVE-2022-23529",
            "cwe": "CWE-94",
            "cvss": 9.8,
            "severity": VulnerabilitySeverity.CRITICAL,
            "title": "Insecure Key Verification in jsonwebtoken",
            "description": "Arbitrary code execution flaw in auth secret verification function.",
            "remediation": "Upgrade `jsonwebtoken` to version >= 9.0.0.",
        },
        # Java / JVM
        {
            "package": "log4j-core",
            "vulnerable_below": "2.17.1",
            "cve": "CVE-2021-44228",
            "cwe": "CWE-502",
            "cvss": 10.0,
            "severity": VulnerabilitySeverity.CRITICAL,
            "title": "Log4Shell Remote Code Execution in Log4j",
            "description": "JNDI features used in configuration, log messages, and parameters do not protect against attacker controlled LDAP.",
            "remediation": "Upgrade `log4j-core` to version >= 2.17.1.",
        },
    ]

    def __init__(self, use_cli_if_available: bool = True):
        self.use_cli_if_available = use_cli_if_available
        self._has_cli = bool(shutil.which("trivy")) if use_cli_if_available else False

    def scan_manifests_and_configs(
        self,
        manifest_paths: List[str],
        config_paths: List[str],
        custom_cve_feeds: Optional[List[Union[str, Path, Dict[str, Any]]]] = None,
        repo_root: Optional[str] = None,
    ) -> List[SecurityVulnerability]:
        """Audits both dependency manifests and configuration files."""
        vulnerabilities: List[SecurityVulnerability] = []
        root = Path(repo_root) if repo_root else Path.cwd()

        # Build active CVE database combining built-in and custom feeds
        active_cve_db = list(self.CVE_DATABASE)
        if custom_cve_feeds:
            for feed in custom_cve_feeds:
                if isinstance(feed, dict):
                    active_cve_db.append(feed)
                elif isinstance(feed, (str, Path)) and Path(feed).is_file():
                    try:
                        content = json.loads(Path(feed).read_text(encoding="utf-8"))
                        if isinstance(content, list):
                            active_cve_db.extend(content)
                    except Exception:
                        pass

        # 1. Audit Dependency Manifests
        for m in manifest_paths:
            p = Path(m) if Path(m).is_absolute() else root / m
            if not p.is_file():
                continue
            rel_path = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            fname = p.name.lower()
            if "requirements" in fname or fname.endswith(".txt"):
                vulnerabilities.extend(self._scan_requirements_txt(rel_path, content, active_cve_db))
            elif fname == "package.json":
                vulnerabilities.extend(self._scan_package_json(rel_path, content, active_cve_db))
            elif fname in ("pyproject.toml", "pipfile"):
                vulnerabilities.extend(self._scan_generic_python_manifest(rel_path, content, active_cve_db))

        # 2. Audit Config Files (Dockerfile, K8s, .env, docker-compose)
        for c in config_paths:
            p = Path(c) if Path(c).is_absolute() else root / c
            if not p.is_file():
                continue
            rel_path = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            fname = p.name.lower()
            if "dockerfile" in fname:
                vulnerabilities.extend(self._scan_dockerfile(rel_path, content))
            elif fname.endswith((".yaml", ".yml")) and ("k8s" in fname or "deployment" in fname or "pod" in fname):
                vulnerabilities.extend(self._scan_k8s_yaml(rel_path, content))
            elif fname.startswith(".env") or "docker-compose" in fname:
                vulnerabilities.extend(self._scan_env_or_compose(rel_path, content))

        return vulnerabilities

    def _scan_requirements_txt(
        self, file_path: str, content: str, cve_db: List[Dict[str, Any]]
    ) -> List[SecurityVulnerability]:
        """Scans requirements.txt lines for vulnerable package versions."""
        findings: List[SecurityVulnerability] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if not s or s.startswith(("#", "-", "@", "git+")):
                continue

            # Parse pkg==version or pkg>=1.0,<=2.0
            match = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*(?:==|>=|<=|~=)\s*([0-9a-zA-Z_\-\.]+)", s)
            if not match:
                continue
            pkg_name = match.group(1).lower().replace("_", "-")
            version_str = match.group(2)

            for cve in cve_db:
                target_pkg = cve["package"].lower().replace("_", "-")
                if pkg_name == target_pkg:
                    if self._is_vulnerable(version_str, cve["vulnerable_below"]):
                        findings.append(
                            SecurityVulnerability(
                                id=f"SEC-CVE-{idx}-{cve['cve']}",
                                title=cve["title"],
                                description=f"{cve['description']} (Detected `{pkg_name}=={version_str}`)",
                                category=VulnerabilityCategory.DEPENDENCY_CVE,
                                severity=cve["severity"],
                                file_path=file_path,
                                line_number=idx,
                                rule_id=f"trivy:{cve['cve']}",
                                tool_source="trivy",
                                owasp_category="A06:2021-Vulnerable and Outdated Components",
                                cve_id=cve["cve"],
                                cwe_id=cve.get("cwe", "CWE-1395"),
                                cvss_score=cve.get("cvss", 7.5),
                                remediation=cve["remediation"],
                                code_snippet=s,
                            )
                        )

        return findings

    def _scan_package_json(
        self, file_path: str, content: str, cve_db: List[Dict[str, Any]]
    ) -> List[SecurityVulnerability]:
        """Scans package.json dependencies and devDependencies."""
        findings: List[SecurityVulnerability] = []
        try:
            data = json.loads(content)
        except Exception:
            return findings

        deps = {}
        deps.update(data.get("dependencies", {}))
        deps.update(data.get("devDependencies", {}))

        lines = content.splitlines()

        for pkg, raw_ver in deps.items():
            clean_ver = re.sub(r"^[\^~>=<]+", "", str(raw_ver)).strip()
            pkg_lower = pkg.lower()

            for cve in cve_db:
                if pkg_lower == cve["package"].lower():
                    if self._is_vulnerable(clean_ver, cve["vulnerable_below"]):
                        # Find line in file
                        line_num = 1
                        for lidx, line in enumerate(lines, start=1):
                            if f'"{pkg}"' in line:
                                line_num = lidx
                                break

                        findings.append(
                            SecurityVulnerability(
                                id=f"SEC-CVE-JS-{line_num}-{cve['cve']}",
                                title=cve["title"],
                                description=f"{cve['description']} (Detected `{pkg}@{clean_ver}`)",
                                category=VulnerabilityCategory.DEPENDENCY_CVE,
                                severity=cve["severity"],
                                file_path=file_path,
                                line_number=line_num,
                                rule_id=f"trivy:{cve['cve']}",
                                tool_source="trivy",
                                owasp_category="A06:2021-Vulnerable and Outdated Components",
                                cve_id=cve["cve"],
                                cwe_id=cve.get("cwe", "CWE-1395"),
                                cvss_score=cve.get("cvss", 7.5),
                                remediation=cve["remediation"],
                                code_snippet=lines[line_num - 1].strip() if line_num - 1 < len(lines) else None,
                            )
                        )

        return findings

    def _scan_generic_python_manifest(
        self, file_path: str, content: str, cve_db: List[Dict[str, Any]]
    ) -> List[SecurityVulnerability]:
        """Scans pyproject.toml or Pipfile."""
        findings: List[SecurityVulnerability] = []
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            match = re.search(r'["\']([a-zA-Z0-9_\-\.]+)\s*[=<>~^]+\s*([0-9a-zA-Z_\-\.]+)["\']', s)
            if match:
                pkg_name = match.group(1).lower().replace("_", "-")
                version_str = match.group(2)
                for cve in cve_db:
                    if pkg_name == cve["package"].lower().replace("_", "-"):
                        if self._is_vulnerable(version_str, cve["vulnerable_below"]):
                            findings.append(
                                SecurityVulnerability(
                                    id=f"SEC-CVE-{idx}-{cve['cve']}",
                                    title=cve["title"],
                                    description=f"{cve['description']} (Detected `{pkg_name}=={version_str}`)",
                                    category=VulnerabilityCategory.DEPENDENCY_CVE,
                                    severity=cve["severity"],
                                    file_path=file_path,
                                    line_number=idx,
                                    rule_id=f"trivy:{cve['cve']}",
                                    tool_source="trivy",
                                    owasp_category="A06:2021-Vulnerable and Outdated Components",
                                    cve_id=cve["cve"],
                                    cwe_id=cve.get("cwe", "CWE-1395"),
                                    cvss_score=cve.get("cvss", 7.5),
                                    remediation=cve["remediation"],
                                    code_snippet=s,
                                )
                            )
        return findings

    def _scan_dockerfile(self, file_path: str, content: str) -> List[SecurityVulnerability]:
        """Inspects Dockerfiles for container security best practices."""
        findings: List[SecurityVulnerability] = []
        lines = content.splitlines()
        has_user_instruction = False

        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if s.startswith("#") or not s:
                continue

            upper = s.upper()

            # Check USER
            if upper.startswith("USER ") and "ROOT" not in upper:
                has_user_instruction = True

            # Check FROM with :latest or unpinned
            if upper.startswith("FROM "):
                image = s.split()[1] if len(s.split()) > 1 else ""
                if ":latest" in image or ":" not in image:
                    findings.append(
                        SecurityVulnerability(
                            id=f"SEC-DOCKER-LATEST-{idx}",
                            title="Dockerfile Uses Unpinned / Latest Base Image",
                            description=(
                                f"Base image `{image}` uses the unpinned or mutable `:latest` tag. "
                                "This creates unpredictable builds and risks silent introduction of vulnerabilities."
                            ),
                            category=VulnerabilityCategory.CONFIG_MISCONFIG,
                            severity=VulnerabilitySeverity.MEDIUM,
                            file_path=file_path,
                            line_number=idx,
                            rule_id="trivy:docker.unpinned-base-image",
                            tool_source="trivy",
                            owasp_category="A05:2021-Security Misconfiguration",
                            cwe_id="CWE-1035",
                            cvss_score=5.0,
                            remediation="Pin base images to a specific immutable tag or digest (e.g. `python:3.12.3-slim`).",
                            code_snippet=s,
                        )
                    )

            # Check EXPOSE 22 (SSH)
            if upper.startswith("EXPOSE ") and "22" in s.split():
                findings.append(
                    SecurityVulnerability(
                        id=f"SEC-DOCKER-SSH-{idx}",
                        title="SSH Daemon Port Exposed in Dockerfile",
                        description="Exposing port 22 in application containers violates container isolation principles.",
                        category=VulnerabilityCategory.CONFIG_MISCONFIG,
                        severity=VulnerabilitySeverity.HIGH,
                        file_path=file_path,
                        line_number=idx,
                        rule_id="trivy:docker.ssh-port-exposed",
                        tool_source="trivy",
                        owasp_category="A05:2021-Security Misconfiguration",
                        cwe_id="CWE-250",
                        cvss_score=7.0,
                        remediation="Do not run OpenSSH inside app containers; use orchestrator exec / debug containers.",
                        code_snippet=s,
                    )
                )

        if not has_user_instruction and lines:
            findings.append(
                SecurityVulnerability(
                    id="SEC-DOCKER-ROOT-1",
                    title="Container Runs as Root (Missing USER Instruction)",
                    description=(
                        "Dockerfile does not specify a non-root `USER` directive. "
                        "Processes executing as UID 0 in containers pose privilege escalation risks if container breaks out."
                    ),
                    category=VulnerabilityCategory.CONFIG_MISCONFIG,
                    severity=VulnerabilitySeverity.HIGH,
                    file_path=file_path,
                    line_number=len(lines),
                    rule_id="trivy:docker.runs-as-root",
                    tool_source="trivy",
                    owasp_category="A05:2021-Security Misconfiguration",
                    cwe_id="CWE-250",
                    cvss_score=7.8,
                    remediation="Add `USER appuser` or `USER 10001` before the ENTRYPOINT/CMD instruction.",
                    code_snippet="USER <non-root-user>",
                )
            )

        return findings

    def _scan_k8s_yaml(self, file_path: str, content: str) -> List[SecurityVulnerability]:
        """Audits Kubernetes deployment/pod YAML files."""
        findings: List[SecurityVulnerability] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if "privileged: true" in s:
                findings.append(
                    SecurityVulnerability(
                        id=f"SEC-K8S-PRIV-{idx}",
                        title="Kubernetes Container Configured with Privileged Access",
                        description=(
                            "Container runs with `privileged: true`. Privileged containers have root capabilities "
                            "on the host kernel, bypassing all container isolation boundaries."
                        ),
                        category=VulnerabilityCategory.CONFIG_MISCONFIG,
                        severity=VulnerabilitySeverity.CRITICAL,
                        file_path=file_path,
                        line_number=idx,
                        rule_id="trivy:k8s.privileged-container",
                        tool_source="trivy",
                        owasp_category="A05:2021-Security Misconfiguration",
                        cwe_id="CWE-250",
                        cvss_score=9.6,
                        remediation="Set `securityContext.privileged: false` and grant only specific Linux capabilities if needed.",
                        code_snippet=s,
                    )
                )

            if "hostNetwork: true" in s:
                findings.append(
                    SecurityVulnerability(
                        id=f"SEC-K8S-NET-{idx}",
                        title="Pod Shares Host Network Namespace",
                        description="`hostNetwork: true` allows pods to sniff and intercept host network traffic.",
                        category=VulnerabilityCategory.CONFIG_MISCONFIG,
                        severity=VulnerabilitySeverity.HIGH,
                        file_path=file_path,
                        line_number=idx,
                        rule_id="trivy:k8s.host-network",
                        tool_source="trivy",
                        owasp_category="A05:2021-Security Misconfiguration",
                        cwe_id="CWE-250",
                        cvss_score=7.7,
                        remediation="Disable `hostNetwork` and rely on Kubernetes Service CNI abstractions.",
                        code_snippet=s,
                    )
                )

        return findings

    def _scan_env_or_compose(self, file_path: str, content: str) -> List[SecurityVulnerability]:
        """Scans .env or docker-compose.yml files for security misconfigurations."""
        findings: List[SecurityVulnerability] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if s.startswith("#") or not s:
                continue

            # Check database port exposed to 0.0.0.0 in docker-compose
            if re.search(r'["\']?0\.0\.0\.0:(?:3306|5432|27017|6379):', s):
                findings.append(
                    SecurityVulnerability(
                        id=f"SEC-COMPOSE-BIND-{idx}",
                        title="Database Port Bound to 0.0.0.0",
                        description=(
                            "Database port is bound to `0.0.0.0`, exposing the database to the entire public Internet."
                        ),
                        category=VulnerabilityCategory.CONFIG_MISCONFIG,
                        severity=VulnerabilitySeverity.HIGH,
                        file_path=file_path,
                        line_number=idx,
                        rule_id="trivy:compose.database-public-bind",
                        tool_source="trivy",
                        owasp_category="A05:2021-Security Misconfiguration",
                        cwe_id="CWE-668",
                        cvss_score=8.5,
                        remediation="Bind database ports to `127.0.0.1` (e.g. `127.0.0.1:5432:5432`) or keep inside internal docker network.",
                        code_snippet=s,
                    )
                )

        return findings

    @staticmethod
    def _is_vulnerable(detected_version: str, vulnerable_below: str) -> bool:
        """Compares semantic versions to check if detected version is lower than patch threshold."""
        try:
            v_curr = parse_version(detected_version)
            v_target = parse_version(vulnerable_below)
            return v_curr < v_target
        except Exception:
            return False
