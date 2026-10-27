"""
Agent 9: Code Quality (Layer: Quality).
Role: Maintainability checker.
Description: Finds complexity, duplication, smells, test coverage gaps and style issues.
Access: read-only
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from agents.base import AgentMetadata, BaseAgent
from models.code_quality import (
    CodeQualityInput,
    CodeQualityOutput,
    CoverageSummary,
    FindingSeverity,
    QualityFinding,
    QualityFindingCategory,
)
from storage.registry_store import CodeRegistryStore
from tools.coverage_parser import CoverageParserTool
from tools.eslint_tool import ESLintTool
from tools.registry_lookup_tool import RegistryLookupTool
from tools.ruff_tool import RuffTool
from tools.sonarqube_tool import SonarQubeTool


CODE_QUALITY_METADATA = AgentMetadata(
    id="code_quality",
    name="Code Quality",
    layer="quality",
    role="Maintainability checker",
    description="Finds complexity, duplication, smells, test coverage gaps and style issues.",
    access="read-only",
    model_tier="small",
    inputs=[
        "changed_files",
        "graph_neighbors",
        "coverage_reports",
    ],
    outputs=[
        "findings_with_file_and_line",
    ],
    tools=[
        "sonarqube",
        "ruff",
        "eslint",
        "registry.lookup",
    ],
    trigger="on changed files",
    optional=False,
)


class CodeQuality(BaseAgent):
    """
    Code Quality Agent audits source files for maintainability defects:
    - Complexity: Cognitive and Cyclomatic complexity metrics (SonarQube)
    - Duplication: Cross-file block duplication detection (SonarQube)
    - Code Smells: Long functions, excessive parameters, broad exceptions, dead code
    - Style Issues: Unused imports, dead variables, formatting (Ruff, ESLint)
    - Coverage Gaps: Line-by-line uncovered execution statements in changed code
    """

    def __init__(
        self,
        store: CodeRegistryStore,
        repo_root: Optional[str] = None,
        metadata: Optional[AgentMetadata] = None,
    ):
        super().__init__(metadata=metadata or CODE_QUALITY_METADATA.model_copy(deep=True))
        self.store = store
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

        # Tools
        self.lookup_tool = RegistryLookupTool(store=self.store)
        self.sonarqube_tool = SonarQubeTool()
        self.ruff_tool = RuffTool()
        self.eslint_tool = ESLintTool()
        self.coverage_tool = CoverageParserTool()

    def execute(self, inputs: Union[CodeQualityInput, Dict[str, Any]]) -> CodeQualityOutput:
        """
        Executes code quality inspection across changed files, graph neighbors, and coverage reports.
        Returns pinpointed findings with exact file paths and line numbers.
        """
        self.require_access("read-only")

        if isinstance(inputs, dict):
            inputs = CodeQualityInput.model_validate(inputs)

        # Update SonarQube thresholds from inputs
        self.sonarqube_tool.max_complexity = inputs.max_cyclomatic_complexity
        self.sonarqube_tool.max_function_lines = inputs.max_function_lines
        self.sonarqube_tool.max_parameters = inputs.max_parameters

        # 1. Resolve files in scope (changed files + graph neighbor files)
        scoped_files = self._resolve_target_files(inputs.changed_files, inputs.graph_neighbors)

        t0 = self.log_started({
            "changed_files_count": len(inputs.changed_files),
            "total_scoped_files": len(scoped_files),
            "coverage_reports_count": len(inputs.coverage_reports),
        })

        try:
            all_findings: List[QualityFinding] = []

            # Read all file contents for inspection
            file_contents: Dict[str, str] = {}
            for f in scoped_files:
                p = Path(f)
                if not p.is_absolute():
                    p = self.repo_root / p
                if p.exists() and p.is_file():
                    try:
                        file_contents[str(f)] = p.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass

            # 2. SonarQube Quality Analysis (Complexity, Code Smells & Duplication)
            for fpath, content in file_contents.items():
                sonar_file_findings = self.sonarqube_tool.analyze_file(fpath, content)
                all_findings.extend(sonar_file_findings)

            if len(file_contents) > 1:
                dup_findings = self.sonarqube_tool.detect_duplications(file_contents)
                all_findings.extend(dup_findings)

            # 3. Ruff Python Linter Analysis (Style & Smells)
            py_files = [f for f in scoped_files if f.endswith(".py")]
            if py_files:
                ruff_findings = self.ruff_tool.check_files(py_files)
                all_findings.extend(ruff_findings)

            # 4. ESLint JS/TS Linter Analysis
            js_files = [f for f in scoped_files if f.endswith((".js", ".jsx", ".ts", ".tsx"))]
            if js_files:
                eslint_findings = self.eslint_tool.check_files(js_files)
                all_findings.extend(eslint_findings)

            # 5. Test Coverage Gap Analysis
            coverage_summary: Optional[CoverageSummary] = None
            if inputs.coverage_reports:
                cov_summary, cov_findings = self.coverage_tool.parse_reports(
                    reports=inputs.coverage_reports,
                    changed_files=[str(f) for f in inputs.changed_files],
                    repo_root=self.repo_root,
                )
                coverage_summary = cov_summary
                all_findings.extend(cov_findings)

            # Deduplicate findings by rule, file, and line
            deduped_findings = self._deduplicate_findings(all_findings)

            # 6. Calculate Technical Debt and Maintainability Rating
            total_debt_minutes = sum(f.debt_minutes for f in deduped_findings)
            rating = self._calculate_maintainability_rating(total_debt_minutes)

            # Summary metrics
            by_category = {}
            by_severity = {}
            for f in deduped_findings:
                by_category[f.category.value] = by_category.get(f.category.value, 0) + 1
                by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1

            stats = {
                "files_analyzed": len(scoped_files),
                "total_findings": len(deduped_findings),
                "findings_by_category": by_category,
                "findings_by_severity": by_severity,
                "technical_debt_minutes": total_debt_minutes,
                "maintainability_rating": rating,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self.log_event(
                "quality.audited",
                f"Code Quality audit completed across {len(scoped_files)} files. "
                f"Rating: {rating} ({total_debt_minutes} min debt). "
                f"Found {len(deduped_findings)} issues across complexity, smells, style, and coverage.",
                **stats,
            )

            self.log_completed(t0, stats)

            return CodeQualityOutput(
                findings_with_file_and_line=deduped_findings,
                maintainability_rating=rating,
                technical_debt_minutes=total_debt_minutes,
                coverage_summary=coverage_summary,
                stats=stats,
            )
        except Exception as e:
            self.log_failed(t0, e)
            raise

    # --------------------------------------------------------------------------
    # Subroutines
    # --------------------------------------------------------------------------

    def _resolve_target_files(
        self,
        changed_files: List[Union[str, Path]],
        graph_neighbors: List[str],
    ) -> List[str]:
        """Resolves changed files and neighbor files into a unique list of file paths."""
        files_set: Set[str] = set()

        for f in changed_files:
            p = Path(f)
            if p.is_absolute():
                try:
                    rel = str(p.relative_to(self.repo_root)).replace("\\", "/")
                    files_set.add(rel)
                except ValueError:
                    files_set.add(str(p))
            else:
                s = str(f).strip()
                if s.startswith("./"):
                    s = s[2:]
                files_set.add(s)

        for nid in graph_neighbors:
            node = self.lookup_tool.get(nid)
            if node and node.location and node.location.path:
                s = str(node.location.path).strip()
                if s.startswith("./"):
                    s = s[2:]
                files_set.add(s)

        return sorted(list(files_set))

    def _deduplicate_findings(self, findings: List[QualityFinding]) -> List[QualityFinding]:
        """Ensures findings are unique by rule, file, and line."""
        seen: Set[str] = set()
        deduped: List[QualityFinding] = []

        for f in findings:
            key = f"{f.rule_id}:{f.file_path}:{f.line_number}"
            if key not in seen:
                seen.add(key)
                deduped.append(f)

        # Sort by file path then line number
        return sorted(deduped, key=lambda f: (f.file_path, f.line_number))

    def _calculate_maintainability_rating(self, debt_minutes: int) -> str:
        """
        Calculates SonarQube SQALE maintainability rating:
        A: <= 30 mins
        B: 31 - 120 mins
        C: 121 - 300 mins
        D: 301 - 600 mins
        E: > 600 mins
        """
        if debt_minutes <= 30:
            return "A"
        elif debt_minutes <= 120:
            return "B"
        elif debt_minutes <= 300:
            return "C"
        elif debt_minutes <= 600:
            return "D"
        else:
            return "E"
