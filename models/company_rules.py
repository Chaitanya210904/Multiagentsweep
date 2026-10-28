"""
Data models for the Company Rules Agent (Layer: Safety).
Defines rule definitions, categories, severity tiers, violations, and compliance outputs.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RuleSeverity(str, Enum):
    """Severity tier for company policy rules."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleCategory(str, Enum):
    """Categorical classification of company rules."""
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    CODE_STYLE = "code_style"
    NAMING = "naming"
    PERFORMANCE = "performance"
    DATA_PRIVACY = "data_privacy"
    DEPENDENCIES = "dependencies"


class CompanyRuleDefinition(BaseModel):
    """Specification of an enterprise company rule extracted from policy files."""
    rule_id: str = Field(description="Unique numbered rule identifier, e.g., 'SEC-001', 'ARCH-012'")
    title: str = Field(description="Short descriptive name of the rule")
    category: RuleCategory = Field(default=RuleCategory.SECURITY, description="Rule category")
    severity: RuleSeverity = Field(default=RuleSeverity.HIGH, description="Violation severity")
    description: str = Field(description="Detailed explanation of the rule requirements")
    pattern: Optional[str] = Field(default=None, description="Regex or text pattern used for automated checks")
    file_patterns: List[str] = Field(default_factory=lambda: ["*"], description="Target file globs (e.g. ['*.py'])")
    remediation: str = Field(description="Prescriptive action required to resolve the violation")
    source_file: Optional[str] = Field(default=None, description="Path or name of the source policy file")


class RuleViolation(BaseModel):
    """A pinpointed violation of a company rule in the codebase."""
    violation_id: str = Field(description="Unique identifier for the violation instance")
    rule_id: str = Field(description="Cited numbered rule ID, e.g. 'SEC-001'")
    rule_title: str = Field(description="Title of the breached rule")
    severity: RuleSeverity = Field(description="Severity of the violation")
    category: RuleCategory = Field(description="Category of the rule")
    file_path: str = Field(description="Relative or absolute path to the violating file")
    line_number: Optional[int] = Field(default=None, description="Exact line number of the infraction")
    code_snippet: Optional[str] = Field(default=None, description="Offending code line or snippet")
    infraction_message: str = Field(description="Clear explanation of what violated the rule")
    remediation: str = Field(description="Specific remediation instructions citing rule requirements")


class CompanyRulesInput(BaseModel):
    """Input payload accepted by the Company Rules Agent."""
    changed_files: List[str] = Field(
        default_factory=list,
        description="List of files to inspect for policy compliance",
    )
    rule_files: List[str] = Field(
        default_factory=list,
        description="List of uploaded policy file paths, Markdown strings, or raw rule texts",
    )
    rule_definitions: List[CompanyRuleDefinition] = Field(
        default_factory=list,
        description="Explicit pre-parsed CompanyRuleDefinition objects",
    )
    fail_on_severity: RuleSeverity = Field(
        default=RuleSeverity.HIGH,
        description="Minimum severity threshold that triggers a failure status",
    )
    repo_root: Optional[str] = Field(
        default=None,
        description="Optional repository root directory",
    )


class CompanyRulesOutput(BaseModel):
    """Output payload produced by the Company Rules Agent."""
    violations: List[RuleViolation] = Field(
        default_factory=list,
        description="Pinpointed violations with cited rule IDs and line numbers",
    )
    compliance_score: float = Field(
        ge=0.0,
        le=100.0,
        description="Overall compliance percentage score (100.0 = zero violations)",
    )
    rules_checked_count: int = Field(default=0, description="Total number of active rules evaluated")
    files_scanned_count: int = Field(default=0, description="Total number of source files scanned")
    passed: bool = Field(description="Whether the codebase passes company policy compliance")
    critical_count: int = Field(default=0, description="Number of CRITICAL violations")
    high_count: int = Field(default=0, description="Number of HIGH violations")
    medium_count: int = Field(default=0, description="Number of MEDIUM violations")
    low_count: int = Field(default=0, description="Number of LOW violations")
    info_count: int = Field(default=0, description="Number of INFO violations")
    summary: str = Field(description="Executive summary of company policy audit")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Execution timing and metrics")
