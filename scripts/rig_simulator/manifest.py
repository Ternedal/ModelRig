#!/usr/bin/env python3
"""The rig-simulator manifest: which operators run in CI, and what each must do.

``operators.json`` is the single list of rig operators the simulator knows.
Every entry is one of two things:

``run``
    An operator the simulator executes against the simulated stack, with an
    expectation the run must meet (exit codes, JSON on stdout, a journal line,
    no traceback). This is the class of defect rig days kept finding: a path
    that does not exist on the rig, an argument the script does not take, a
    PowerShell 5.1 parse error, an environment variable set too late.

``pending``
    A script the release qualification names that the simulator cannot run yet,
    with the issue that tracks it and one line saying why. A pending entry is
    not a pass. It keeps the gap visible instead of silent.

``tests/workflow_rig_simulator.py`` loads the manifest through this module and
requires that every script `docs/KALIV_SYSTEM_RELEASE_QUALIFICATION.md` names
is either ``run`` or ``pending``. A new qualifier in the document with no
manifest entry fails CI; so does a manifest entry whose script does not exist.

This module is stdlib only and imports nothing from the worker.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCHEMA = "kaliv-rig-simulator-manifest/v1"
QUALIFICATION_DOC = Path("docs") / "KALIV_SYSTEM_RELEASE_QUALIFICATION.md"
KINDS = ("python", "powershell")
PLATFORMS = ("any", "windows")
PLACEHOLDER = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
VARIABLES = (
    "REPO",          # absolute repository root
    "HEAD_SHA",      # git rev-parse HEAD of that root
    "BACKEND_URL",   # simulated backend, loopback
    "WORKER_URL",    # simulated worker, loopback
    "OLLAMA_URL",    # mock Ollama, loopback
    "HEARTBEAT",     # a heartbeat file the simulator advances every tick
    "FRESH_WAV",     # a WAV written seconds before the operator starts
    "WORK_DIR",      # scratch directory below validation/rig-simulator/
    "PYTHON",        # the interpreter running the simulator
)
# A script the qualification document names, as it names it: either a bare
# file name in backticks or a scripts/ path. Both forms occur in the document.
DOC_SCRIPT = re.compile(r"(?<![\w/])((?:scripts/)?[A-Za-z0-9_\-]+\.(?:py|ps1|cmd))\b")


class ManifestError(ValueError):
    """The manifest is not usable; the message says which rule failed."""


@dataclass(frozen=True)
class Expect:
    exit_codes: tuple[int, ...]
    stdout_json: dict[str, Any] | None = None       # {} = any JSON object; {"schema": "..."} = fields that must match
    jsonl_last: dict[str, Any] | None = None        # {"path": "...", "fields": {...}}
    files_exist: tuple[str, ...] = ()
    allow_traceback: bool = False

    def assertions(self) -> int:
        return (
            1  # exit codes always count
            + (self.stdout_json is not None)
            + (self.jsonl_last is not None)
            + (len(self.files_exist) > 0)
        )


@dataclass(frozen=True)
class Operator:
    id: str
    script: str
    kind: str
    args: tuple[str, ...]
    expect: Expect
    why: str
    platform: str = "any"
    timeout_seconds: int = 120
    needs_stack: bool = True


@dataclass(frozen=True)
class Pending:
    script: str
    issue: int
    why: str


@dataclass(frozen=True)
class Manifest:
    operators: tuple[Operator, ...]
    pending: tuple[Pending, ...]
    path: Path
    problems: tuple[str, ...] = field(default_factory=tuple)

    def scripts(self) -> set[str]:
        return {op.script for op in self.operators} | {p.script for p in self.pending}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _expect(raw: Any, where: str) -> Expect:
    _require(isinstance(raw, dict), f"{where}: expect must be an object")
    codes = raw.get("exit")
    _require(
        isinstance(codes, list) and codes and all(isinstance(c, int) and not isinstance(c, bool) for c in codes),
        f"{where}: expect.exit must be a non-empty list of integers",
    )
    stdout_json = raw.get("stdout_json")
    _require(stdout_json is None or isinstance(stdout_json, dict), f"{where}: expect.stdout_json must be an object")
    jsonl_last = raw.get("jsonl_last")
    if jsonl_last is not None:
        _require(isinstance(jsonl_last, dict), f"{where}: expect.jsonl_last must be an object")
        _require(isinstance(jsonl_last.get("path"), str) and jsonl_last["path"], f"{where}: expect.jsonl_last.path missing")
        _require(isinstance(jsonl_last.get("fields"), dict) and jsonl_last["fields"], f"{where}: expect.jsonl_last.fields missing")
    files_exist = raw.get("files_exist", [])
    _require(isinstance(files_exist, list) and all(isinstance(f, str) for f in files_exist), f"{where}: expect.files_exist must be a list of strings")
    allow_traceback = raw.get("allow_traceback", False)
    _require(isinstance(allow_traceback, bool), f"{where}: expect.allow_traceback must be a boolean")
    unknown = set(raw) - {"exit", "stdout_json", "jsonl_last", "files_exist", "allow_traceback"}
    _require(not unknown, f"{where}: unknown expect keys {sorted(unknown)}")
    return Expect(
        exit_codes=tuple(codes),
        stdout_json=stdout_json,
        jsonl_last=jsonl_last,
        files_exist=tuple(files_exist),
        allow_traceback=allow_traceback,
    )


def _operator(raw: Any, index: int, repo_root: Path) -> Operator:
    where = f"operators[{index}]"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    op_id = raw.get("id")
    _require(isinstance(op_id, str) and re.fullmatch(r"[a-z0-9][a-z0-9\-]{2,63}", op_id or ""), f"{where}: id must be a kebab-case slug")
    where = f"operators[{op_id}]"
    script = raw.get("script")
    _require(isinstance(script, str) and script and not Path(script).is_absolute() and ".." not in Path(script).parts, f"{where}: script must be a repository-relative path")
    _require((repo_root / script).is_file(), f"{where}: script {script} does not exist")
    kind = raw.get("kind")
    _require(kind in KINDS, f"{where}: kind must be one of {KINDS}")
    _require(not (kind == "python" and not script.endswith(".py")), f"{where}: a python operator must be a .py file")
    _require(not (kind == "powershell" and not script.endswith(".ps1")), f"{where}: a powershell operator must be a .ps1 file")
    platform = raw.get("platform", "any")
    _require(platform in PLATFORMS, f"{where}: platform must be one of {PLATFORMS}")
    _require(not (kind == "powershell" and platform != "windows"), f"{where}: a powershell operator must declare platform windows")
    args = raw.get("args", [])
    _require(isinstance(args, list) and all(isinstance(a, str) for a in args), f"{where}: args must be a list of strings")
    for arg in args:
        for name in PLACEHOLDER.findall(arg):
            _require(name in VARIABLES, f"{where}: unknown placeholder ${{{name}}}")
    why = raw.get("why")
    _require(isinstance(why, str) and len(why.strip()) >= 20, f"{where}: why must say in a sentence what the run proves")
    timeout = raw.get("timeout_seconds", 120)
    _require(isinstance(timeout, int) and 5 <= timeout <= 1800, f"{where}: timeout_seconds must be 5..1800")
    needs_stack = raw.get("needs_stack", True)
    _require(isinstance(needs_stack, bool), f"{where}: needs_stack must be a boolean")
    expect = _expect(raw.get("expect"), where)
    unknown = set(raw) - {"id", "script", "kind", "platform", "args", "why", "timeout_seconds", "needs_stack", "expect"}
    _require(not unknown, f"{where}: unknown keys {sorted(unknown)}")
    return Operator(
        id=op_id, script=script, kind=kind, args=tuple(args), expect=expect, why=why.strip(),
        platform=platform, timeout_seconds=timeout, needs_stack=needs_stack,
    )


def _pending(raw: Any, index: int, repo_root: Path) -> Pending:
    where = f"pending[{index}]"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    script = raw.get("script")
    _require(isinstance(script, str) and script and (repo_root / script).is_file(), f"{where}: script {script!r} does not exist")
    issue = raw.get("issue")
    _require(isinstance(issue, int) and not isinstance(issue, bool) and issue > 0, f"{where}: issue must be a positive issue number")
    why = raw.get("why")
    _require(isinstance(why, str) and len(why.strip()) >= 20, f"{where}: why must say in a sentence what blocks the run")
    unknown = set(raw) - {"script", "issue", "why"}
    _require(not unknown, f"{where}: unknown keys {sorted(unknown)}")
    return Pending(script=script, issue=issue, why=why.strip())


def load_manifest(path: Path, repo_root: Path) -> Manifest:
    """Parse and validate; raise ManifestError on the first rule that fails."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{path}: cannot read manifest: {exc}") from exc
    _require(isinstance(raw, dict), "manifest must be an object")
    _require(raw.get("schema") == SCHEMA, f"manifest schema must be {SCHEMA}")
    operators_raw = raw.get("operators")
    _require(isinstance(operators_raw, list) and operators_raw, "manifest needs a non-empty operators list")
    pending_raw = raw.get("pending", [])
    _require(isinstance(pending_raw, list), "pending must be a list")
    unknown = set(raw) - {"schema", "operators", "pending"}
    _require(not unknown, f"unknown manifest keys {sorted(unknown)}")

    operators = tuple(_operator(item, i, repo_root) for i, item in enumerate(operators_raw))
    ids = [op.id for op in operators]
    _require(len(ids) == len(set(ids)), f"duplicate operator ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    pending = tuple(_pending(item, i, repo_root) for i, item in enumerate(pending_raw))
    run_scripts = {op.script for op in operators}
    both = run_scripts & {p.script for p in pending}
    _require(not both, f"scripts listed as both run and pending: {sorted(both)}")
    return Manifest(operators=operators, pending=pending, path=path)


def referenced_scripts(doc_text: str, repo_root: Path) -> set[str]:
    """Scripts the qualification document names, normalised to scripts/<name>.

    Only names that exist under scripts/ count: the document also mentions
    evidence file names and qualifiers that live in sister repositories.
    """
    found: set[str] = set()
    for match in DOC_SCRIPT.finditer(doc_text):
        name = match.group(1)
        relative = name if name.startswith("scripts/") else f"scripts/{name}"
        if (repo_root / relative).is_file():
            found.add(relative)
    return found


def coverage_gaps(manifest: Manifest, referenced: set[str]) -> list[str]:
    """Referenced scripts that are neither run nor pending."""
    return sorted(referenced - manifest.scripts())


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("operators.json"))
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    try:
        manifest = load_manifest(args.manifest, root)
    except ManifestError as exc:
        print(f"MANIFEST INVALID: {exc}")
        return 1
    doc = (root / QUALIFICATION_DOC).read_text(encoding="utf-8")
    gaps = coverage_gaps(manifest, referenced_scripts(doc, root))
    print(json.dumps({
        "schema": SCHEMA,
        "operators": [op.id for op in manifest.operators],
        "pending": [p.script for p in manifest.pending],
        "coverage_gaps": gaps,
    }, indent=2))
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
