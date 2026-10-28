"""
Company Rules Agent (Layer: Safety).
Role: Rule compliance checker.
Checks uploaded enterprise policy and rule files, evaluates codebase for policy compliance,
cites the exact numbered rule ID per finding, and flags violations by severity.
"""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union

from agents.base import AgentMetadata, BaseAgent
from models.company_rules import (
    CompanyRuleDefinition,
    CompanyRulesInput,
    CompanyRulesOutput,
    RuleSeverity,
    RuleViolation,
)
from storage.registry_store import CodeRegistryStore
from tools.registry_lookup_tool import RegistryLookupTool
from tools.rule_evaluator_tool import RuleEvaluatorTool
from tools.rule_parser_tool import RuleParserTool


COMPANY_RULES_METADATA = AgentMetadata(
    id="company_rules",
    name="Company Rules",
    layer="safety",
    role="Rule compliance checker",
    description="Checks your uploaded rule files, cites the rule ID per finding, and flags violations by severity.",
    access="read-only",
    model_tier="small",
    inputs=[
        "changed_files",
        "rule_files",
        "rule_definitions",
    ],
    outputs=[
        "violations",
        "compliance_score",
        "severity_breakdown",
    ],
    tools=[
        "rules.parse",
        "rules.evaluate",
        "registry.lookup",
    ],
    trigger="on changed files or rule updates",
    optional=False,
)


class CompanyRulesAgent(BaseAgent):
    """
    Evaluates codebase adherence to enterprise company rules and policies.
    Extracts numbered rule IDs (e.g. 'RULE-SEC-001'), scopes checks to targeted files,
    and calculates quantitative compliance metrics.
    """

    def __init__(
        self,
        registry_store: Optional[CodeRegistryStore] = None,
        repo_root: Optional[Union[str, Path]] = None,
        log_file: Optional[str] = None,
    ):
        super().__init__(metadata=COMPANY_RULES_METADATA, log_file=log_file)
        self.store = registry_store or CodeRegistryStore()
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()

        # Tools
        self.parser_tool = RuleParserTool()
        self.evaluator_tool = RuleEvaluatorTool()
        self.lookup_tool = RegistryLookupTool(store=self.store)

    def execute(self, inputs: Union[CompanyRulesInput, Dict[str, Any]]) -> CompanyRulesOutput:
        """
        Executes policy compliance check against uploaded rule files and code files.
        """
        # Strict access-control verification
        self.require_access("read-only")

        if isinstance(inputs, dict):
            inp = CompanyRulesInput(**inputs)
        else:
            inp = inputs

        t0 = self.log_started({
            "changed_files_count": len(inp.changed_files),
            "rule_files_count": len(inp.rule_files),
            "fail_on_severity": inp.fail_on_severity.value,
        })

        try:
            # 1. Parse active rules from rule files, inline policy, or defaults
            self.log_event("tool.rules_parse", "Parsing company rule files and definitions")
            active_rules = self.parser_tool.parse_rules(
                rule_files_or_texts=inp.rule_files,
                explicit_definitions=inp.rule_definitions,
            )

            # 2. Resolve target files
            target_files = self._resolve_target_files(inp.changed_files)
            effective_root = Path(inp.repo_root) if inp.repo_root else self.repo_root

            # 3. Evaluate files against active rules
            self.log_event(
                "tool.rules_evaluate",
                f"Evaluating {len(target_files)} files against {len(active_rules)} company rules",
            )
            violations, compliance_score, passed, severity_breakdown = self.evaluator_tool.evaluate_rules(
                files=target_files,
                rules=active_rules,
                fail_on_severity=inp.fail_on_severity,
                repo_root=effective_root,
            )

            # 4. Enrich violations with Code Registry entity context if available
            self._enrich_with_registry(violations)

            # 5. Formulate executive summary
            summary = self._build_summary(
                compliance_score=compliance_score,
                violations_count=len(violations),
                passed=passed,
                breakdown=severity_breakdown,
                rules_count=len(active_rules),
            )

            duration_ms = (time.time() - t0) * 1000

            output = CompanyRulesOutput(
                violations=violations,
                compliance_score=compliance_score,
                rules_checked_count=len(active_rules),
                files_scanned_count=len(target_files),
                passed=passed,
                critical_count=severity_breakdown.get(RuleSeverity.CRITICAL.value, 0),
                high_count=severity_breakdown.get(RuleSeverity.HIGH.value, 0),
                medium_count=severity_breakdown.get(RuleSeverity.MEDIUM.value, 0),
                low_count=severity_breakdown.get(RuleSeverity.LOW.value, 0),
                info_count=severity_breakdown.get(RuleSeverity.INFO.value, 0),
                summary=summary,
                stats={
                    "duration_ms": round(duration_ms, 2),
                    "rules_evaluated": len(active_rules),
                    "files_scanned": len(target_files),
                    "violations_found": len(violations),
                },
            )

            self.log_completed(t0, {
                "compliance_score": compliance_score,
                "passed": passed,
                "violations_count": len(violations),
                "critical": output.critical_count,
                "high": output.high_count,
            })

            return output

        except Exception as e:
            self.log_failed(t0, e)
            raise

    def _resolve_target_files(self, changed_files: List[str]) -> List[Path]:
        """Resolves target files to scan, falling back to repository scanning if empty."""
        if changed_files:
            return [
                Path(f) if Path(f).is_absolute() else self.repo_root / f
                for f in changed_files
            ]

        # Scan code files in repo
        code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".sql"}
        discovered = []
        for p in self.repo_root.rglob("*"):
            if p.is_file() and p.suffix in code_exts:
                # Skip hidden/virtualenv dirs
                parts = p.parts
                if any(part.startswith(".") or part in {"venv", ".venv", "node_modules", "__pycache__"} for part in parts):
                    continue
                discovered.append(p)
                if len(discovered) >= 100:  # Bound scan scope
                    break
        return discovered

    def _enrich_with_registry(self, violations: List[RuleViolation]) -> None:
        """Enriches violations with canonical entity metadata from Registry Keeper."""
        for v in violations:
            try:
                # Look up node by path
                nodes = self.lookup_tool.get_by_path(v.file_path)
                if nodes:
                    node = nodes[0]
                    v.infraction_message += f" (Context: {node.type.value} '{node.id}')"
            except Exception:
                pass

    def _build_summary(
        self,
        compliance_score: float,
        violations_count: int,
        passed: bool,
        breakdown: Dict[str, int],
        rules_count: int,
    ) -> str:
        """Constructs concise executive summary of policy adherence."""
        status_text = "PASSED" if passed else "FAILED POLICY COMPLIANCE"
        crit = breakdown.get(RuleSeverity.CRITICAL.value, 0)
        high = breakdown.get(RuleSeverity.HIGH.value, 0)
        med = breakdown.get(RuleSeverity.MEDIUM.value, 0)

        return (
            f"Company Rules Audit: [{status_text}] - Score: {compliance_score}/100.0. "
            f"Evaluated {rules_count} rules across codebase. "
            f"Found {violations_count} violation(s) (Critical: {crit}, High: {high}, Medium: {med})."
        )


CompanyRules = CompanyRulesAgent
