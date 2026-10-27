"""
Agent 10: Security (Layer: Safety).
Role: Vulnerability scanner.
Description: Runs SAST, secret scanning, dependency CVE checks, and auth and input reviews.
Access: read-only
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from agents.base import AgentMetadata, BaseAgent
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
from tools.registry_lookup_tool import RegistryLookupTool
from tools.semgrep_tool import SemgrepTool
from tools.trivy_tool import TrivyTool


SECURITY_METADATA = AgentMetadata(
    id="security",
    name="Security",
    layer="safety",
    role="Vulnerability scanner",
    description="Runs SAST, secret scanning, dependency CVE checks, and auth and input reviews.",
    access="read-only",
    model_tier="medium",
    inputs=[
        "changed_code",
        "dependency_manifests",
        "configs",
        "cve_feeds",
    ],
    outputs=[
        "vulnerabilities_with_severity_and_owasp_or_cve_reference",
    ],
    tools=[
        "semgrep",
        "trivy",
        "gitleaks",
        "registry.lookup",
    ],
    trigger="on changed code or dependencies",
    optional=False,
)


class SecurityAgent(BaseAgent):
    """
    Security Agent: Autonomous Vulnerability Scanner (Layer: Safety).
    - SAST Analysis: Injections, deserialization, SSRF, broken crypto, eval/exec (Semgrep)
    - Secret Scanning: High-entropy credentials, API keys, private keys, tokens (Gitleaks)
    - Dependency CVE Auditing: Known package CVEs in manifests (Trivy)
    - IaC & Config Review: Dockerfile, Kubernetes, environment misconfigurations (Trivy)
    - Auth & Input Review: Missing guards on state-changing API endpoints
    - Strict read-only enforcement
    """

    def __init__(
        self,
        metadata: Optional[AgentMetadata] = None,
        registry_store: Optional[CodeRegistryStore] = None,
        repo_root: Optional[Union[str, Path]] = None,
        log_file: Optional[str] = None,
    ):
        meta = (metadata or SECURITY_METADATA).model_copy(deep=True)
        super().__init__(meta, log_file=log_file)
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.registry_store = registry_store or CodeRegistryStore()
        self.lookup_tool = RegistryLookupTool(store=self.registry_store)

        # Initialize real analysis tools
        self.semgrep_tool = SemgrepTool()
        self.gitleaks_tool = GitleaksTool()
        self.trivy_tool = TrivyTool()

    def execute(self, payload: SecurityInput) -> SecurityOutput:
        """
        Executes comprehensive multi-vector security scanning on changed files and dependencies.
        Enforces read-only access.
        """
        # 1. Enforce strict read-only access
        self.require_access("read-only")

        t0 = self.log_started({
            "code_files_count": len(payload.changed_code),
            "manifests_count": len(payload.dependency_manifests),
            "configs_count": len(payload.configs),
            "cve_feeds_count": len(payload.cve_feeds),
        })

        # 2. Resolve input files and auto-discover manifests/configs if not specified
        code_files = self._resolve_target_files(payload.changed_code)
        manifest_files = self._resolve_manifest_files(payload.dependency_manifests)
        config_files = self._resolve_config_files(payload.configs)

        all_vulnerabilities: List[SecurityVulnerability] = []

        # 3. Tool 1: Semgrep SAST & Auth Review
        self.log_event(
            event="tool.semgrep",
            message=f"Semgrep scanning {len(code_files)} code files",
            files_count=len(code_files),
        )
        sast_vulns = self.semgrep_tool.scan_files(code_files, repo_root=str(self.repo_root))
        all_vulnerabilities.extend(sast_vulns)

        # 4. Tool 2: Gitleaks Secret Scanner
        files_for_secrets = list(set(code_files + config_files))
        self.log_event(
            event="tool.gitleaks",
            message=f"Gitleaks scanning {len(files_for_secrets)} files for credentials",
            files_count=len(files_for_secrets),
        )
        secret_vulns = self.gitleaks_tool.scan_files(files_for_secrets, repo_root=str(self.repo_root))
        all_vulnerabilities.extend(secret_vulns)

        # 5. Tool 3: Trivy Dependency CVE & Config Auditor
        self.log_event(
            event="tool.trivy",
            message=f"Trivy auditing {len(manifest_files)} manifests and {len(config_files)} configs",
            manifests=len(manifest_files),
            configs=len(config_files),
        )
        trivy_vulns = self.trivy_tool.scan_manifests_and_configs(
            manifest_paths=manifest_files,
            config_paths=config_files,
            custom_cve_feeds=payload.cve_feeds,
            repo_root=str(self.repo_root),
        )
        all_vulnerabilities.extend(trivy_vulns)

        # 6. Tool 4: Registry Lookup Context Enrichment
        # If an affected file hosts an API endpoint or DB table registered in the graph, tag context
        enriched_vulns = self._enrich_with_registry_context(all_vulnerabilities)

        # 7. Deduplicate findings
        unique_vulns = self._deduplicate_vulnerabilities(enriched_vulns)

        # 8. Sort vulnerabilities by severity (CRITICAL first) and line number
        severity_order = {
            VulnerabilitySeverity.CRITICAL: 0,
            VulnerabilitySeverity.HIGH: 1,
            VulnerabilitySeverity.MEDIUM: 2,
            VulnerabilitySeverity.LOW: 3,
            VulnerabilitySeverity.INFO: 4,
        }
        unique_vulns.sort(key=lambda v: (severity_order.get(v.severity, 5), v.file_path, v.line_number))

        # 9. Compute Metrics & Severity Breakdown
        critical_count = sum(1 for v in unique_vulns if v.severity == VulnerabilitySeverity.CRITICAL)
        high_count = sum(1 for v in unique_vulns if v.severity == VulnerabilitySeverity.HIGH)
        medium_count = sum(1 for v in unique_vulns if v.severity == VulnerabilitySeverity.MEDIUM)
        low_count = sum(1 for v in unique_vulns if v.severity == VulnerabilitySeverity.LOW)
        info_count = sum(1 for v in unique_vulns if v.severity == VulnerabilitySeverity.INFO)

        # 10. Quantitative Security Score & Grade
        security_score = self._calculate_security_score(
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            info_count=info_count,
        )
        security_grade = self._calculate_security_grade(security_score, critical_count, high_count)

        # 11. Policy Compliance Check (Pass / Fail)
        passed = self._check_policy_pass(unique_vulns, payload.fail_on_severity)

        # Diagnostics stats
        by_category = {}
        for v in unique_vulns:
            cat = v.category.value if hasattr(v.category, "value") else str(v.category)
            by_category[cat] = by_category.get(cat, 0) + 1

        stats = {
            "by_category": by_category,
            "by_severity": {
                "critical": critical_count,
                "high": high_count,
                "medium": medium_count,
                "low": low_count,
                "info": info_count,
            },
            "scanned_code_files": len(code_files),
            "scanned_manifest_files": len(manifest_files),
            "scanned_config_files": len(config_files),
        }

        self.log_completed(
            start_time=t0,
            outputs_summary={
                "vulnerabilities_total": len(unique_vulns),
                "critical": critical_count,
                "high": high_count,
                "security_score": security_score,
                "security_grade": security_grade,
                "passed": passed,
            },
        )

        return SecurityOutput(
            vulnerabilities_with_severity_and_owasp_or_cve_reference=unique_vulns,
            security_score=security_score,
            security_grade=security_grade,
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            info_count=info_count,
            passed=passed,
            scanned_files_count=len(code_files) + len(manifest_files) + len(config_files),
            stats=stats,
        )

    # --------------------------------------------------------------------------
    # Subroutines: File Resolution
    # --------------------------------------------------------------------------

    def _resolve_target_files(self, inputs: List[Union[str, Path]]) -> List[str]:
        """Resolves target source code files."""
        resolved: List[str] = []
        for item in inputs:
            p = Path(item) if Path(item).is_absolute() else self.repo_root / item
            if p.is_file():
                try:
                    rel = str(p.relative_to(self.repo_root))
                except ValueError:
                    rel = str(p)
                resolved.append(rel)
            elif p.is_dir():
                for sub in p.rglob("*"):
                    if sub.is_file() and sub.suffix.lower() in (
                        ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".c", ".cpp"
                    ):
                        try:
                            rel = str(sub.relative_to(self.repo_root))
                        except ValueError:
                            rel = str(sub)
                        resolved.append(rel)
        return resolved

    def _resolve_manifest_files(self, inputs: List[Union[str, Path]]) -> List[str]:
        """Resolves dependency manifest files or auto-discovers if empty."""
        resolved: List[str] = []
        for item in inputs:
            p = Path(item) if Path(item).is_absolute() else self.repo_root / item
            if p.is_file():
                try:
                    rel = str(p.relative_to(self.repo_root))
                except ValueError:
                    rel = str(p)
                resolved.append(rel)

        if not resolved:
            # Auto-discover common manifests at repo root
            for name in ("requirements.txt", "package.json", "Pipfile", "pyproject.toml"):
                candidate = self.repo_root / name
                if candidate.is_file():
                    resolved.append(name)
        return resolved

    def _resolve_config_files(self, inputs: List[Union[str, Path]]) -> List[str]:
        """Resolves configuration files or auto-discovers if empty."""
        resolved: List[str] = []
        for item in inputs:
            p = Path(item) if Path(item).is_absolute() else self.repo_root / item
            if p.is_file():
                try:
                    rel = str(p.relative_to(self.repo_root))
                except ValueError:
                    rel = str(p)
                resolved.append(rel)

        if not resolved:
            # Auto-discover common configs
            for name in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", ".env"):
                candidate = self.repo_root / name
                if candidate.is_file():
                    resolved.append(name)
        return resolved

    # --------------------------------------------------------------------------
    # Subroutines: Context Enrichment & Deduplication
    # --------------------------------------------------------------------------

    def _enrich_with_registry_context(
        self, vulnerabilities: List[SecurityVulnerability]
    ) -> List[SecurityVulnerability]:
        """Checks registry to see if affected files contain API routes or database models."""
        enriched: List[SecurityVulnerability] = []
        for v in vulnerabilities:
            nodes = self.lookup_tool.get_by_path(v.file_path)
            if nodes:
                is_api = any(
                    "api" in n.id.lower() or "route" in n.id.lower() or "endpoint" in n.id.lower()
                    for n in nodes
                )
                if is_api and v.severity == VulnerabilitySeverity.MEDIUM and v.category == VulnerabilityCategory.SAST:
                    # Escalate public API input flaws from Medium to High
                    v.severity = VulnerabilitySeverity.HIGH
                    v.description += " [Registry Context: File exposes registered public API endpoint]"
            enriched.append(v)
        return enriched

    def _deduplicate_vulnerabilities(
        self, vulnerabilities: List[SecurityVulnerability]
    ) -> List[SecurityVulnerability]:
        """Eliminates exact duplicate vulnerability entries."""
        seen: Set[str] = set()
        unique: List[SecurityVulnerability] = []
        for v in vulnerabilities:
            key = f"{v.file_path}:{v.line_number}:{v.rule_id}"
            if key not in seen:
                seen.add(key)
                unique.append(v)
        return unique

    # --------------------------------------------------------------------------
    # Subroutines: Quantitative Scoring & Grading
    # --------------------------------------------------------------------------

    @staticmethod
    def _calculate_security_score(
        critical_count: int,
        high_count: int,
        medium_count: int,
        low_count: int,
        info_count: int,
    ) -> float:
        """
        Calculates calibrated security health score from 0.0 to 100.0.
        Penalties: Critical (-25.0), High (-15.0), Medium (-5.0), Low (-1.0), Info (-0.2).
        """
        score = 100.0
        score -= critical_count * 25.0
        score -= high_count * 15.0
        score -= medium_count * 5.0
        score -= low_count * 1.0
        score -= info_count * 0.2
        return round(max(0.0, score), 1)

    @staticmethod
    def _calculate_security_grade(score: float, critical_count: int, high_count: int) -> str:
        """Assigns security letter grade."""
        if critical_count > 0:
            return "F"
        if score >= 90.0 and high_count == 0:
            return "A"
        if score >= 75.0 and high_count <= 1:
            return "B"
        if score >= 60.0:
            return "C"
        if score >= 40.0:
            return "D"
        return "F"

    @staticmethod
    def _check_policy_pass(
        vulnerabilities: List[SecurityVulnerability],
        fail_on_severity: Optional[VulnerabilitySeverity],
    ) -> bool:
        """Checks whether findings violate the configured minimum severity policy threshold."""
        if not fail_on_severity:
            return True

        severity_ranks = {
            VulnerabilitySeverity.INFO: 1,
            VulnerabilitySeverity.LOW: 2,
            VulnerabilitySeverity.MEDIUM: 3,
            VulnerabilitySeverity.HIGH: 4,
            VulnerabilitySeverity.CRITICAL: 5,
        }
        threshold_rank = severity_ranks.get(fail_on_severity, 4)

        for v in vulnerabilities:
            v_rank = severity_ranks.get(v.severity, 1)
            if v_rank >= threshold_rank:
                return False
        return True


# Backward-compatible alias
Security = SecurityAgent
