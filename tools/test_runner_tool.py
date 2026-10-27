"""
Tool: test_runner
Executes automated test suites (pytest/unittest) on test files and synthesized test code.
Returns structured pass/fail metrics, execution duration, stdout/stderr, and failure traces.
"""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field


class TestExecutionResult(BaseModel):
    """Structured report returned by the test_runner tool."""
    __test__ = False
    success: bool = Field(description="True if all tests passed and no errors occurred")
    total: int = Field(default=0, ge=0, description="Total tests collected and executed")
    passed: int = Field(default=0, ge=0, description="Number of passing tests")
    failed: int = Field(default=0, ge=0, description="Number of failing tests")
    errors: int = Field(default=0, ge=0, description="Number of collection or test setup errors")
    skipped: int = Field(default=0, ge=0, description="Number of skipped tests")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Execution duration in milliseconds")
    output: str = Field(default="", description="Captured terminal output (stdout and stderr)")
    error_message: Optional[str] = Field(default=None, description="High-level error summary if execution failed")
    failures_detail: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed list of specific test failures with tracebacks",
    )


class TestRunnerTool:
    """
    Automated Test Runner Tool for executing and verifying Python tests.
    Uses pytest subprocess execution with timeout guards and AST compilation pre-checks.
    """
    __test__ = False

    name = "test_runner"
    description = (
        "Executes test files using pytest or unittest, validates test syntax, "
        "and extracts granular pass/fail counts, duration, and failure stack traces."
    )

    def __init__(self, repo_root: Optional[Union[str, Path]] = None):
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

    def verify_syntax(self, code: str, filename: str = "<test>") -> Tuple[bool, Optional[str]]:
        """
        Validates Python syntax of test code prior to disk writes or execution.
        Returns (True, None) on success, or (False, error_details) on failure.
        """
        try:
            compile(code, filename, "exec")
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}"
        except Exception as e:
            return False, f"Compilation error: {str(e)}"

    def run_test_file(
        self,
        test_file: Union[str, Path],
        timeout: float = 15.0,
        extra_args: Optional[List[str]] = None,
        cwd: Optional[Path] = None,
    ) -> TestExecutionResult:
        """
        Executes pytest on a specified test file on disk and returns structured metrics.
        """
        target_path = Path(test_file)
        if not target_path.is_absolute():
            target_path = (cwd or self.repo_root) / target_path

        if not target_path.exists():
            return TestExecutionResult(
                success=False,
                total=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                duration_ms=0.0,
                output="",
                error_message=f"Test file not found: {target_path}",
            )

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(target_path),
            "-v",
            "--tb=short",
        ]
        if extra_args:
            cmd.extend(extra_args)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(cwd or self.repo_root)

        start_time = time.time()
        try:
            res = subprocess.run(
                cmd,
                cwd=str(cwd or self.repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration_ms = (time.time() - start_time) * 1000
            combined_output = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")

            # Parse results from pytest output
            metrics = self._parse_pytest_output(combined_output, return_code=res.returncode)
            metrics.duration_ms = duration_ms
            metrics.output = combined_output
            return metrics

        except subprocess.TimeoutExpired as e:
            duration_ms = (time.time() - start_time) * 1000
            out = (e.stdout or "") + ("\n" + e.stderr if e.stderr else "")
            return TestExecutionResult(
                success=False,
                total=0,
                passed=0,
                failed=1,
                errors=0,
                skipped=0,
                duration_ms=duration_ms,
                output=out,
                error_message=f"Test execution timed out after {timeout} seconds",
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return TestExecutionResult(
                success=False,
                total=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                duration_ms=duration_ms,
                output="",
                error_message=f"Subprocess execution error: {str(e)}",
            )

    def run_code(
        self,
        test_code: str,
        temp_dir: Optional[Path] = None,
        timeout: float = 15.0,
        file_prefix: str = "test_gen_",
    ) -> TestExecutionResult:
        """
        Executes test code in a temporary file and returns structured results.
        Automatically cleans up the temporary file after execution.
        """
        valid_syntax, syn_err = self.verify_syntax(test_code)
        if not valid_syntax:
            return TestExecutionResult(
                success=False,
                total=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                duration_ms=0.0,
                output="",
                error_message=f"Invalid test code syntax: {syn_err}",
            )

        dir_path = temp_dir or (self.repo_root / ".tmp_test_runner")
        dir_path.mkdir(parents=True, exist_ok=True)

        fd, temp_file_path = tempfile.mkstemp(prefix=file_prefix, suffix=".py", dir=str(dir_path))
        os.close(fd)

        try:
            Path(temp_file_path).write_text(test_code, encoding="utf-8")
            return self.run_test_file(
                test_file=Path(temp_file_path),
                timeout=timeout,
                cwd=self.repo_root,
            )
        finally:
            try:
                if Path(temp_file_path).exists():
                    os.unlink(temp_file_path)
            except OSError:
                pass

    def _parse_pytest_output(self, output: str, return_code: int) -> TestExecutionResult:
        """Parses stdout/stderr of pytest run into typed metrics."""
        passed = 0
        failed = 0
        errors = 0
        skipped = 0

        # Match pytest summary line like: "=== 3 passed, 1 failed in 0.05s ==="
        summary_match = re.search(r"==+ (.+) in [0-9\.]+s ==+", output)
        if summary_match:
            parts = summary_match.group(1).split(",")
            for p in parts:
                p = p.strip()
                if "passed" in p:
                    num = re.search(r"(\d+)\s+passed", p)
                    if num:
                        passed = int(num.group(1))
                elif "failed" in p:
                    num = re.search(r"(\d+)\s+failed", p)
                    if num:
                        failed = int(num.group(1))
                elif "error" in p:
                    num = re.search(r"(\d+)\s+error", p)
                    if num:
                        errors = int(num.group(1))
                elif "skipped" in p:
                    num = re.search(r"(\d+)\s+skipped", p)
                    if num:
                        skipped = int(num.group(1))
        else:
            # Fallback line counter if summary banner was cut off
            passed = len(re.findall(r"::[A-Za-z0-9_]+\s+PASSED", output))
            failed = len(re.findall(r"::[A-Za-z0-9_]+\s+FAILED", output))
            errors = len(re.findall(r"::[A-Za-z0-9_]+\s+ERROR", output))

        total = passed + failed + errors + skipped
        success = (return_code == 0) and (failed == 0) and (errors == 0) and (passed > 0 or total == 0)

        failures_detail: List[Dict[str, Any]] = []
        if failed > 0 or errors > 0:
            # Extract failure blocks
            fail_blocks = re.findall(r"_{10,}\s+([^\n]+)\s+_{10,}\n(.*?)(?=\n_{10,}|\n=+ [0-9]|Z\b)", output, re.DOTALL)
            for test_name, trace in fail_blocks:
                failures_detail.append({
                    "test_name": test_name.strip(),
                    "traceback": trace.strip()[:1000],
                })

        err_msg = None
        if not success:
            if failed > 0:
                err_msg = f"{failed} test(s) failed during execution"
            elif errors > 0:
                err_msg = f"{errors} error(s) occurred during test collection or execution"
            elif return_code != 0:
                err_msg = f"pytest exited with non-zero code {return_code}"

        return TestExecutionResult(
            success=success,
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_ms=0.0,
            output=output,
            error_message=err_msg,
            failures_detail=failures_detail,
        )
