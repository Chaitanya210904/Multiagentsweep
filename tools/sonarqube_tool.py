"""
Tool: sonarqube
Implements SonarQube static code quality model:
- Cognitive & Cyclomatic complexity calculation
- Code smell detection (long functions, too many parameters, broad exceptions, deep nesting, dead code)
- Duplication detection (repeated code blocks across files)
"""

import ast
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from models.code_quality import FindingSeverity, QualityFinding, QualityFindingCategory


class SonarQubeTool:
    """Tool: sonarqube - SonarQube static maintainability, complexity, and duplication inspector."""

    name = "sonarqube"
    description = (
        "Inspects source files for cognitive complexity, duplication, and code smells "
        "(long functions, excessive parameters, broad exceptions, deep nesting) based on SonarQube rules."
    )

    def __init__(
        self,
        max_complexity: int = 10,
        max_function_lines: int = 50,
        max_parameters: int = 5,
        min_duplicate_lines: int = 6,
    ):
        self.max_complexity = max_complexity
        self.max_function_lines = max_function_lines
        self.max_parameters = max_parameters
        self.min_duplicate_lines = min_duplicate_lines

    def analyze_file(self, file_path: str, content: Optional[str] = None) -> List[QualityFinding]:
        """Runs SonarQube quality analysis on a single file."""
        p = Path(file_path)
        if content is None:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return []

        findings: List[QualityFinding] = []

        if p.suffix.lower() == ".py":
            findings.extend(self._analyze_python_ast(file_path, content))
        elif p.suffix.lower() in (".js", ".jsx", ".ts", ".tsx"):
            findings.extend(self._analyze_js_generic(file_path, content))

        return findings

    def detect_duplications(self, files_content: Dict[str, str]) -> List[QualityFinding]:
        """
        Detects duplicated code blocks across multiple files.
        Extracts sliding line blocks of length >= min_duplicate_lines.
        """
        findings: List[QualityFinding] = []
        block_hashes: Dict[str, List[Tuple[str, int]]] = {}  # hash -> list of (file_path, start_line)

        for path, content in files_content.items():
            lines = [l.strip() for l in content.splitlines()]
            if len(lines) < self.min_duplicate_lines:
                continue

            for i in range(len(lines) - self.min_duplicate_lines + 1):
                window = lines[i : i + self.min_duplicate_lines]
                # Skip windows composed only of trivial syntax (comments, braces, empty lines)
                meaningful = [l for l in window if l and not l.startswith(("#", "//", "/*", "*", "pass"))]
                if len(meaningful) < 4:
                    continue

                block_str = "\n".join(meaningful)
                block_hash = hashlib.sha256(block_str.encode("utf-8")).hexdigest()
                block_hashes.setdefault(block_hash, []).append((path, i + 1))

        # Check for duplicate hashes that appear in different places
        reported_dups: Set[Tuple[str, int]] = set()

        for h, occurrences in block_hashes.items():
            if len(occurrences) > 1:
                first_file, first_line = occurrences[0]
                for file_path, line_no in occurrences[1:]:
                    if (file_path, line_no) not in reported_dups:
                        reported_dups.add((file_path, line_no))
                        findings.append(
                            QualityFinding(
                                id=f"sonar:dup:{file_path}:{line_no}",
                                category=QualityFindingCategory.DUPLICATION,
                                severity=FindingSeverity.MAJOR,
                                file_path=file_path,
                                line_number=line_no,
                                end_line_number=line_no + self.min_duplicate_lines,
                                rule_id="sonar:duplicated-blocks",
                                tool_source="sonarqube",
                                message=(
                                    f"Duplicated code block: {self.min_duplicate_lines} identical lines "
                                    f"duplicated with {first_file}:{first_line}."
                                ),
                                remediation=(
                                    f"Extract duplicated logic into a shared helper function or utility module."
                                ),
                                debt_minutes=15,
                            )
                        )

        return findings

    # --------------------------------------------------------------------------
    # Python AST Analysis
    # --------------------------------------------------------------------------

    def _analyze_python_ast(self, file_path: str, content: str) -> List[QualityFinding]:
        findings: List[QualityFinding] = []
        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError:
            return findings

        lines = content.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_findings = self._check_function_node(node, file_path, lines)
                findings.extend(func_findings)

            elif isinstance(node, ast.Try):
                try_findings = self._check_try_node(node, file_path, lines)
                findings.extend(try_findings)

        return findings

    def _check_function_node(
        self,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        file_path: str,
        lines: List[str],
    ) -> List[QualityFinding]:
        findings: List[QualityFinding] = []
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)
        func_len = end_line - start_line + 1

        # 1. Function Length (Code Smell)
        if func_len > self.max_function_lines:
            findings.append(
                QualityFinding(
                    id=f"sonar:long-function:{file_path}:{start_line}",
                    category=QualityFindingCategory.CODE_SMELL,
                    severity=FindingSeverity.MAJOR,
                    file_path=file_path,
                    line_number=start_line,
                    end_line_number=end_line,
                    rule_id="sonar:function-length",
                    tool_source="sonarqube",
                    message=(
                        f"Function '{node.name}' has {func_len} lines, exceeding the maintainability "
                        f"threshold of {self.max_function_lines} lines."
                    ),
                    remediation=(
                        f"Decompose '{node.name}' into smaller single-responsibility sub-functions."
                    ),
                    debt_minutes=20,
                )
            )

        # 2. Parameter Count (Code Smell)
        total_args = (
            len(node.args.args)
            + len(node.args.posonlyargs)
            + len(node.args.kwonlyargs)
            + (1 if node.args.vararg else 0)
            + (1 if node.args.kwarg else 0)
        )
        # Exclude 'self' and 'cls'
        first_arg = node.args.args[0].arg if node.args.args else None
        if first_arg in ("self", "cls"):
            total_args -= 1

        if total_args > self.max_parameters:
            findings.append(
                QualityFinding(
                    id=f"sonar:too-many-parameters:{file_path}:{start_line}",
                    category=QualityFindingCategory.CODE_SMELL,
                    severity=FindingSeverity.MAJOR,
                    file_path=file_path,
                    line_number=start_line,
                    rule_id="sonar:too-many-parameters",
                    tool_source="sonarqube",
                    message=(
                        f"Function '{node.name}' has {total_args} parameters, exceeding the limit of {self.max_parameters}."
                    ),
                    remediation=(
                        f"Introduce a parameter object or Pydantic dataclass to encapsulate arguments for '{node.name}'."
                    ),
                    debt_minutes=10,
                )
            )

        # 3. Cyclomatic & Cognitive Complexity
        complexity = self._compute_cyclomatic_complexity(node)
        if complexity > self.max_complexity:
            findings.append(
                QualityFinding(
                    id=f"sonar:complexity:{file_path}:{start_line}",
                    category=QualityFindingCategory.COMPLEXITY,
                    severity=FindingSeverity.CRITICAL if complexity > (self.max_complexity * 2) else FindingSeverity.MAJOR,
                    file_path=file_path,
                    line_number=start_line,
                    end_line_number=end_line,
                    rule_id="sonar:cognitive-complexity",
                    tool_source="sonarqube",
                    message=(
                        f"Function '{node.name}' has cyclomatic complexity of {complexity} "
                        f"(threshold is {self.max_complexity})."
                    ),
                    remediation=(
                        f"Refactor control flow in '{node.name}'. Replace nested conditionals with guard clauses "
                        f"or polymorphism."
                    ),
                    debt_minutes=complexity * 2,
                )
            )

        # 4. Deep Nesting
        max_nesting = self._compute_max_nesting(node)
        if max_nesting > 4:
            findings.append(
                QualityFinding(
                    id=f"sonar:deep-nesting:{file_path}:{start_line}",
                    category=QualityFindingCategory.COMPLEXITY,
                    severity=FindingSeverity.MAJOR,
                    file_path=file_path,
                    line_number=start_line,
                    rule_id="sonar:deep-nesting",
                    tool_source="sonarqube",
                    message=f"Function '{node.name}' contains deeply nested blocks (depth {max_nesting} > 4).",
                    remediation="Flatten nested blocks using early returns / guard clauses.",
                    debt_minutes=15,
                )
            )

        return findings

    def _check_try_node(self, node: ast.Try, file_path: str, lines: List[str]) -> List[QualityFinding]:
        findings: List[QualityFinding] = []
        for handler in node.handlers:
            # Broad exception: `except:` or `except Exception:` without re-raise
            is_broad = handler.type is None
            if handler.type and isinstance(handler.type, ast.Name) and handler.type.id in ("Exception", "BaseException"):
                is_broad = True

            if is_broad:
                # Check if body re-raises or logs
                has_raise = any(isinstance(s, ast.Raise) for s in ast.walk(handler))
                if not has_raise:
                    findings.append(
                        QualityFinding(
                            id=f"sonar:broad-exception:{file_path}:{handler.lineno}",
                            category=QualityFindingCategory.CODE_SMELL,
                            severity=FindingSeverity.CRITICAL,
                            file_path=file_path,
                            line_number=handler.lineno,
                            rule_id="sonar:no-broad-exception",
                            tool_source="sonarqube",
                            message="Broad exception caught without re-raising: masks unexpected runtime defects.",
                            remediation="Catch specific exception types, or re-raise after handling.",
                            debt_minutes=10,
                        )
                    )
        return findings

    def _compute_cyclomatic_complexity(self, node: ast.AST) -> int:
        """Computes McCabe cyclomatic complexity of an AST branch."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
            elif isinstance(child, (ast.Assert, ast.IfExp)):
                complexity += 1
        return complexity

    def _compute_max_nesting(self, node: ast.AST, current_depth: int = 0) -> int:
        """Calculates deepest block nesting level inside a function."""
        max_d = current_depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.Try)):
                d = self._compute_max_nesting(child, current_depth + 1)
                if d > max_d:
                    max_d = d
            else:
                d = self._compute_max_nesting(child, current_depth)
                if d > max_d:
                    max_d = d
        return max_d

    # --------------------------------------------------------------------------
    # JavaScript / TypeScript Fallback
    # --------------------------------------------------------------------------

    def _analyze_js_generic(self, file_path: str, content: str) -> List[QualityFinding]:
        findings: List[QualityFinding] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Hardcoded credentials smell
            if any(k in stripped.lower() for k in ("password =", "secret =", "api_key =", "token =")):
                if not stripped.startswith(("//", "/*")):
                    findings.append(
                        QualityFinding(
                            id=f"sonar:hardcoded-secret:{file_path}:{idx}",
                            category=QualityFindingCategory.CODE_SMELL,
                            severity=FindingSeverity.BLOCKER,
                            file_path=file_path,
                            line_number=idx,
                            rule_id="sonar:hardcoded-credentials",
                            tool_source="sonarqube",
                            message="Potential hardcoded secret or credential discovered.",
                            remediation="Extract credentials to environment variables or secret manager.",
                            debt_minutes=30,
                        )
                    )
        return findings
