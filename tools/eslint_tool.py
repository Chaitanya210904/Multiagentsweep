"""
Tool: eslint
JavaScript and TypeScript linter integration:
Executes official `eslint --format=json` when available,
with an internal rule parser fallback when eslint/Node binary is absent.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import List, Optional

from models.code_quality import FindingSeverity, QualityFinding, QualityFindingCategory


class ESLintTool:
    """Tool: eslint - JavaScript/TypeScript quality and style inspector."""

    name = "eslint"
    description = (
        "Inspects JavaScript/TypeScript source code using ESLint (or rule-based fallback) "
        "to detect syntax smells, loose equality, eval, var usage, and unhandled promises."
    )

    def __init__(self, executable_path: Optional[str] = None):
        self.executable = executable_path or shutil.which("eslint") or shutil.which("npx")

    def check_files(self, file_paths: List[str]) -> List[QualityFinding]:
        """Lints JS/TS files using ESLint binary if present, or internal rule engine."""
        js_files = [f for f in file_paths if f.endswith((".js", ".jsx", ".ts", ".tsx")) and Path(f).exists()]
        if not js_files:
            return []

        if self.executable and shutil.which("eslint"):
            try:
                return self._run_eslint_binary(js_files)
            except Exception:
                pass

        return self._run_pattern_fallback(js_files)

    def _run_eslint_binary(self, js_files: List[str]) -> List[QualityFinding]:
        findings: List[QualityFinding] = []
        cmd = ["eslint", "--format=json"] + js_files
        res = subprocess.run(cmd, capture_output=True, text=True)

        if res.stdout.strip():
            try:
                data = json.loads(res.stdout)
                for file_entry in data:
                    fpath = file_entry.get("filePath", "")
                    for msg in file_entry.get("messages", []):
                        rule_id = msg.get("ruleId") or "eslint:syntax"
                        line = msg.get("line", 1)
                        col = msg.get("column", 1)
                        severity_num = msg.get("severity", 1)
                        desc = msg.get("message", "")

                        sev = FindingSeverity.MAJOR if severity_num == 2 else FindingSeverity.MINOR

                        findings.append(
                            QualityFinding(
                                id=f"eslint:{rule_id}:{fpath}:{line}:{col}",
                                category=QualityFindingCategory.STYLE_ISSUE,
                                severity=sev,
                                file_path=fpath,
                                line_number=line,
                                column_number=col,
                                rule_id=f"eslint:{rule_id}",
                                tool_source="eslint",
                                message=desc,
                                remediation=f"Fix ESLint issue '{rule_id}': {desc}",
                                debt_minutes=5,
                            )
                        )
            except json.JSONDecodeError:
                pass

        return findings

    def _run_pattern_fallback(self, js_files: List[str]) -> List[QualityFinding]:
        """Rule-based inspection for JS/TS code when eslint is not installed."""
        findings: List[QualityFinding] = []

        for fpath in js_files:
            try:
                content = Path(fpath).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for idx, line in enumerate(content.splitlines(), start=1):
                clean = line.strip()
                if clean.startswith(("//", "/*", "*")):
                    continue

                # 1. no-var
                if re.search(r"\bvar\s+[a-zA-Z0-9_$]+", clean):
                    findings.append(
                        QualityFinding(
                            id=f"eslint:no-var:{fpath}:{idx}",
                            category=QualityFindingCategory.STYLE_ISSUE,
                            severity=FindingSeverity.MINOR,
                            file_path=fpath,
                            line_number=idx,
                            rule_id="eslint:no-var",
                            tool_source="eslint",
                            message="Unexpected 'var', use 'let' or 'const' instead.",
                            remediation="Replace 'var' with 'const' or 'let' for block-scoped binding.",
                            debt_minutes=2,
                        )
                    )

                # 2. no-eval
                if re.search(r"\beval\s*\(", clean):
                    findings.append(
                        QualityFinding(
                            id=f"eslint:no-eval:{fpath}:{idx}",
                            category=QualityFindingCategory.CODE_SMELL,
                            severity=FindingSeverity.CRITICAL,
                            file_path=fpath,
                            line_number=idx,
                            rule_id="eslint:no-eval",
                            tool_source="eslint",
                            message="'eval' can be harmful: introduces code injection vulnerability.",
                            remediation="Refactor dynamic execution to use safe parsers or structured mappings.",
                            debt_minutes=15,
                        )
                    )

                # 3. eqeqeq (Loose equality)
                if re.search(r"\s==\s[^=]", clean) or re.search(r"\s!=\s[^=]", clean):
                    findings.append(
                        QualityFinding(
                            id=f"eslint:eqeqeq:{fpath}:{idx}",
                            category=QualityFindingCategory.STYLE_ISSUE,
                            severity=FindingSeverity.MINOR,
                            file_path=fpath,
                            line_number=idx,
                            rule_id="eslint:eqeqeq",
                            tool_source="eslint",
                            message="Expected '===' and instead saw '=='.",
                            remediation="Use strict equality '===' to prevent implicit type coercion.",
                            debt_minutes=2,
                        )
                    )

                # 4. no-debugger
                if re.search(r"\bdebugger\b", clean):
                    findings.append(
                        QualityFinding(
                            id=f"eslint:no-debugger:{fpath}:{idx}",
                            category=QualityFindingCategory.CODE_SMELL,
                            severity=FindingSeverity.MAJOR,
                            file_path=fpath,
                            line_number=idx,
                            rule_id="eslint:no-debugger",
                            tool_source="eslint",
                            message="Unexpected 'debugger' statement in production code.",
                            remediation="Remove debugger breakpoint before committing.",
                            debt_minutes=2,
                        )
                    )

        return findings
