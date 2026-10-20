"""
Tool: git.diff
Inspects real git diffs, extracts file status changes (A, M, D, R),
and calculates SHA-256 hashes of real files on disk.
"""

import hashlib
import os
from pathlib import Path
import subprocess
from typing import Dict, List, Optional, Tuple
from models.registry import GitDiffEntry


class GitDiffTool:
    """Tool for querying and parsing real git diffs from the local repository."""

    name = "git.diff"
    description = "Inspect git diffs and parse added, modified, deleted, or renamed files."

    def __init__(self, repo_root: Optional[str] = None):
        self._repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    def get_diff_entries(
        self,
        base_commit: Optional[str] = None,
        target_commit: Optional[str] = None,
        staged: bool = False,
        include_working_tree: bool = True,
    ) -> List[GitDiffEntry]:
        """
        Executes real git diff in the repo and parses name-status and diff content.
        If no commits are specified, diffs against HEAD (or status if initial repo).
        """
        # Check if repo has commits
        has_head = self._has_head_commit()

        if base_commit and target_commit:
            cmd = ["git", "diff", "--name-status", base_commit, target_commit]
        elif base_commit:
            cmd = ["git", "diff", "--name-status", base_commit]
        elif staged:
            cmd = ["git", "diff", "--name-status", "--cached"]
        elif has_head and include_working_tree:
            cmd = ["git", "diff", "--name-status", "HEAD"]
        elif has_head:
            cmd = ["git", "diff", "--name-status"]
        else:
            # Initial repository with no commits yet - check status
            return self.get_working_tree_status()

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return self.get_working_tree_status()
            
            return self.parse_name_status(result.stdout)
        except Exception:
            return []

    def get_commit_diff(self, commit_hash: str) -> List[GitDiffEntry]:
        """Fetch file modifications introduced by a specific commit."""
        cmd = ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", commit_hash]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return []
            return self.parse_name_status(result.stdout)
        except Exception:
            return []

    def get_working_tree_status(self) -> List[GitDiffEntry]:
        """
        Inspects working tree status using git status --porcelain
        Captures untracked files (??), added (A), modified (M), deleted (D), and renamed (R).
        """
        cmd = ["git", "status", "--porcelain"]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return []
            
            entries: List[GitDiffEntry] = []
            for line in result.stdout.splitlines():
                if not line or len(line) < 3:
                    continue
                code = line[:2]
                raw_path = line[3:].strip()
                
                # Handle renamed files format: "R  old -> new"
                if " -> " in raw_path:
                    old_p, new_p = raw_path.split(" -> ", 1)
                    entries.append(
                        GitDiffEntry(
                            change_type="R",
                            old_path=old_p.strip().strip('"'),
                            path=new_p.strip().strip('"'),
                        )
                    )
                elif "D" in code:
                    entries.append(
                        GitDiffEntry(
                            change_type="D",
                            path=raw_path.strip().strip('"'),
                        )
                    )
                elif "??" in code or "A" in code:
                    entries.append(
                        GitDiffEntry(
                            change_type="A",
                            path=raw_path.strip().strip('"'),
                        )
                    )
                else:
                    entries.append(
                        GitDiffEntry(
                            change_type="M",
                            path=raw_path.strip().strip('"'),
                        )
                    )
            return entries
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
                entries.append(
                    GitDiffEntry(
                        change_type="R",
                        old_path=parts[1].strip(),
                        path=parts[2].strip(),
                    )
                )
            elif status_code.startswith("C") and len(parts) >= 3:
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
        """Calculates real SHA-256 hash of a file on disk if it exists."""
        full_path = (self._repo_root / file_path).resolve()
        if not full_path.is_file():
            return None
        hasher = hashlib.sha256()
        with open(full_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _has_head_commit(self) -> bool:
        """Checks if HEAD commit exists in the repo."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=str(self._repo_root),
                capture_output=True,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False
