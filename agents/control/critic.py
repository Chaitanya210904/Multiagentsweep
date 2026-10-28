"""
Result Aggregator and Critic Agent (Layer: Control).
Role: Consolidator and Quality Gate.
Combines findings from all specialist agents, prunes false alarms and duplicate reports,
resolves inter-agent conflicts, and generates a unified report ranked by business & architectural impact.
"""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agents.base import AgentMetadata, BaseAgent
from models.control import (
    CriticFinding,
    FindingCategory,
    NormalizedSeverity,
    UnifiedReport,
)
from storage.registry_store import CodeRegistryStore


CRITIC_METADATA = AgentMetadata(
    id="result_aggregator_critic",
    name="Result Aggregation & Critic",
    layer="control",
    role="Consolidator & Quality Gate",
    description="Combines findings from all specialist agents, removes false alarms, resolves conflicts, and ranks options by impact.",
    access="read-only",
    model_tier="medium",
    inputs=[
        "specialist_outputs",
        "impact_data",
        "target_files",
    ],
    outputs=[
        "unified_report",
        "ranked_findings",
        "pruned_findings",
        "remediation_options",
    ],
    tools=[
        "critic.deduplicate",
        "critic.rank",
        "registry.lookup",
    ],
    trigger="after specialist agents complete",
    optional=False,
)


