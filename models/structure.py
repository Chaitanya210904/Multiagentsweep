"""
Data models for the Structure Mapper Agent (Layer: Graph).
"""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union
import uuid
from pydantic import BaseModel, Field

from models.registry import RegistryNode, UpdateProposal


class RepoShard(BaseModel):
    """
    Represents a discrete partition or shard of the repository
    (e.g., a directory, module, package, or explicit list of files).
    """
    shard_id: str = Field(description="Unique shard identifier, e.g. 'shard:agents/graph'")
    root_path: str = Field(description="Directory path of the shard relative to repo root")
    files: Optional[List[str]] = Field(default=None, description="Explicit list of relative file paths in this shard")
    language: Optional[str] = Field(default=None, description="Dominant language if known (python, typescript, etc.)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata tags")

    @classmethod
    def from_directory(cls, dir_path: Union[str, Path], repo_root: Union[str, Path] = ".") -> "RepoShard":
        """Factory method to construct a RepoShard from a directory."""
        repo_p = Path(repo_root).resolve()
        dir_p = Path(dir_path).resolve()
        try:
            rel = str(dir_p.relative_to(repo_p))
        except ValueError:
            rel = str(dir_p)
        clean_rel = "." if rel == "." else rel.lstrip("./")
        shard_id = f"shard:{clean_rel.replace('/', '.')}"
        return cls(shard_id=shard_id, root_path=clean_rel)


class LanguageConfig(BaseModel):
    """Configuration options for language parsing and symbol extraction."""
    language: str = Field(description="Language name: python, javascript, typescript, go, java, sql, etc.")
    extensions: List[str] = Field(description="List of matching file extensions, e.g. ['.py', '.pyi']")
    parser: str = Field(default="tree_sitter", description="Parser engine: 'tree_sitter' or 'ast'")
    extract_docstrings: bool = Field(default=True, description="Whether to extract summaries/docstrings")
    extract_signatures: bool = Field(default=True, description="Whether to extract call signatures")
    max_file_size_bytes: int = Field(default=5 * 1024 * 1024, description="Skip files larger than this threshold")


DEFAULT_LANGUAGE_CONFIGS: Dict[str, LanguageConfig] = {
    "python": LanguageConfig(
        language="python",
        extensions=[".py", ".pyi"],
        parser="tree_sitter",
    ),
    "javascript": LanguageConfig(
        language="javascript",
        extensions=[".js", ".jsx", ".mjs", ".cjs"],
        parser="tree_sitter",
    ),
    "typescript": LanguageConfig(
        language="typescript",
        extensions=[".ts", ".tsx"],
        parser="tree_sitter",
    ),
    "go": LanguageConfig(
        language="go",
        extensions=[".go"],
        parser="tree_sitter",
    ),
    "sql": LanguageConfig(
        language="sql",
        extensions=[".sql"],
        parser="generic",
    ),
    "generic": LanguageConfig(
        language="generic",
        extensions=[],
        parser="generic",
    ),
}


class StructureMapperInput(BaseModel):
    """Input payload accepted by the Structure Mapper Agent."""
    repo_shard: Union[RepoShard, str] = Field(description="Repository shard definition or folder path")
    language_configs: Optional[Dict[str, LanguageConfig]] = Field(
        default=None,
        description="Optional custom language configs (defaults to DEFAULT_LANGUAGE_CONFIGS)",
    )
    only_changed: bool = Field(default=False, description="If True, only emits proposals for modified/new nodes")


class StructureMapperOutput(BaseModel):
    """Output payload produced by the Structure Mapper Agent."""
    shard_id: str
    nodes: List[RegistryNode] = Field(
        default_factory=list,
        description="All extracted code nodes with id, type, path, signature, hash, and summary",
    )
    registry_update_proposals: List[UpdateProposal] = Field(
        default_factory=list,
        description="Update proposals packaged for the Registry Keeper",
    )
    stats: Dict[str, Any] = Field(default_factory=dict, description="Shard processing statistics")
