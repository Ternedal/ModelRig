"""Bounded read and literal-search access inside task-approved paths."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .contract import DevelopmentTask, normalize_repo_path


class FileAccessError(RuntimeError):
    """A requested file operation escaped or exceeded its read authority."""


@dataclass(frozen=True, slots=True)
class SearchMatch:
    path: str
    line_number: int
    line: str


class WorkspaceFiles:
    """Read UTF-8 text without granting generic filesystem access."""

    def __init__(self, task: DevelopmentTask, workspace: Path) -> None:
        self.task = task
        self.workspace = workspace.resolve()
        if not self.workspace.is_dir():
            raise FileAccessError("workspace does not exist")

    @staticmethod
    def _matches(path: str, pattern: str) -> bool:
        return (
            fnmatch.fnmatchcase(path, pattern)
            or path == pattern
            or path.startswith(pattern.rstrip("/") + "/")
        )

    def _allowed(self, path: str) -> bool:
        if path == ".git" or path.startswith(".git/"):
            return False
        return any(
            self._matches(path, pattern) for pattern in self.task.allowed_paths
        ) and not any(
            self._matches(path, pattern) for pattern in self.task.protected_paths
        )

    def _resolve(self, relative: str) -> tuple[str, Path]:
        normalized = normalize_repo_path(relative, name="path")
        if not self._allowed(normalized):
            raise FileAccessError("path is outside readable task scope")

        candidate = self.workspace / PurePosixPath(normalized)
        cursor = candidate
        while cursor != self.workspace:
            if cursor.is_symlink():
                raise FileAccessError("path contains a symlink")
            cursor = cursor.parent

        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self.workspace):
            raise FileAccessError("path escaped workspace")
        return normalized, resolved

    def read_text(
        self,
        relative: str,
        *,
        max_bytes: int = 262_144,
    ) -> str:
        upper_bound = min(self.task.budget.max_output_bytes, 4_000_000)
        if not 1 <= max_bytes <= upper_bound:
            raise FileAccessError("read bound is invalid")

        _, path = self._resolve(relative)
        if not path.is_file():
            raise FileAccessError("path is not a regular file")
        data = path.read_bytes()
        if len(data) > max_bytes:
            raise FileAccessError("file exceeds read bound")
        if b"\x00" in data:
            raise FileAccessError("binary file is not readable as text")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileAccessError("file is not UTF-8 text") from exc

    def search_text(
        self,
        query: str,
        *,
        max_results: int = 100,
        max_scan_bytes: int = 8_000_000,
        max_file_bytes: int = 262_144,
    ) -> tuple[SearchMatch, ...]:
        if (
            not isinstance(query, str)
            or not query
            or query.strip() != query
            or "\x00" in query
            or len(query.encode("utf-8")) > 512
        ):
            raise FileAccessError("query is invalid")
        if not 1 <= max_results <= 500:
            raise FileAccessError("result bound is invalid")
        if not 1_024 <= max_scan_bytes <= 64_000_000:
            raise FileAccessError("scan bound is invalid")
        if not 1 <= max_file_bytes <= 4_000_000:
            raise FileAccessError("file scan bound is invalid")

        results: list[SearchMatch] = []
        scanned = 0
        for directory, dirnames, filenames in os.walk(self.workspace):
            current = Path(directory)
            dirnames[:] = [
                name
                for name in sorted(dirnames)
                if name != ".git" and not (current / name).is_symlink()
            ]
            for filename in sorted(filenames):
                path = current / filename
                if path.is_symlink() or not path.is_file():
                    continue
                relative = path.relative_to(self.workspace).as_posix()
                if not self._allowed(relative):
                    continue

                size = path.stat().st_size
                if size > max_file_bytes:
                    continue
                scanned += size
                if scanned > max_scan_bytes:
                    raise FileAccessError("search exceeded scan budget")

                data = path.read_bytes()
                if b"\x00" in data:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue

                for line_number, line in enumerate(text.splitlines(), 1):
                    if query not in line:
                        continue
                    results.append(
                        SearchMatch(
                            path=relative,
                            line_number=line_number,
                            line=line[:1_000],
                        )
                    )
                    if len(results) >= max_results:
                        return tuple(results)
        return tuple(results)
