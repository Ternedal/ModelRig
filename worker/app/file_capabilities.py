"""Scoped read-only file capabilities (T-035).

The model never receives an absolute filesystem authority. A trusted operator
selects exactly one workspace through the server environment, and the tools
accept relative paths only. The surface is default-off and refuses to register
unless ToolHost process isolation is explicitly enabled.

V1 intentionally contains only read/list/search. It has no create, overwrite,
append, delete, move, rename, chmod, shell, home-directory, drive or temp access.
"""
from __future__ import annotations

import json
import ntpath
import os
import re
import stat
from dataclasses import dataclass

from .read_scope import PathDenied, ReadScope

FILE_CAPABILITIES_FLAG = "KALIV_FILE_CAPABILITIES_ENABLED"
FILE_WORKSPACE_ID_ENV = "KALIV_FILE_WORKSPACE_ID"
FILE_WORKSPACE_ROOT_ENV = "KALIV_FILE_WORKSPACE_ROOT"
TOOL_ISOLATION_ENV = "KALIV_TOOL_ISOLATION"

RESULT_SCHEMA = "kaliv-file-capability-result/v1"
RECEIPT_SCHEMA = "kaliv-file-capability-receipt/v1"

MAX_READ_BYTES = 12_000
MAX_LIST_ENTRIES = 50
MAX_SEARCH_RESULTS = 20
MAX_SEARCH_FILES = 500
MAX_SEARCH_TOTAL_BYTES = 1_000_000
MAX_SEARCH_FILE_BYTES = 64_000
MAX_QUERY_CHARS = 200
MAX_EXCERPT_CHARS = 240

_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_TEXT_EXTENSIONS = {
    "", ".txt", ".md", ".markdown", ".json", ".jsonl", ".ndjson",
    ".csv", ".tsv", ".log", ".ini", ".cfg", ".conf", ".toml",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".css", ".js",
    ".ts", ".kt", ".kts", ".java", ".py", ".ps1", ".bat", ".cmd",
    ".sh", ".sql", ".go", ".rs", ".c", ".h", ".cpp", ".hpp",
}
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    root: str


class FileCapabilityConfigError(RuntimeError):
    """Trusted workspace/activation configuration is invalid."""


def file_capabilities_enabled() -> bool:
    return os.getenv(FILE_CAPABILITIES_FLAG, "").strip() == "1"


def _require_process_isolation() -> None:
    value = os.getenv(TOOL_ISOLATION_ENV, "").strip().lower()
    if value != "process":
        raise FileCapabilityConfigError(
            f"{FILE_CAPABILITIES_FLAG}=1 requires {TOOL_ISOLATION_ENV}=process"
        )


def _is_link_or_reparse(path: str) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def workspace_from_environment() -> Workspace:
    workspace_id = os.getenv(FILE_WORKSPACE_ID_ENV, "")
    root_raw = os.getenv(FILE_WORKSPACE_ROOT_ENV, "")
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        raise FileCapabilityConfigError(
            f"{FILE_WORKSPACE_ID_ENV} must match {_WORKSPACE_ID.pattern}"
        )
    if not root_raw or not os.path.isabs(root_raw):
        raise FileCapabilityConfigError(
            f"{FILE_WORKSPACE_ROOT_ENV} must be an explicit absolute directory"
        )

    root = os.path.abspath(root_raw)
    if not os.path.isdir(root):
        raise FileCapabilityConfigError(
            f"{FILE_WORKSPACE_ROOT_ENV} does not name an existing directory"
        )
    if _is_link_or_reparse(root):
        raise FileCapabilityConfigError("workspace root cannot be a symlink/reparse point")

    real_root = os.path.realpath(root)
    if not _same_path(root, real_root):
        raise FileCapabilityConfigError(
            "workspace root resolves through an alias/symlink/reparse boundary"
        )
    return Workspace(workspace_id=workspace_id, root=root)


def _deny(message: str):
    from . import tools

    raise tools.ToolDenied(message)


def _validate_args(args: object, *, allowed: set[str], required: set[str]) -> dict:
    if not isinstance(args, dict):
        _deny("file capability args skal være et objekt")
    unknown = set(args) - allowed
    if unknown:
        _deny("ukendte file capability argumenter: " + ", ".join(sorted(unknown)))
    missing = required - set(args)
    if missing:
        _deny("manglende file capability argumenter: " + ", ".join(sorted(missing)))
    return args


