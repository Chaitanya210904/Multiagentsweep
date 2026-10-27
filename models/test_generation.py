"""
Data models for the Test Generation Agent (Layer: Optional).
Defines coverage gaps, code under test, test cases, and generated test files.
Access: can-edit
Trigger: after approval
"""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class TestType(str, Enum):
    """Categorical classification of generated tests."""
    UNIT = "unit"
    INTEGRATION = "integration"
    REGRESSION = "regression"
    EDGE_CASE = "edge_case"
    ERROR_HANDLING = "error_handling"
    PARAMETRIZED = "parametrized"


TestType.__test__ = False


class CoverageGap(BaseModel):
    """
    Represents an identified test coverage gap in source code.
    Can originate from CoverageParserTool, Code Quality findings, or Impact Analyzer untested nodes.
    """
    file_path: str = Field(description="Repository-relative file path where coverage gap exists")
    start_line: int = Field(default=1, ge=1, description="1-indexed line number where gap starts")
    end_line: Optional[int] = Field(default=None, description="1-indexed line number where gap ends")
    missing_lines: List[int] = Field(default_factory=list, description="Specific line numbers not executed in tests")
    node_id: Optional[str] = Field(default=None, description="Canonical registry node ID if mapped")
    entity_name: Optional[str] = Field(default=None, description="Function, method, or class name lacking tests")
    reason: Optional[str] = Field(default=None, description="Contextual explanation of why this gap exists")


class CodeUnderTest(BaseModel):
    """
    Specification of source code targeting test generation.
    """
    file_path: str = Field(description="Repository-relative path of source code under test")
    content: Optional[str] = Field(default=None, description="Raw source code content if provided directly")
    node_ids: List[str] = Field(default_factory=list, description="Target registry node IDs in this file")
    functions: List[str] = Field(default_factory=list, description="Target function or method names to cover")
    classes: List[str] = Field(default_factory=list, description="Target class names to cover")
    language: str = Field(default="python", description="Programming language: python, javascript, typescript")


class TestCase(BaseModel):
    """
    A single generated test function or test method.
    """
    __test__ = False
    name: str = Field(description="Test function name, e.g. 'test_calculate_tax_negative_amount'")
    target_function: str = Field(description="Name of the function or method being tested")
    description: str = Field(description="Summary of test intent and scenario")
    test_type: TestType = Field(default=TestType.UNIT, description="Type of test")
    coverage_gap_addressed: Optional[str] = Field(default=None, description="Coverage gap reference or line range")
    code: str = Field(description="Executable Python test function code")


class NewTestFile(BaseModel):
    """
    Complete synthesized test file output by the Test Generation Agent.
    """
    __test__ = False
    test_file_path: str = Field(description="Target path for the test file, e.g. 'tests/generated/test_calc.py'")
    source_file_path: str = Field(description="Source file under test, e.g. 'core/calc.py'")
    content: str = Field(description="Full executable content of the test file including imports and fixtures")
    target_nodes: List[str] = Field(default_factory=list, description="Registry node IDs targeted")
    coverage_gaps_addressed: List[str] = Field(default_factory=list, description="Summaries of gaps resolved")
    test_cases: List[TestCase] = Field(default_factory=list, description="List of discrete test cases generated")
    written_to_disk: bool = Field(default=False, description="True if test file was actually written to the filesystem")
    verification_status: str = Field(
        default="unverified",
        description="Execution verification result: 'passed', 'failed', 'syntax_valid', 'unverified'",
    )
    test_runner_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed execution report from test_runner tool",
    )


class TestGenerationInput(BaseModel):
    """
    Input payload for the Test Generation Agent.
    Strictly accepts coverage_gaps and code_under_test as mandated by agent specification.
    Includes explicit approval flag enforcing trigger: 'after approval'.
    """
    __test__ = False
    coverage_gaps: List[Any] = Field(
        default_factory=list,
        description="Coverage gaps: CoverageGap objects, QualityFindings, gap dictionaries, or node IDs",
    )
    code_under_test: List[Any] = Field(
        default_factory=list,
        description="Target code files, modules, or CodeUnderTest specifications",
    )
    approved: bool = Field(
        default=True,
        description="Approval flag enforcing trigger 'after approval'. If False, tests are drafted in-memory without disk write.",
    )
    dry_run: bool = Field(
        default=False,
        description="If True, tests are synthesized and verified without persisting to disk.",
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Optional directory where generated test files should be written (defaults to tests/generated/)",
    )
    framework: str = Field(
        default="pytest",
        description="Test framework: 'pytest' or 'unittest'",
    )


class TestGenerationOutput(BaseModel):
    """
    Output payload produced by the Test Generation Agent.
    Outputs new_test_files as mandated by agent specification.
    """
    __test__ = False
    new_test_files: List[NewTestFile] = Field(
        default_factory=list,
        description="List of synthesized and verified test files",
    )
    total_tests_generated: int = Field(default=0, ge=0, description="Total number of individual test cases generated")
    total_gaps_addressed: int = Field(default=0, ge=0, description="Total coverage gaps resolved")
    approval_status: str = Field(
        default="approved",
        description="Approval gate status: 'approved', 'awaiting_approval', 'rejected'",
    )
    execution_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of test_runner execution verification metrics",
    )
    stats: Dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnostic statistics: files generated, lines of test code, test types breakdown",
    )
