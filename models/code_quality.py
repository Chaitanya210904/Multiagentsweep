"""
Data models for the Code Quality Agent (Layer: Quality).
Defines quality findings with file and line numbers, complexity metrics,
duplication, code smells, test coverage gaps, and style issues.
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class QualityFindingCategory(str, Enum):
    """Categorical classification of maintainability and quality issues."""
    COMPLEXITY = "complexity"       # Cognitive complexity, cyclomatic complexity, deep nesting
    DUPLICATION = "duplication"     # Duplicate code blocks, copy-pasted logic
    CODE_SMELL = "code_smell"       # Dead code, long functions, broad exceptions, God methods
    COVERAGE_GAP = "coverage_gap"   # Changed code lacking test coverage
    STYLE_ISSUE = "style_issue"     # Linter warnings, naming violations, unused imports/variables


class FindingSeverity(str, Enum):
    """Severity classification aligned with SonarQube quality model."""
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"
    BLOCKER = "blocker"


class QualityFinding(BaseModel):
    """
    A specific code quality finding pinpointed to an exact file and line number.
    Contains rule ID, tool source, explanation, and remediation guidance.
    """
    id: str = Field(description="Unique finding identifier")
    category: QualityFindingCategory
    severity: FindingSeverity
    file_path: str = Field(description="Repository-relative file path")
    line_number: int = Field(ge=1, description="1-indexed line number where finding begins")
    column_number: Optional[int] = Field(default=None, description="1-indexed column number if available")
    end_line_number: Optional[int] = Field(default=None, description="1-indexed line number where finding ends")
    rule_id: str = Field(description="Canonical rule identifier, e.g. 'sonar:cognitive-complexity', 'ruff:F401'")
    tool_source: str = Field(description="Source tool that generated finding: 'sonarqube', 'ruff', 'eslint', 'coverage'")
    message: str = Field(description="Descriptive explanation of the quality issue")
    remediation: str = Field(description="Specific actionable advice on how to refactor and resolve the issue")
    code_snippet: Optional[str] = Field(default=None, description="Source code snippet at the finding location")
    debt_minutes: int = Field(default=5, ge=0, description="Estimated technical debt remediation time in minutes")


class CoverageSummary(BaseModel):
    """Aggregated test coverage metrics for the reviewed scope."""
    overall_coverage_pct: float = Field(ge=0.0, le=100.0, description="Total coverage percentage across codebase")
    changed_files_coverage_pct: float = Field(ge=0.0, le=100.0, description="Coverage percentage on changed files")
    uncovered_lines_by_file: Dict[str, List[int]] = Field(
        default_factory=dict,
        description="Map of file paths to lists of uncovered line numbers",
    )


class CodeQualityInput(BaseModel):
    """Input payload accepted by the Code Quality Agent."""
    changed_files: List[Union[str, Path]] = Field(
        description="List of file paths that changed or need maintainability review",
    )
    graph_neighbors: List[str] = Field(
        default_factory=list,
        description="Optional list of related graph neighbor node IDs (e.g., callers, callees, tests) from Impact Analyzer",
    )
    coverage_reports: List[Union[str, Path, Dict[str, Any]]] = Field(
        default_factory=list,
        description="Coverage reports: file paths (JSON, XML, LCOV) or parsed coverage dictionaries",
    )
    max_cyclomatic_complexity: int = Field(
        default=10,
        ge=1,
        description="Threshold above which cyclomatic complexity generates a finding",
    )
    max_function_lines: int = Field(
        default=50,
        ge=10,
        description="Threshold above which function length generates a code smell finding",
    )
    max_parameters: int = Field(
        default=5,
        ge=1,
        description="Threshold above which parameter count generates a code smell finding",
    )


class CodeQualityOutput(BaseModel):
    """Output payload produced by the Code Quality Agent."""
    findings_with_file_and_line: List[QualityFinding] = Field(
        default_factory=list,
        description="Detailed list of all findings with exact file paths, line numbers, and remediations",
    )
    maintainability_rating: str = Field(
        description="SonarQube SQALE rating: 'A' (best), 'B', 'C', 'D', 'E' (worst)",
    )
    technical_debt_minutes: int = Field(
        ge=0,
        description="Total estimated remediation time required to fix all findings in minutes",
    )
    coverage_summary: Optional[CoverageSummary] = Field(
        default=None,
        description="Test coverage breakdown across changed files",
    )
    stats: Dict[str, Any] = Field(
        default_factory=dict,
        description="Summary diagnostics: findings by category, severity counts, files scanned",
    )