class ResultAggregatorCriticAgent(BaseAgent):
    """
    Critic Engine that ingests heterogeneous findings across Quality, Safety, Architecture,
    Runtime, and Rules layers, filters out false alarms, harmonizes severities,
    resolves conflicts, and generates a unified impact-ranked report.
    """

    def __init__(
        self,
        registry_store: Optional[CodeRegistryStore] = None,
        repo_root: Optional[Union[str, Path]] = None,
        log_file: Optional[str] = None,
    ):
        super().__init__(metadata=CRITIC_METADATA, log_file=log_file)
        self.store = registry_store or CodeRegistryStore()
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()

    def execute(self, inputs: Union[Dict[str, Any], Any]) -> UnifiedReport:
        """
        Executes aggregation, false-alarm pruning, conflict resolution, and ranking.
        """
        self.require_access("read-only")

        t0 = self.log_started({"task": "aggregate_and_critic"})

        specialist_outputs = inputs.get("specialist_outputs", {}) if isinstance(inputs, dict) else getattr(inputs, "specialist_outputs", {})
        task_id = inputs.get("task_id", f"task_{int(time.time())}") if isinstance(inputs, dict) else getattr(inputs, "task_id", "default_task")
        target_files = inputs.get("target_files", []) if isinstance(inputs, dict) else getattr(inputs, "target_files", [])

        try:
            # 1. Normalize all specialist outputs into standard CriticFindings
            self.log_event("critic.normalize", "Normalizing heterogeneous findings across all specialist agents")
            raw_findings = self._normalize_all_findings(specialist_outputs)

            # 2. Extract blast radius scores from Impact Analyzer
            blast_radius_score = self._extract_blast_radius(specialist_outputs)

            # 3. Prune false alarms and duplicate reports
            self.log_event("critic.prune", f"Evaluating {len(raw_findings)} raw findings for duplicates and false positives")
            active_findings, pruned_findings = self._prune_false_alarms(raw_findings)

            # 4. Resolve inter-agent recommendation conflicts
            self.log_event("critic.conflicts", "Resolving recommendation conflicts between agents")
            conflicts_resolved = self._resolve_conflicts(active_findings, specialist_outputs)

            # 5. Rank active findings by composite impact score
            self.log_event("critic.rank", "Ranking verified findings by composite impact and blast radius")
            ranked_findings = self._rank_findings_by_impact(active_findings, blast_radius_score)

            # 6. Synthesize actionable remediation proposals for human review
            remediation_options = self._generate_remediation_options(ranked_findings)

            # 7. Compute domain health scores and overall system health
            domain_scores, overall_health = self._compute_health_scores(specialist_outputs, ranked_findings)

            # Severity breakdown
            counts = {
                NormalizedSeverity.CRITICAL.value: sum(1 for f in ranked_findings if f.severity == NormalizedSeverity.CRITICAL),
                NormalizedSeverity.HIGH.value: sum(1 for f in ranked_findings if f.severity == NormalizedSeverity.HIGH),
                NormalizedSeverity.MEDIUM.value: sum(1 for f in ranked_findings if f.severity == NormalizedSeverity.MEDIUM),
                NormalizedSeverity.LOW.value: sum(1 for f in ranked_findings if f.severity == NormalizedSeverity.LOW),
                NormalizedSeverity.INFO.value: sum(1 for f in ranked_findings if f.severity == NormalizedSeverity.INFO),
            }

            # Build executive summary
            summary = self._build_executive_summary(
                overall_health=overall_health,
                active_count=len(ranked_findings),
                pruned_count=len(pruned_findings),
                counts=counts,
            )

            report = UnifiedReport(
                report_id=f"rep_{task_id}_{int(time.time())}",
                task_id=task_id,
                executive_summary=summary,
                overall_health_score=overall_health,
                total_findings_detected=len(raw_findings),
                false_alarms_pruned=len(pruned_findings),
                active_findings_count=len(ranked_findings),
                critical_count=counts[NormalizedSeverity.CRITICAL.value],
                high_count=counts[NormalizedSeverity.HIGH.value],
                medium_count=counts[NormalizedSeverity.MEDIUM.value],
                low_count=counts[NormalizedSeverity.LOW.value],
                info_count=counts[NormalizedSeverity.INFO.value],
                ranked_findings=ranked_findings,
                pruned_findings=pruned_findings,
                conflicts_resolved=conflicts_resolved,
                remediation_options=remediation_options,
                agent_health_scores=domain_scores,
            )

            self.log_completed(t0, {
                "overall_health_score": overall_health,
                "active_findings": len(ranked_findings),
                "pruned_false_alarms": len(pruned_findings),
                "critical": report.critical_count,
                "high": report.high_count,
            })

            return report

        except Exception as e:
            self.log_failed(t0, e)
            raise

    def _normalize_all_findings(self, outputs: Dict[str, Any]) -> List[CriticFinding]:
        """Translates heterogeneous specialist findings into normalized CriticFindings."""
        findings: List[CriticFinding] = []

        # 1. Security findings
        # 1. Security findings
        sec_out = outputs.get("security")
        if sec_out:
            if isinstance(sec_out, dict):
                vulns = sec_out.get("vulnerabilities_with_severity_and_owasp_or_cve_reference") or sec_out.get("vulnerabilities", [])
            else:
                vulns = getattr(sec_out, "vulnerabilities_with_severity_and_owasp_or_cve_reference", None) or getattr(sec_out, "vulnerabilities", [])
            for v in vulns:
                f_id = getattr(v, "id", None) or getattr(v, "vulnerability_id", f"sec_{len(findings)}")
                sev_str = str(getattr(v, "severity", "medium")).lower()
                sev = self._to_normalized_severity(sev_str)
                findings.append(
                    CriticFinding(
                        finding_id=f_id,
                        source_agent="security",
                        tool_name=getattr(v, "tool_source", None) or getattr(v, "scanner", "semgrep/trivy/gitleaks"),
                        rule_or_cve_id=getattr(v, "cve_id", None) or getattr(v, "owasp_category", None) or getattr(v, "rule_id", "SECURITY-RULE"),
                        title=getattr(v, "title", "Security Vulnerability"),
                        category=FindingCategory.SECURITY,
                        severity=sev,
                        file_path=getattr(v, "file_path", None) or getattr(v, "file", None),
                        line_number=getattr(v, "line_number", None) or getattr(v, "line", None),
                        code_snippet=getattr(v, "code_snippet", None) or getattr(v, "snippet", None),
                        description=getattr(v, "description", ""),
                        remediation_proposal=getattr(v, "remediation", "Apply security patch or sanitize inputs."),
                        confidence=getattr(v, "confidence", 0.95),
                    )
                )

        # 2. Company Rules findings
        rules_out = outputs.get("company_rules")
        if rules_out:
            if isinstance(rules_out, dict):
                viols = rules_out.get("violations", [])
            else:
                viols = getattr(rules_out, "violations", [])
            for r in viols:
                sev_str = str(getattr(r, "severity", "medium")).lower()
                sev = self._to_normalized_severity(sev_str)
                findings.append(
                    CriticFinding(
                        finding_id=getattr(r, "violation_id", f"rule_{len(findings)}"),
                        source_agent="company_rules",
                        tool_name="rules.evaluate",
                        rule_or_cve_id=getattr(r, "rule_id", "RULE-CUSTOM"),
                        title=getattr(r, "rule_title", "Company Policy Violation"),
                        category=FindingCategory.POLICY_COMPLIANCE,
                        severity=sev,
                        file_path=getattr(r, "file_path", None),
                        line_number=getattr(r, "line_number", None),
                        code_snippet=getattr(r, "code_snippet", None),
                        description=getattr(r, "infraction_message", ""),
                        remediation_proposal=getattr(r, "remediation", "Comply with corporate policy standard."),
                        confidence=1.0,
                    )
                )

        # 3. Code Quality findings
        cq_out = outputs.get("code_quality")
        if cq_out:
            if isinstance(cq_out, dict):
                q_findings = cq_out.get("findings_with_file_and_line") or cq_out.get("findings", [])
            else:
                q_findings = getattr(cq_out, "findings_with_file_and_line", None) or getattr(cq_out, "findings", [])
            for q in q_findings:
                sev_str = str(getattr(q, "severity", "medium")).lower()
                sev = self._to_normalized_severity(sev_str)
                findings.append(
                    CriticFinding(
                        finding_id=getattr(q, "finding_id", f"cq_{len(findings)}"),
                        source_agent="code_quality",
                        tool_name=getattr(q, "engine", "sonarqube/ruff/eslint"),
                        rule_or_cve_id=getattr(q, "rule_id", "CODE-SMELL"),
                        title=getattr(q, "title", "Code Quality & Maintainability Finding"),
                        category=FindingCategory.QUALITY,
                        severity=sev,
                        file_path=getattr(q, "file_path", None),
                        line_number=getattr(q, "line_number", None),
                        code_snippet=getattr(q, "code_snippet", None),
                        description=getattr(q, "message", getattr(q, "description", "")),
                        remediation_proposal=getattr(q, "remediation", "Refactor complex code to reduce cognitive load."),
                        confidence=0.85,
                    )
                )

        # 4. Architecture Review findings
        arch_out = outputs.get("architecture_review")
        if arch_out:
            if isinstance(arch_out, dict):
                a_viols = arch_out.get("violations", [])
            else:
                a_viols = getattr(arch_out, "violations", [])
            for a in a_viols:
                findings.append(
                    CriticFinding(
                        finding_id=getattr(a, "violation_id", f"arch_{len(findings)}"),
                        source_agent="architecture_review",
                        tool_name="graph.traverse",
                        rule_or_cve_id=str(getattr(a, "type", "ARCHITECTURE_VIOLATION")),
                        title=getattr(a, "title", "Architecture Boundary Violation"),
                        category=FindingCategory.ARCHITECTURE,
                        severity=NormalizedSeverity.HIGH if "cycle" in str(getattr(a, "type", "")).lower() or "boundary" in str(getattr(a, "type", "")).lower() else NormalizedSeverity.MEDIUM,
                        file_path=getattr(a, "file_path", None) or (getattr(a, "nodes", [None])[0] if getattr(a, "nodes", None) else None),
                        line_number=None,
                        code_snippet=None,
                        description=getattr(a, "description", ""),
                        remediation_proposal=getattr(a, "remediation", "Decouple dependency or invert control via dependency injection."),
                        confidence=0.95,
                    )
                )

        # 5. Scale & Load findings
        scale_out = outputs.get("scale_load")
        if scale_out:
            if isinstance(scale_out, dict):
                bottlenecks = scale_out.get("bottlenecks", [])
            else:
                bottlenecks = getattr(scale_out, "bottlenecks", [])
            for b in bottlenecks:
                sev_str = str(getattr(b, "severity", "high")).lower()
                sev = self._to_normalized_severity(sev_str)
                findings.append(
                    CriticFinding(
                        finding_id=getattr(b, "bottleneck_id", f"scale_{len(findings)}"),
                        source_agent="scale_load",
                        tool_name="k6/locust/query_profiler",
                        rule_or_cve_id="N_PLUS_ONE_OR_MISSING_INDEX",
                        title=getattr(b, "title", "Capacity Bottleneck"),
                        category=FindingCategory.PERFORMANCE,
                        severity=sev,
                        file_path=getattr(b, "file_path", None),
                        line_number=getattr(b, "line_number", None),
                        code_snippet=getattr(b, "query_pattern", None),
                        description=getattr(b, "description", ""),
                        remediation_proposal=getattr(b, "remediation", "Add database index, eager load relations, or add Redis cache."),
                        confidence=0.90,
                    )
                )

        # 6. Observability findings
        obs_out = outputs.get("observability")
        if obs_out:
            if isinstance(obs_out, dict):
                anomalies = obs_out.get("error_and_latency_anomalies") or obs_out.get("anomalies", [])
            else:
                anomalies = getattr(obs_out, "error_and_latency_anomalies", None) or getattr(obs_out, "anomalies", [])
            for an in anomalies:
                findings.append(
                    CriticFinding(
                        finding_id=getattr(an, "anomaly_id", f"obs_{len(findings)}"),
                        source_agent="observability",
                        tool_name="prometheus/logs/traces",
                        rule_or_cve_id="RUNTIME_ANOMALY",
                        title=getattr(an, "metric_name", "Runtime Performance Anomaly"),
                        category=FindingCategory.RUNTIME_ANOMALY,
                        severity=NormalizedSeverity.HIGH if getattr(an, "severity", "high") == "high" else NormalizedSeverity.MEDIUM,
                        file_path=None,
                        line_number=None,
                        code_snippet=None,
                        description=getattr(an, "description", f"Metric deviation factor: {getattr(an, 'deviation_factor', 1.0)}x"),
                        remediation_proposal=getattr(an, "remediation", "Inspect telemetry traces and linked registry code nodes."),
                        confidence=0.88,
                    )
                )

        return findings

    def _prune_false_alarms(
        self,
        findings: List[CriticFinding],
    ) -> Tuple[List[CriticFinding], List[CriticFinding]]:
        """
        Critic Engine filters:
        1. Overlapping duplicates (e.g. Semgrep and Company Rules finding the same eval or secret).
        2. Non-existent files or deleted lines.
        3. Low confidence / noisy warnings.
        """
        active: List[CriticFinding] = []
        pruned: List[CriticFinding] = []

        # Deduplication signature: (normalized_file_path, line_number, normalized_category_or_rule)
        seen_locations: Dict[Tuple[str, Optional[int]], CriticFinding] = {}

        for f in findings:
            # Check 1: File existence check (if file_path is specified and relative to repo_root)
            if f.file_path:
                cand_path = self.repo_root / f.file_path if not Path(f.file_path).is_absolute() else Path(f.file_path)
                # If file explicitly doesn't exist on disk, mark as false alarm / stale finding
                if not cand_path.exists() and not f.file_path.startswith("file:"):
                    f.is_false_alarm = True
                    f.suppression_reason = f"File '{f.file_path}' no longer exists in repository working tree."
                    pruned.append(f)
                    continue

            # Check 2: Deduplication across agents
            loc_key = (f.file_path or "no_file", f.line_number)
            if loc_key in seen_locations:
                prior = seen_locations[loc_key]
                # If they target the exact same line with similar rules (e.g. SEC-001 vs hardcoded secret)
                if self._is_duplicate(prior, f):
                    # Keep the higher severity/confidence finding, suppress this one
                    f.is_false_alarm = True
                    f.suppression_reason = f"Duplicate finding already reported by '{prior.source_agent}' ({prior.rule_or_cve_id})."
                    pruned.append(f)
                    continue

            # Check 3: Confidence threshold filter
            if f.confidence < 0.4:
                f.is_false_alarm = True
                f.suppression_reason = f"Confidence score ({f.confidence:.2f}) below minimum reliability threshold."
                pruned.append(f)
                continue

            # Passed all false alarm checks
            seen_locations[loc_key] = f
            active.append(f)

        return active, pruned

    def _is_duplicate(self, prior: CriticFinding, current: CriticFinding) -> bool:
        """Determines if two findings at the same location describe the same underlying defect."""
        if prior.file_path != current.file_path:
            return False
        if prior.line_number is not None and prior.line_number == current.line_number:
            # Both security/policy or both quality
            p_cat = prior.category.value
            c_cat = current.category.value
            if p_cat == c_cat or ("security" in p_cat and "policy" in c_cat) or ("policy" in p_cat and "security" in c_cat):
                return True
        return False

    def _resolve_conflicts(self, active: List[CriticFinding], specialist_outputs: Dict[str, Any]) -> List[str]:
        """Detects and resolves contradictory recommendations from different specialist agents."""
        resolutions: List[str] = []
        files_with_smells = {f.file_path for f in active if f.category == FindingCategory.QUALITY and f.file_path}
        arch_hotspots = set()

        arch_out = specialist_outputs.get("architecture_review")
        if arch_out:
            for v in getattr(arch_out, "violations", []):
                for node_id in getattr(v, "nodes", []):
                    if node_id:
                        arch_hotspots.add(node_id.replace("file:", "").replace("func:", "").split(":")[0])

        overlap = files_with_smells.intersection(arch_hotspots)
        for target in overlap:
            resolutions.append(
                f"Unified Resolution for '{target}': Code Quality recommends splitting long functions, "
                f"while Architecture Review flagged high instability. Resolved: Extract an independent helper module "
                f"with inverted interface dependency to simultaneously eliminate complexity and decouple boundaries."
            )

        return resolutions

    def _rank_findings_by_impact(
        self,
        findings: List[CriticFinding],
        blast_radius: float,
    ) -> List[CriticFinding]:
        """
        Ranks findings by composite business and blast radius impact:
        Impact Score = (Severity Weight * 0.4) + (Blast Radius * 0.3) + (Confidence * 30.0)
        """
        sev_weights = {
            NormalizedSeverity.CRITICAL: 100.0,
            NormalizedSeverity.HIGH: 70.0,
            NormalizedSeverity.MEDIUM: 40.0,
            NormalizedSeverity.LOW: 15.0,
            NormalizedSeverity.INFO: 5.0,
        }

        for f in findings:
            w = sev_weights.get(f.severity, 20.0)
            score = (w * 0.4) + (blast_radius * 0.3) + (f.confidence * 30.0)
            f.impact_score = round(min(100.0, score), 1)

        # Sort descending by impact_score
        return sorted(findings, key=lambda x: x.impact_score, reverse=True)

    def _generate_remediation_options(self, findings: List[CriticFinding]) -> List[Dict[str, Any]]:
        """Synthesizes structured remediation proposals for human approval."""
        options: List[Dict[str, Any]] = []
        for idx, f in enumerate(findings[:10], start=1):
            options.append({
                "option_id": f"OPT-{idx:03d}",
                "title": f.title,
                "target_file": f.file_path,
                "line_number": f.line_number,
                "severity": f.severity.value.upper(),
                "impact_score": f.impact_score,
                "action": f.remediation_proposal,
                "requires_human_approval": True,
            })
        return options

    def _compute_health_scores(
        self,
        outputs: Dict[str, Any],
        active_findings: List[CriticFinding],
    ) -> Tuple[Dict[str, float], float]:
        """Computes calibrated domain and overall health scores (0.0 to 100.0)."""
        domain_scores: Dict[str, float] = {}

        # Security
        sec_out = outputs.get("security")
        domain_scores["security"] = float(getattr(sec_out, "security_score", 100.0)) if sec_out else 100.0

        # Architecture
        arch_out = outputs.get("architecture_review")
        domain_scores["architecture"] = float(getattr(arch_out, "clean_architecture_score", 100.0)) if arch_out else 100.0

        # Quality
        cq_out = outputs.get("code_quality")
        if cq_out:
            rating = str(getattr(cq_out, "maintainability_rating", "A")).upper()
            rating_map = {"A": 95.0, "B": 80.0, "C": 65.0, "D": 50.0, "E": 35.0}
            domain_scores["quality"] = rating_map.get(rating, 75.0)
        else:
            domain_scores["quality"] = 100.0

        # Rules
        rules_out = outputs.get("company_rules")
        domain_scores["policy_compliance"] = float(getattr(rules_out, "compliance_score", 100.0)) if rules_out else 100.0

        # Runtime
        scale_out = outputs.get("scale_load")
        if scale_out:
            status = str(getattr(getattr(scale_out, "capacity_estimate", None), "status", "OPTIMAL")).upper()
            domain_scores["runtime"] = 90.0 if "OPTIMAL" in status else (65.0 if "MARGINAL" in status else 40.0)
        else:
            domain_scores["runtime"] = 100.0

        # Overall composite health
        overall = sum(domain_scores.values()) / max(1, len(domain_scores))
        return domain_scores, round(overall, 1)

    def _extract_blast_radius(self, outputs: Dict[str, Any]) -> float:
        """Extracts numerical blast radius from Impact Analyzer if present."""
        impact_out = outputs.get("impact_analyzer")
        if impact_out:
            return float(getattr(impact_out, "blast_radius_score", 30.0))
        return 25.0

    def _to_normalized_severity(self, s: str) -> NormalizedSeverity:
        """Converts heterogeneous severity strings into NormalizedSeverity."""
        s = s.lower()
        if "crit" in s:
            return NormalizedSeverity.CRITICAL
        if "high" in s:
            return NormalizedSeverity.HIGH
        if "med" in s:
            return NormalizedSeverity.MEDIUM
        if "low" in s:
            return NormalizedSeverity.LOW
        return NormalizedSeverity.INFO

    def _build_executive_summary(
        self,
        overall_health: float,
        active_count: int,
        pruned_count: int,
        counts: Dict[str, int],
    ) -> str:
        """Builds concise synthesis for human reviewers."""
        crit = counts.get(NormalizedSeverity.CRITICAL.value, 0)
        high = counts.get(NormalizedSeverity.HIGH.value, 0)
        med = counts.get(NormalizedSeverity.MEDIUM.value, 0)

        health_tag = "EXCELLENT" if overall_health >= 90 else ("GOOD" if overall_health >= 75 else ("DEGRADED" if overall_health >= 50 else "CRITICAL"))

        return (
            f"Multi-Agent Unified Review: Health [{health_tag}] ({overall_health}/100.0). "
            f"Critic verified {active_count} actionable finding(s) after pruning {pruned_count} false alarm(s)/duplicates. "
            f"Active Breakdown: {crit} Critical, {high} High, {med} Medium. "
            f"All automated edits blocked pending Human-in-the-Loop approval."
        )


ResultAggregatorCritic = ResultAggregatorCriticAgent
