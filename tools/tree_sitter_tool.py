"""
Tool: tree_sitter
Multi-language AST parser for extracting code nodes: files, classes, methods, and functions.
Extracts canonical IDs, locations (line ranges, signatures), SHA-256 hashes, and docstring summaries.
"""

import ast
import hashlib
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from models.registry import NodeLocation, NodeType, RegistryNode


class TreeSitterTool:
    """Multi-language code parser and symbol tree extractor."""

    name = "tree_sitter"
    description = (
        "Extracts structural code nodes (file, class, function, method) "
        "with locations, signatures, cryptographic hashes, and docstring summaries."
    )

    def __init__(self, repo_root: Optional[str] = None):
        self._repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

    def parse_file(self, file_path: Path) -> List[RegistryNode]:
        """Parses a real file on disk and extracts all contained code nodes."""
        full_path = file_path if file_path.is_absolute() else (self._repo_root / file_path).resolve()
        if not full_path.is_file():
            return []

        try:
            rel_path = str(full_path.relative_to(self._repo_root))
        except ValueError:
            rel_path = str(full_path)

        try:
            raw_bytes = full_path.read_bytes()
            content = raw_bytes.decode("utf-8", errors="replace")
            file_hash = hashlib.sha256(raw_bytes).hexdigest()
        except Exception:
            return []

        stat = full_path.stat()
        file_node = RegistryNode(
            id=f"file:{rel_path}",
            name=full_path.name,
            type=NodeType.FILE,
            location=NodeLocation(path=rel_path),
            hash=file_hash,
            metadata={
                "size_bytes": stat.st_size,
                "modified_time": stat.st_mtime,
                "extension": full_path.suffix,
            },
        )

        nodes: List[RegistryNode] = [file_node]
        ext = full_path.suffix.lower()

        if ext in (".py", ".pyi"):
            nodes.extend(self._parse_python(content, rel_path))
        elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs"):
            nodes.extend(self._parse_javascript_typescript(content, rel_path))
        elif ext == ".go":
            nodes.extend(self._parse_go(content, rel_path))

        return nodes

    def _parse_python(self, content: str, rel_path: str) -> List[RegistryNode]:
        """Parses Python code using AST to extract classes and functions."""
        nodes: List[RegistryNode] = []
        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError:
            return nodes

        lines = content.splitlines()

        for item in tree.body:
            if isinstance(item, ast.ClassDef):
                end_lineno = item.end_lineno or item.lineno
                class_lines = "\n".join(lines[item.lineno - 1 : end_lineno])
                class_hash = hashlib.sha256(class_lines.encode("utf-8")).hexdigest()
                summary = ast.get_docstring(item)
                
                # Bases / Inheritance signatures
                bases = [getattr(b, "id", getattr(b, "attr", "object")) for b in item.bases]
                base_str = f"({', '.join(bases)})" if bases else ""
                sig = f"class {item.name}{base_str}"

                class_node = RegistryNode(
                    id=f"class:{rel_path}:{item.name}",
                    name=item.name,
                    type=NodeType.CLASS,
                    location=NodeLocation(
                        path=rel_path,
                        start_line=item.lineno,
                        end_line=end_lineno,
                        signature=sig,
                    ),
                    hash=class_hash,
                    metadata={
                        "summary": summary,
                        "docstring": summary,
                        "bases": bases,
                    },
                )
                nodes.append(class_node)

                # Methods inside class
                for sub in item.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        sub_end = sub.end_lineno or sub.lineno
                        fn_lines = "\n".join(lines[sub.lineno - 1 : sub_end])
                        fn_hash = hashlib.sha256(fn_lines.encode("utf-8")).hexdigest()
                        fn_summary = ast.get_docstring(sub)
                        args = [arg.arg for arg in sub.args.args]
                        fn_sig = f"def {sub.name}({', '.join(args)})"

                        method_node = RegistryNode(
                            id=f"func:{rel_path}:{item.name}.{sub.name}",
                            name=f"{item.name}.{sub.name}",
                            type=NodeType.FUNCTION,
                            location=NodeLocation(
                                path=rel_path,
                                start_line=sub.lineno,
                                end_line=sub_end,
                                signature=fn_sig,
                            ),
                            hash=fn_hash,
                            metadata={
                                "summary": fn_summary,
                                "docstring": fn_summary,
                                "parent_class": item.name,
                                "is_async": isinstance(sub, ast.AsyncFunctionDef),
                                "args": args,
                            },
                        )
                        nodes.append(method_node)

            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_lineno = item.end_lineno or item.lineno
                fn_lines = "\n".join(lines[item.lineno - 1 : end_lineno])
                fn_hash = hashlib.sha256(fn_lines.encode("utf-8")).hexdigest()
                summary = ast.get_docstring(item)
                args = [arg.arg for arg in item.args.args]
                sig = f"def {item.name}({', '.join(args)})"

                fn_node = RegistryNode(
                    id=f"func:{rel_path}:{item.name}",
                    name=item.name,
                    type=NodeType.FUNCTION,
                    location=NodeLocation(
                        path=rel_path,
                        start_line=item.lineno,
                        end_line=end_lineno,
                        signature=sig,
                    ),
                    hash=fn_hash,
                    metadata={
                        "summary": summary,
                        "docstring": summary,
                        "is_async": isinstance(item, ast.AsyncFunctionDef),
                        "args": args,
                    },
                )
                nodes.append(fn_node)

        return nodes

    def _parse_javascript_typescript(self, content: str, rel_path: str) -> List[RegistryNode]:
        """Extracts classes, functions, and methods from JS/TS files."""
        nodes: List[RegistryNode] = []
        lines = content.splitlines()

        # Regex patterns for JS/TS
        class_pattern = re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+([A-Za-z0-9_$]+)(?:\s+extends\s+([A-Za-z0-9_$.]+))?")
        fn_pattern = re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)\s*\(([^)]*)\)")
        arrow_pattern = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>")

        for idx, line in enumerate(lines):
            stripped = line.strip()
            lineno = idx + 1

            # Match Class
            c_match = class_pattern.match(stripped)
            if c_match:
                class_name = c_match.group(1)
                extends_name = c_match.group(2)
                sig = f"class {class_name}" + (f" extends {extends_name}" if extends_name else "")
                h = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
                nodes.append(
                    RegistryNode(
                        id=f"class:{rel_path}:{class_name}",
                        name=class_name,
                        type=NodeType.CLASS,
                        location=NodeLocation(path=rel_path, start_line=lineno, signature=sig),
                        hash=h,
                        metadata={"language": "javascript/typescript"},
                    )
                )
                continue

            # Match Function
            f_match = fn_pattern.match(stripped) or arrow_pattern.match(stripped)
            if f_match:
                fn_name = f_match.group(1)
                args = f_match.group(2).strip()
                sig = f"function {fn_name}({args})"
                h = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
                nodes.append(
                    RegistryNode(
                        id=f"func:{rel_path}:{fn_name}",
                        name=fn_name,
                        type=NodeType.FUNCTION,
                        location=NodeLocation(path=rel_path, start_line=lineno, signature=sig),
                        hash=h,
                        metadata={"language": "javascript/typescript", "args": args},
                    )
                )

        return nodes

    def _parse_go(self, content: str, rel_path: str) -> List[RegistryNode]:
        """Extracts struct types and functions from Go files."""
        nodes: List[RegistryNode] = []
        lines = content.splitlines()

        type_pattern = re.compile(r"^type\s+([A-Za-z0-9_]+)\s+struct\b")
        func_pattern = re.compile(r"^func\s+(?:\((?:[^)]+)\)\s+)?([A-Za-z0-9_]+)\s*\(([^)]*)\)")

        for idx, line in enumerate(lines):
            stripped = line.strip()
            lineno = idx + 1

            t_match = type_pattern.match(stripped)
            if t_match:
                name = t_match.group(1)
                h = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
                nodes.append(
                    RegistryNode(
                        id=f"class:{rel_path}:{name}",
                        name=name,
                        type=NodeType.CLASS,
                        location=NodeLocation(path=rel_path, start_line=lineno, signature=f"type {name} struct"),
                        hash=h,
                        metadata={"language": "go"},
                    )
                )

            f_match = func_pattern.match(stripped)
            if f_match:
                name = f_match.group(1)
                h = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
                nodes.append(
                    RegistryNode(
                        id=f"func:{rel_path}:{name}",
                        name=name,
                        type=NodeType.FUNCTION,
                        location=NodeLocation(path=rel_path, start_line=lineno, signature=stripped),
                        hash=h,
                        metadata={"language": "go"},
                    )
                )

        return nodes