def _normalise_relative(raw: object, *, allow_root: bool) -> str:
    if not isinstance(raw, str):
        _deny("path skal være en relativ tekststi")
    if "\x00" in raw:
        _deny("path indeholder NUL")
    if raw == "":
        if allow_root:
            return ""
        _deny("path må ikke være tom")

    drive, _tail = ntpath.splitdrive(raw)
    slash = raw.replace("\\", "/")
    if drive or slash.startswith("/") or slash.startswith("//"):
        _deny("absolutte, UNC- og drive-stier er ikke tilladt")

    parts = slash.split("/")
    for part in parts:
        if not part or part in {".", ".."}:
            _deny("path skal være kanonisk og må ikke indeholde ., .. eller tomme segmenter")
        if ":" in part:
            _deny("path må ikke indeholde drive/ADS-colon")
        if part.endswith(".") or part.endswith(" "):
            _deny("Windows-aliaser med afsluttende punktum/mellemrum afvises")
        if part.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
            _deny("Windows device-navne er ikke gyldige workspace-paths")
    return "/".join(parts)


def _commonpath_is_root(root: str, candidate: str) -> bool:
    try:
        common = os.path.commonpath([root, candidate])
    except ValueError:
        return False
    return _same_path(common, root)


def _resolve_existing(workspace: Workspace, raw: object, *, allow_root: bool) -> tuple[str, str]:
    relative = _normalise_relative(raw, allow_root=allow_root)
    parts = [] if not relative else relative.split("/")
    candidate = os.path.abspath(os.path.join(workspace.root, *parts))
    if not _commonpath_is_root(workspace.root, candidate):
        _deny("path forlader workspace")

    # Reuse the pre-existing I1 path authority instead of creating a second
    # interpretation of hostile Windows aliases. The stricter relative-only
    # rule above remains T-035-specific; ReadScope additionally pins 8.3/DOS/
    # ADS/UNC semantics that have already been measured and regression-tested.
    if relative:
        try:
            scoped = ReadScope(workspace.root).resolve(relative)
        except PathDenied as exc:
            _deny(f"read-scope afviser path: {exc}")
        if not _same_path(candidate, scoped):
            _deny("file capability path er uenig med canonical ReadScope")

    current = workspace.root
    for part in parts:
        current = os.path.join(current, part)
        try:
            os.lstat(current)
        except FileNotFoundError:
            _deny(f"workspace-path findes ikke: {relative}")
        except OSError as exc:
            _deny(f"workspace-path kan ikke valideres: {type(exc).__name__}")
        if _is_link_or_reparse(current):
            _deny("symlink/reparse-paths er ikke tilladt i workspace")

    real_candidate = os.path.realpath(candidate)
    if not _commonpath_is_root(workspace.root, real_candidate):
        _deny("resolved path forlader workspace")
    if not _same_path(candidate, real_candidate):
        _deny("path ændrer identitet ved realpath-resolution")
    return candidate, relative


def _safe_regular_file_size(workspace: Workspace, path: str, relative: str) -> int:
    """Read file metadata only while the scoped path/identity stays stable."""
    checked, checked_relative = _resolve_existing(workspace, relative, allow_root=False)
    if not _same_path(path, checked) or checked_relative != relative:
        _deny("fil-path ændrede authority før metadata-read")
    try:
        before = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        _deny(f"filmetadata kan ikke læses: {type(exc).__name__}")
    if not stat.S_ISREG(before.st_mode) or _is_link_or_reparse(path):
        _deny("filmetadata kræver en regulær workspace-fil")
    checked_after, relative_after = _resolve_existing(workspace, relative, allow_root=False)
    if not _same_path(path, checked_after) or relative_after != relative:
        _deny("fil-path ændrede authority under metadata-read")
    try:
        after = os.stat(path, follow_symlinks=False)
    except OSError:
        _deny("filen ændrede sig under metadata-read")
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        _deny("fil-identiteten ændrede sig under metadata-read")
    return int(before.st_size)


