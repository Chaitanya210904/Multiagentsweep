"""
Tool: git.diff
Inspects git diffs, extracts file status changes (A, M, D, R),
and identifies modified, added, deleted, or renamed files.
"""

import hashlib
import os
from pathlib import Path
import subprocess
from typing import Dict, List, Optional, Tuple
from models.registry import GitDiffEntry


class GitDiffTool:
    """Tool for querying and parsing git diffs."""

    name = "git.diff"
    description = "Inspect git diffs and parse added, modified, deleted, or renamed files."

    def __init__(self, repo_root: Optional[str] = None):
        self._repo_root = Path(repo_root) if repo_root else Path.cwd()

    def get_diff_entries(
        self,
        base_commit: Optional[str] = None,
        target_commit: Optional[str] = None,
        staged: bool = False,
    ) -> List[GitDiffEntry]:
        """
        Executes git diff in the repo and parses name-status and diff content.
        """
        cmd = ["git", "diff", "--name-status"]
        if staged:
            cmd.append("--cached")
        if base_commit and target_commit:
            cmd.extend([base_commit, target_commit])
        elif base_commit:
            cmd.append(base_commit)

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                # Fallback or empty if not a git repo or no commits yet
                return []
            
            return self.parse_name_status(result.stdout)
        except Exception:
            return []

    def parse_name_status(self, name_status_output: str) -> List[GitDiffEntry]:
        """
        Parses git diff --name-status lines:
        M    path/to/file.py
        A    path/to/new.py
        D    path/to/deleted.py
        R100 old/path.py  new/path.py
        """
        entries: List[GitDiffEntry] = []
        for line in name_status_output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if not parts:
                continue

            status_code = parts[0].strip()
            if status_code.startswith("R") and len(parts) >= 3:
                # Rename: R100 \t old_path \t new_path
                entries.append(
                    GitDiffEntry(
                        change_type="R",
                        old_path=parts[1].strip(),
                        path=parts[2].strip(),
                    )
                )
            elif status_code.startswith("C") and len(parts) >= 3:
                # Copy: C100 \t old_path \t new_path
                entries.append(
                    GitDiffEntry(
                        change_type="A",
                        old_path=parts[1].strip(),
                        path=parts[2].strip(),
                    )
                )
            elif len(parts) >= 2:
                code = status_code[0].upper()
                entries.append(
                    GitDiffEntry(
                        change_type=code,
                        path=parts[1].strip(),
                    )
                )
        return entries

    def get_file_content_hash(self, file_path: str) -> Optional[str]:
        """Calculates SHA-256 hash of a file on disk if it exists."""
        full_path = self._repo_root / file_path
        if not full_path.is_file():
            return None
        hasher = hashlib.sha256()
        with open(full_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
