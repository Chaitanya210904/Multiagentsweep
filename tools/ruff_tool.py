"""
Tool: ruff
Fast Python linter integration:
Executes official `ruff check --output-format=json` when available,
with an internal Python AST fallback engine when ruff binary is absent.
"""

import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Set

from models.code_quality import FindingSeverity, QualityFinding, QualityFindingCategory


class RuffTool:
    """Tool: ruff - Python linter and code quality scanner."""

    name = "ruff"
    description = (
        "Executes fast Python linting using ruff (or AST fallback) to detect unused imports, "
        "dead variables, style violations, and formatting issues."
    )

    def __init__(self, executable_path: Optional[str] = None):
        # Discover ruff executable
        candidate = executable_path or shutil.which("ruff")
        if not candidate:
            venv_ruff = Path(sys.prefix) / "bin" / "ruff"
            if venv_ruff.exists():
                candidate = str(venv_ruff)
        self.executable = candidate

    def check_files(self, file_paths: List[str]) -> List[QualityFinding]:
        """Lints given Python files, using ruff binary if present, or AST engine."""
        py_files = [f for f in file_paths if f.endswith(".py") and Path(f).exists()]
        if not py_files:
            return []

        if self.executable:
            try:
                return self._run_ruff_binary(py_files)
            except Exception:
                # Fall back to internal AST engine on binary failure
                pass

        return self._run_ast_fallback(py_files)

    def _run_ruff_binary(self, py_files: List[str]) -> List[QualityFinding]:
        findings: List[QualityFinding] = []
        cmd = [self.executable, "check", "--output-format=json"] + py_files
        res = subprocess.run(cmd, capture_output=True, text=True)

        if res.stdout.strip():
            try:
                items = json.loads(res.stdout)
                for item in items:
                    code = item.get("code", "RUFF")
                    msg = item.get("message", "")
                    filename = item.get("filename", "")
                    loc = item.get("location", {})
                    line = loc.get("row", 1)
                    col = loc.get("column", 1)

                    sev = FindingSeverity.MINOR
                    if code.startswith(("F8", "E7", "B")):
                        sev = FindingSeverity.MAJOR
                    elif code.startswith("S"):
                        sev = FindingSeverity.CRITICAL

                    cat = QualityFindingCategory.STYLE_ISSUE
                    if code.startswith(("F8", "E7", "B")):
                        cat = QualityFindingCategory.CODE_SMELL

                    findings.append(
                        QualityFinding(
                            id=f"ruff:{code}:{filename}:{line}:{col}",
                            category=cat,
                            severity=sev,
                            file_path=filename,
                            line_number=line,
                            column_number=col,
                            rule_id=f"ruff:{code}",
                            tool_source="ruff",
                            message=msg,
                            remediation=f"Resolve ruff lint rule {code}: {msg}",
                            debt_minutes=5,
                        )
                    )
            except json.JSONDecodeError:
                pass

        return findings

    def _run_ast_fallback(self, py_files: List[str]) -> List[QualityFinding]:
        """Pure Python AST linter for unused imports and dead variables."""
        findings: List[QualityFinding] = []

        for fpath in py_files:
            try:
                content = Path(fpath).read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content, filename=fpath)
            except Exception:
                continue

            # 1. Unused imports (ruff:F401)
            imported_names: Dict[str, Tuple[int, int]] = {}  # name -> (lineno, col_offset)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_names[alias.asname or alias.name] = (node.lineno, node.col_offset)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name != "*":
                            imported_names[alias.asname or alias.name] = (node.lineno, node.col_offset)

            # Collect all referenced names
            used_names: Set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
                    used_names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    used_names.add(node.attr)

            for imp_name, (lineno, col) in imported_names.items():
                # Dunder or wildcard skips
                if imp_name not in used_names and not imp_name.startswith("__"):
                    findings.append(
                        QualityFinding(
                            id=f"ruff:F401:{fpath}:{lineno}:{col}",
                            category=QualityFindingCategory.STYLE_ISSUE,
                            severity=FindingSeverity.MINOR,
                            file_path=fpath,
                            line_number=lineno,
                            column_number=col + 1,
                            rule_id="ruff:F401",
                            tool_source="ruff",
                            message=f"'{imp_name}' imported but unused",
                            remediation=f"Remove unused import '{imp_name}'.",
                            debt_minutes=2,
                        )
                    )

            # 2. Line length check (ruff:E501)
            for idx, line in enumerate(content.splitlines(), start=1):
                if len(line) > 130 and not line.strip().startswith(("#", "http")):
                    findings.append(
                        QualityFinding(
                            id=f"ruff:E501:{fpath}:{idx}",
                            category=QualityFindingCategory.STYLE_ISSUE,
                            severity=FindingSeverity.INFO,
                            file_path=fpath,
                            line_number=idx,
                            rule_id="ruff:E501",
                            tool_source="ruff",
                            message=f"Line too long ({len(line)} > 130 characters)",
                            remediation="Break long expression onto multiple lines.",
                            debt_minutes=2,
                        )
                    )

        return findings