def _safe_open_bytes(workspace: Workspace, path: str, relative: str, cap: int) -> bytes:
    """Bounded read with path + identity checks around the open operation."""
    checked, checked_relative = _resolve_existing(workspace, relative, allow_root=False)
    if not _same_path(path, checked) or checked_relative != relative:
        _deny("fil-path ændrede authority før open")
    try:
        before = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        _deny(f"filen kan ikke stat'es: {type(exc).__name__}")
    if not stat.S_ISREG(before.st_mode):
        _deny("path er ikke en regulær fil")
    if _is_link_or_reparse(path):
        _deny("symlink/reparse-filer er ikke tilladt")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    fd = None
    try:
        fd = os.open(path, flags)
        opened = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            _deny("fil-identiteten ændrede sig under open")
        data = os.read(fd, cap + 1)
    except PermissionError:
        _deny("filen kan ikke læses med workspace-rettighederne")
    except OSError as exc:
        _deny(f"filen kan ikke læses: {type(exc).__name__}")
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    try:
        after = os.stat(path, follow_symlinks=False)
    except OSError:
        _deny("filen ændrede sig under læsning")
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        _deny("fil-identiteten ændrede sig under læsning")
    checked_after, relative_after = _resolve_existing(workspace, relative, allow_root=False)
    if not _same_path(path, checked_after) or relative_after != relative:
        _deny("fil-path ændrede authority under læsning")
    return data


def _safe_listdir(workspace: Workspace, directory: str, relative: str) -> list[str]:
    """List a directory only while its scoped identity stays stable."""
    checked, checked_relative = _resolve_existing(workspace, relative, allow_root=True)
    if not _same_path(directory, checked) or checked_relative != relative:
        _deny("mappe-path ændrede authority før listing")
    try:
        before = os.stat(directory, follow_symlinks=False)
    except OSError as exc:
        _deny(f"mappen kan ikke stat'es: {type(exc).__name__}")
    if not stat.S_ISDIR(before.st_mode) or _is_link_or_reparse(directory):
        _deny("file-list/search kræver en regulær workspace-mappe")
    try:
        names = os.listdir(directory)
    except OSError as exc:
        _deny(f"mappen kan ikke listes: {type(exc).__name__}")
    try:
        after = os.stat(directory, follow_symlinks=False)
    except OSError:
        _deny("mappen ændrede sig under listing")
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        _deny("mappe-identiteten ændrede sig under listing")
    checked_after, relative_after = _resolve_existing(workspace, relative, allow_root=True)
    if not _same_path(directory, checked_after) or relative_after != relative:
        _deny("mappe-path ændrede authority under listing")
    return names


def _text_status(path: str, data: bytes) -> tuple[str, str | None]:
    extension = os.path.splitext(path)[1].lower()
    if extension not in _TEXT_EXTENSIONS:
        return "unsupported_media", None
    if b"\x00" in data:
        return "unsupported_binary", None
    try:
        return "text", data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "unsupported_encoding", None


def _receipt(workspace: Workspace, operation: str, relative_paths: list[str], summary: str) -> dict:
    return {
        "schema": RECEIPT_SCHEMA,
        "workspace_id": workspace.workspace_id,
        "operation": operation,
        "relative_paths": relative_paths,
        "result_summary": summary,
        "production_activation": False,
    }


