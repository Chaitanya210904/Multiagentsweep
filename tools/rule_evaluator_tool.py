"""
Tool: rules.evaluate
Evaluates source code and config files against company policy rules,
pinpointing exact line numbers, citing numbered rule IDs, and providing remediations.
"""

import fnmatch
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from models.company_rules import (
    CompanyRuleDefinition,
    RuleSeverity,
    RuleViolation,
)


class RuleEvaluatorTool:
    """
    Evaluator tool scanning source files, matching patterns, and citing exact rule IDs.
    """

    name = "rules.evaluate"
    description = (
        "Evaluates files against parsed company rule definitions, pinpointing line numbers "
        "and citing rule IDs (e.g. SEC-001) with severity and remediation instructions."
    )

    SEVERITY_ORDER = {
        RuleSeverity.INFO: 1,
        RuleSeverity.LOW: 2,
        RuleSeverity.MEDIUM: 3,
        RuleSeverity.HIGH: 4,
        RuleSeverity.CRITICAL: 5,
    }

    SEVERITY_PENALTIES = {
        RuleSeverity.CRITICAL: 25.0,
        RuleSeverity.HIGH: 12.0,
        RuleSeverity.MEDIUM: 5.0,
        RuleSeverity.LOW: 2.0,
        RuleSeverity.INFO: 0.5,
    }

    def evaluate_rules(
        self,
        files: List[Union[str, Path]],
        rules: List[CompanyRuleDefinition],
        fail_on_severity: RuleSeverity = RuleSeverity.HIGH,
        repo_root: Optional[Union[str, Path]] = None,
    ) -> Tuple[List[RuleViolation], float, bool, Dict[str, int]]:
        """
        Evaluates files against the provided rules.
        Returns:
            (violations, compliance_score, passed, severity_breakdown)
        """
        violations: List[RuleViolation] = []
        counts: Dict[str, int] = {
            RuleSeverity.CRITICAL.value: 0,
            RuleSeverity.HIGH.value: 0,
            RuleSeverity.MEDIUM.value: 0,
            RuleSeverity.LOW.value: 0,
            RuleSeverity.INFO.value: 0,
        }

        root = Path(repo_root) if repo_root else Path.cwd()

        for file_item in files:
            file_path = Path(file_item)
            if not file_path.is_absolute() and repo_root:
                file_path = root / file_path

            if not file_path.exists() or not file_path.is_file():
                # If file doesn't exist on disk, check if it's passed as raw source text or skip
                continue

            # Read content safely
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel_path = str(file_path.relative_to(root)) if file_path.is_relative_to(root) else str(file_path)
            lines = content.splitlines()

            # Evaluate each rule on this file
            for rule in rules:
                if not self._matches_file_patterns(rel_path, rule.file_patterns):
                    continue

                rule_violations = self._check_rule_on_content(rule, rel_path, content, lines)
                for v in rule_violations:
                    violations.append(v)
                    counts[v.severity.value] = counts.get(v.severity.value, 0) + 1

        # Calculate compliance score
        total_penalty = sum(
            counts[sev.value] * self.SEVERITY_PENALTIES[sev]
            for sev in RuleSeverity
        )
        compliance_score = max(0.0, round(100.0 - total_penalty, 2))

        # Check if passed
        threshold_rank = self.SEVERITY_ORDER.get(fail_on_severity, 4)
        passed = True
        for sev, count in counts.items():
            if count > 0 and self.SEVERITY_ORDER.get(RuleSeverity(sev), 1) >= threshold_rank:
                passed = False
                break

        return violations, compliance_score, passed, counts

    def _matches_file_patterns(self, file_path: str, patterns: List[str]) -> bool:
        """Checks if file path matches any of the glob patterns."""
        if not patterns or "*" in patterns or "**/*" in patterns:
            return True

        filename = Path(file_path).name
        for pat in patterns:
            if fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(file_path, pat):
                return True
            if pat.startswith("*.") and file_path.endswith(pat[1:]):
                return True
        return False

    def _check_rule_on_content(
        self,
        rule: CompanyRuleDefinition,
        file_path: str,
        content: str,
        lines: List[str],
    ) -> List[RuleViolation]:
        """Checks a single rule against file content and extracts exact line numbers."""
        violations: List[RuleViolation] = []
        if not rule.pattern:
            return violations

        try:
            pattern = re.compile(rule.pattern)
        except re.error:
            return violations

        # First try line-by-line matching for precise line numbers
        matched_lines = set()
        for idx, line in enumerate(lines, start=1):
            s_line = line.strip()
            if s_line.startswith(("#", "//", "/*", "*", '"""', "'''")):
                continue
            if pattern.search(line):
                matched_lines.add(idx)
                snippet = s_line
                if len(snippet) > 120:
                    snippet = snippet[:117] + "..."

                violations.append(
                    RuleViolation(
                        violation_id=f"viol_{rule.rule_id}_{Path(file_path).stem}_{idx}",
                        rule_id=rule.rule_id,
                        rule_title=rule.title,
                        severity=rule.severity,
                        category=rule.category,
                        file_path=file_path,
                        line_number=idx,
                        code_snippet=snippet,
                        infraction_message=f"Line violates company policy {rule.rule_id}: {rule.description}",
                        remediation=rule.remediation,
                    )
                )

        # If multi-line pattern didn't match line-by-line, check full content
        if not matched_lines:
            for m in pattern.finditer(content):
                # Calculate line number from character offset
                line_no = content[:m.start()].count("\n") + 1
                snippet = lines[line_no - 1].strip() if line_no <= len(lines) else m.group(0)[:80]
                violations.append(
                    RuleViolation(
                        violation_id=f"viol_{rule.rule_id}_{Path(file_path).stem}_{line_no}",
                        rule_id=rule.rule_id,
                        rule_title=rule.title,
                        severity=rule.severity,
                        category=rule.category,
                        file_path=file_path,
                        line_number=line_no,
                        code_snippet=snippet,
                        infraction_message=f"Block violates company policy {rule.rule_id}: {rule.description}",
                        remediation=rule.remediation,
                    )
                )

        return violations
