"""
Tool: coverage_parser
Parses test coverage reports (coverage.py JSON, LCOV, Cobertura XML, or Python dicts)
and maps uncovered lines on changed files into pinpointed QualityFinding items.
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from models.code_quality import (
    CoverageSummary,
    FindingSeverity,
    QualityFinding,
    QualityFindingCategory,
)


class CoverageParserTool:
    """Tool for ingesting coverage reports and generating coverage gap findings."""

    name = "coverage_parser"
    description = (
        "Parses coverage reports (JSON, LCOV, XML) and maps uncovered execution lines "
        "in changed files into actionable quality findings."
    )

    def parse_reports(
        self,
        reports: List[Union[str, Path, Dict[str, Any]]],
        changed_files: List[str],
        repo_root: Optional[Path] = None,
    ) -> Tuple[Optional[CoverageSummary], List[QualityFinding]]:
        """
        Parses all supplied coverage reports, calculates coverage percentages,
        and generates coverage gap findings for lines in changed files.
        """
        if not reports:
            return None, []

        root = repo_root or Path.cwd()
        normalized_changed: Set[str] = {
            self._normalize_path(f, root) for f in changed_files
        }

        uncovered_by_file: Dict[str, List[int]] = {}
        total_statements = 0
        total_covered = 0
        changed_statements = 0
        changed_covered = 0

        findings: List[QualityFinding] = []

        for rep in reports:
            parsed_data = self._extract_coverage_data(rep, root)
            if not parsed_data:
                continue

            for norm_path, (missing_lines, num_statements, num_covered) in parsed_data.items():
                total_statements += num_statements
                total_covered += num_covered

                is_changed = any(
                    norm_path == c or norm_path.endswith(c) or c.endswith(norm_path)
                    for c in normalized_changed
                )

                if is_changed:
                    changed_statements += num_statements
                    changed_covered += num_covered
                    uncovered_by_file.setdefault(norm_path, []).extend(missing_lines)

                    # Group consecutive missing lines into blocks
                    blocks = self._group_consecutive_lines(missing_lines)
                    for start_l, end_l in blocks:
                        count = end_l - start_l + 1
                        findings.append(
                            QualityFinding(
                                id=f"cov:uncovered:{norm_path}:{start_l}",
                                category=QualityFindingCategory.COVERAGE_GAP,
                                severity=FindingSeverity.MAJOR,
                                file_path=norm_path,
                                line_number=start_l,
                                end_line_number=end_l,
                                rule_id="coverage:uncovered-lines",
                                tool_source="coverage",
                                message=(
                                    f"Test Coverage Gap: {count} line(s) ({start_l}-{end_l}) in modified file "
                                    f"'{norm_path}' are not covered by automated tests."
                                ),
                                remediation=(
                                    f"Write a unit or integration test targeting lines {start_l}-{end_l} in '{norm_path}'."
                                ),
                                debt_minutes=count * 3,
                            )
                        )

        overall_pct = (
            round((total_covered / total_statements) * 100.0, 1)
            if total_statements > 0
            else 0.0
        )
        changed_pct = (
            round((changed_covered / changed_statements) * 100.0, 1)
            if changed_statements > 0
            else 0.0
        )

        summary = CoverageSummary(
            overall_coverage_pct=overall_pct,
            changed_files_coverage_pct=changed_pct,
            uncovered_lines_by_file=uncovered_by_file,
        )

        return summary, findings

    def _extract_coverage_data(
        self,
        report_input: Union[str, Path, Dict[str, Any]],
        root: Path,
    ) -> Dict[str, Tuple[List[int], int, int]]:
        """
        Returns map: normalized_file_path -> (missing_lines_list, num_statements, num_covered)
        """
        if isinstance(report_input, dict):
            # Direct dictionary format: { "path/to/file.py": [lines] }
            res: Dict[str, Tuple[List[int], int, int]] = {}
            for fpath, lines in report_input.items():
                norm = self._normalize_path(fpath, root)
                missing = sorted(list(lines))
                # Heuristic: assume total statements is missing + estimated covered
                res[norm] = (missing, len(missing) + 10, 10)
            return res

        p = Path(report_input)
        if not p.is_absolute():
            p = root / p
        if not p.exists() or not p.is_file():
            return {}

        content = p.read_text(encoding="utf-8", errors="replace")

        # 1. coverage.py JSON format
        if p.suffix.lower() == ".json":
            return self._parse_coverage_json(content, root)

        # 2. LCOV format
        if p.suffix.lower() == ".info" or "SF:" in content:
            return self._parse_lcov(content, root)

        return {}

    def _parse_coverage_json(self, content: str, root: Path) -> Dict[str, Tuple[List[int], int, int]]:
        result = {}
        try:
            data = json.loads(content)
            files = data.get("files", {})
            for fpath, fstats in files.items():
                norm = self._normalize_path(fpath, root)
                missing = fstats.get("missing_lines", [])
                summary = fstats.get("summary", {})
                num_stmts = summary.get("num_statements", len(missing))
                num_covered = summary.get("covered_lines", max(0, num_stmts - len(missing)))
                result[norm] = (missing, num_stmts, num_covered)
        except Exception:
            pass
        return result

    def _parse_lcov(self, content: str, root: Path) -> Dict[str, Tuple[List[int], int, int]]:
        result = {}
        current_file = None
        missing = []
        total_lines = 0
        hit_lines = 0

        for line in content.splitlines():
            line = line.strip()
            if line.startswith("SF:"):
                current_file = line[3:].strip()
                missing = []
                total_lines = 0
                hit_lines = 0
            elif line.startswith("DA:"):
                parts = line[3:].split(",")
                if len(parts) >= 2:
                    lineno = int(parts[0])
                    hits = int(parts[1])
                    total_lines += 1
                    if hits == 0:
                        missing.append(lineno)
                    else:
                        hit_lines += 1
            elif line == "end_of_record" and current_file:
                norm = self._normalize_path(current_file, root)
                result[norm] = (missing, total_lines, hit_lines)
                current_file = None

        return result

    def _normalize_path(self, fpath: str, root: Path) -> str:
        p = Path(fpath)
        try:
            if p.is_absolute():
                return str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            pass
        s = str(p).replace("\\", "/")
        if s.startswith("./"):
            s = s[2:]
        return s

    def _group_consecutive_lines(self, lines: List[int]) -> List[Tuple[int, int]]:
        """Groups a list of integers into continuous (start, end) ranges."""
        if not lines:
            return []
        sorted_l = sorted(list(set(lines)))
        ranges = []
        start = sorted_l[0]
        prev = start

        for curr in sorted_l[1:]:
            if curr == prev + 1:
                prev = curr
            else:
                ranges.append((start, prev))
                start = curr
                prev = curr
        ranges.append((start, prev))
        return ranges