def _render(workspace: Workspace, operation: str, *, relative_paths: list[str], summary: str, payload: dict) -> str:
    return json.dumps(
        {
            "schema": RESULT_SCHEMA,
            "workspace_id": workspace.workspace_id,
            "operation": operation,
            "production_activation": False,
            **payload,
            "receipt": _receipt(workspace, operation, relative_paths, summary),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _run_file_read(args: dict) -> str:
    args = _validate_args(args, allowed={"path"}, required={"path"})
    workspace = workspace_from_environment()
    path, relative = _resolve_existing(workspace, args["path"], allow_root=False)
    size = _safe_regular_file_size(workspace, path, relative)
    if size > MAX_READ_BYTES:
        return _render(
            workspace,
            "read",
            relative_paths=[relative],
            summary=f"unsupported_too_large size={size}",
            payload={"path": relative, "status": "unsupported_too_large", "size_bytes": size},
        )

    data = _safe_open_bytes(workspace, path, relative, MAX_READ_BYTES)
    if len(data) > MAX_READ_BYTES:
        return _render(
            workspace,
            "read",
            relative_paths=[relative],
            summary=f"unsupported_too_large size>{MAX_READ_BYTES}",
            payload={"path": relative, "status": "unsupported_too_large", "size_bytes": size},
        )
    status, text = _text_status(path, data)
    payload = {"path": relative, "status": status, "size_bytes": size}
    if text is not None:
        payload["text"] = text
    return _render(
        workspace,
        "read",
        relative_paths=[relative],
        summary=f"{status} size={size}",
        payload=payload,
    )


def _entry_kind(path: str) -> str:
    if _is_link_or_reparse(path):
        return "unsupported_link"
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return "unavailable"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    return "unsupported"


def _run_file_list(args: dict) -> str:
    args = _validate_args(args, allowed={"path", "limit"}, required=set())
    raw_path = args.get("path", "")
    limit = args.get("limit", MAX_LIST_ENTRIES)
    if type(limit) is not int or not 1 <= limit <= MAX_LIST_ENTRIES:
        _deny(f"limit skal være et heltal mellem 1 og {MAX_LIST_ENTRIES}")

    workspace = workspace_from_environment()
    directory, relative = _resolve_existing(workspace, raw_path, allow_root=True)
    if not os.path.isdir(directory):
        _deny("file_list kræver en mappe")

    names = sorted(_safe_listdir(workspace, directory, relative), key=str.casefold)

    chosen = names[:limit]
    entries: list[dict] = []
    paths: list[str] = []
    for name in chosen:
        child = os.path.join(directory, name)
        child_rel = (f"{relative}/{name}" if relative else name).replace("\\", "/")
        kind = _entry_kind(child)
        item = {"path": child_rel, "kind": kind}
        if kind == "file":
            item["size_bytes"] = _safe_regular_file_size(
                workspace, child, child_rel
            )
        entries.append(item)
        paths.append(item["path"])

    truncated = len(names) > len(chosen)
    return _render(
        workspace,
        "list",
        relative_paths=paths,
        summary=f"entries={len(entries)} truncated={str(truncated).lower()}",
        payload={
            "path": relative,
            "status": "ok",
            "entries": entries,
            "truncated": truncated,
        },
    )


def _search_file(workspace: Workspace, path: str, relative: str, query_folded: str) -> list[dict]:
    checked, checked_relative = _resolve_existing(workspace, relative, allow_root=False)
    if not _same_path(path, checked) or checked_relative != relative:
        _deny("search-file ændrede path-authority")
    size = _safe_regular_file_size(workspace, checked, relative)
    if size > MAX_SEARCH_FILE_BYTES:
        return []
    data = _safe_open_bytes(workspace, checked, relative, MAX_SEARCH_FILE_BYTES)
    if len(data) > MAX_SEARCH_FILE_BYTES:
        return []
    status, text = _text_status(checked, data)
    if status != "text" or text is None:
        return []

    matches: list[dict] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if query_folded in line.casefold():
            excerpt = line.strip()
            if len(excerpt) > MAX_EXCERPT_CHARS:
                excerpt = excerpt[:MAX_EXCERPT_CHARS] + "…"
            matches.append({"path": relative, "line": number, "excerpt": excerpt})
    return matches


def _run_file_search(args: dict) -> str:
    args = _validate_args(
        args,
        allowed={"query", "path", "max_results"},
        required={"query"},
    )
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        _deny("query skal være ikke-tom tekst")
    if len(query) > MAX_QUERY_CHARS:
        _deny(f"query må højst være {MAX_QUERY_CHARS} tegn")
    max_results = args.get("max_results", MAX_SEARCH_RESULTS)
    if type(max_results) is not int or not 1 <= max_results <= MAX_SEARCH_RESULTS:
        _deny(f"max_results skal være et heltal mellem 1 og {MAX_SEARCH_RESULTS}")

    workspace = workspace_from_environment()
    start, start_relative = _resolve_existing(
        workspace, args.get("path", ""), allow_root=True
    )
    if not os.path.isdir(start):
        _deny("file_search path skal være en mappe")

    query_folded = query.casefold()
    pending: list[tuple[str, str]] = [(start, start_relative)]
    visited_files = 0
    total_bytes = 0
    matches: list[dict] = []
    truncated = False

    while pending and len(matches) < max_results:
        directory, relative_dir = pending.pop()
        names = sorted(
            _safe_listdir(workspace, directory, relative_dir),
            key=str.casefold,
            reverse=True,
        )
        for name in names:
            path = os.path.join(directory, name)
            relative = f"{relative_dir}/{name}" if relative_dir else name
            relative = relative.replace("\\", "/")
            kind = _entry_kind(path)
            if kind == "directory":
                checked_dir, checked_relative = _resolve_existing(
                    workspace, relative, allow_root=False
                )
                if not _same_path(path, checked_dir) or checked_relative != relative:
                    _deny("search-directory ændrede path-authority")
                pending.append((checked_dir, checked_relative))
                continue
            if kind != "file":
                continue

            visited_files += 1
            if visited_files > MAX_SEARCH_FILES:
                truncated = True
                pending.clear()
                break
            checked_file, checked_relative = _resolve_existing(
                workspace, relative, allow_root=False
            )
            if not _same_path(path, checked_file) or checked_relative != relative:
                _deny("search-file ændrede path-authority")
            size = _safe_regular_file_size(workspace, checked_file, checked_relative)
            if size > MAX_SEARCH_FILE_BYTES:
                continue
            if total_bytes + size > MAX_SEARCH_TOTAL_BYTES:
                truncated = True
                pending.clear()
                break
            total_bytes += size
            file_matches = _search_file(
                workspace, checked_file, checked_relative, query_folded
            )
            if file_matches:
                room = max_results - len(matches)
                matches.extend(file_matches[:room])
                if len(file_matches) > room:
                    truncated = True
            if len(matches) >= max_results:
                truncated = True
                break

    matched_paths = list(dict.fromkeys(item["path"] for item in matches))
    return _render(
        workspace,
        "search",
        relative_paths=matched_paths,
        summary=(
            f"matches={len(matches)} files_scanned={min(visited_files, MAX_SEARCH_FILES)} "
            f"bytes_scanned={total_bytes} truncated={str(truncated).lower()}"
        ),
        payload={
            "path": start_relative,
            "query": query,
            "status": "ok",
            "matches": matches,
            "files_scanned": min(visited_files, MAX_SEARCH_FILES),
            "bytes_scanned": total_bytes,
            "truncated": truncated,
        },
    )


def _tool_specs():
    from . import tools

    env_allow = (
        FILE_CAPABILITIES_FLAG,
        FILE_WORKSPACE_ID_ENV,
        FILE_WORKSPACE_ROOT_ENV,
        TOOL_ISOLATION_ENV,
    )
    reason = "workspace-valg er interaktivt; v1 file-capabilities må ikke køre unattended"
    return (
        tools.Tool(
            name="file_read",
            risk="read",
            network="none",
            sensitivity="private",
            isolate=True,
            env_allow=env_allow,
            schedulable=False,
            unschedulable_because=reason,
            description="Læs en bounded UTF-8 tekstfil fra det eksplicit valgte workspace.",
            params={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            run=_run_file_read,
        ),
        tools.Tool(
            name="file_list",
            risk="read",
            network="none",
            sensitivity="private",
            isolate=True,
            env_allow=env_allow,
            schedulable=False,
            unschedulable_because=reason,
            description="List bounded metadata i en mappe under det eksplicit valgte workspace.",
            params={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIST_ENTRIES},
                },
                "additionalProperties": False,
            },
            run=_run_file_list,
        ),
        tools.Tool(
            name="file_search",
            risk="read",
            network="none",
            sensitivity="private",
            isolate=True,
            env_allow=env_allow,
            schedulable=False,
            unschedulable_because=reason,
            description="Søg bounded efter tekst i filer under det eksplicit valgte workspace.",
            params={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_CHARS},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_RESULTS},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            run=_run_file_search,
        ),
    )


def register_file_capability_tools() -> bool:
    """Register V1 only after explicit feature + isolation + workspace opt-in."""
    if not file_capabilities_enabled():
        return False
    _require_process_isolation()
    workspace_from_environment()  # validate trusted authority before mutation

    from . import tools

    specs = _tool_specs()
    for spec in specs:
        existing = tools.REGISTRY.get(spec.name)
        if existing is not None and getattr(existing, "run", None) is not spec.run:
            raise RuntimeError(f"{spec.name} is already registered by another component")

    for spec in specs:
        if spec.name not in tools.REGISTRY:
            tools.REGISTRY[spec.name] = spec
    return True
