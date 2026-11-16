#!/usr/bin/env python3
"""Release fingerprint (ADR-SYS-002 D1, D2, D4, D7).

A commit's *release fingerprint* is a SHA-256 over every tracked path in that
commit except the documentation class, computed from the Git objects
(``git ls-tree -r <sha>``), never from the working tree. Two commits with the
same fingerprint run the same code on the rig; physical evidence gathered on
one is evidence about the other.

Three rules shape it:

* **The documentation class is a tracked list** (``release_fingerprint_exclusions.txt``
  in the repository root, one glob per line).
* **Protected prefixes can never be excluded** — everything the rig runs or a
  rig day exercises: ``worker/``, ``backend/``, ``android/``, ``desktop/``,
  ``vr/``, ``renderers/``, ``bodyrig/``, ``scripts/``, ``tests/``, ``deploy/``,
  ``tools/``, ``contracts/``, ``.github/workflows/``, ``VERSION``, and any
  runnable file by suffix (``.cmd``, ``.ps1``, ``.psm1``, ``.bat``, ``.py``,
  compared case-insensitively, as Windows does). An exclusion list whose glob
  would match one of them is rejected at load time.
* **Protected documents are always in the fingerprint**, even though they
  match ``*.md``: the three campaign runbooks the operator follows and the
  three generated state documents operators and gates read. They *are* the
  procedure or the state, not a description of it.

``equivalent(evidence_sha, pinned_sha)`` is the single rule the system release
gate and the ModelRig-bound qualifiers call (D4): the evidence commit is the
pinned commit, or an ancestor of it with the same release fingerprint.

Usage::

    python scripts/release_fingerprint.py compute [<sha>]            # JSON on stdout
    python scripts/release_fingerprint.py equivalent <evidence> <pinned>
    python scripts/release_fingerprint.py changed <from> <to>          # docs-only verdict for a main move
    python scripts/release_fingerprint.py check-exclusions

Stdlib only. Nothing here reads the network or writes to the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

sys.dont_write_bytecode = True

SCHEMA = "kaliv-release-fingerprint/v1"
EXCLUSIONS_FILE = "release_fingerprint_exclusions.txt"
ROOT = Path(__file__).resolve().parents[1]
_SHA40 = re.compile(r"^[0-9a-f]{40}$")

# D2: what the rig runs or a rig day exercises. Directory prefixes end in '/'.
PROTECTED_PREFIXES: tuple[str, ...] = (
    "worker/",
    "backend/",
    "android/",
    "desktop/",
    "vr/",
    "renderers/",
    "bodyrig/",
    "scripts/",
    "tests/",
    "deploy/",
    "tools/",
    "contracts/",
    ".github/workflows/",
)
PROTECTED_FILES: tuple[str, ...] = ("VERSION",)
PROTECTED_SUFFIXES: tuple[str, ...] = (".cmd", ".ps1", ".psm1", ".bat", ".py")

# D2 / Q1 / Q2: documents that are the procedure or the state, not a description of it.
PROTECTED_DOCUMENTS: tuple[str, ...] = (
    "RIGDAG_SIMPEL.md",
    "STAGED_PHYSICAL_PROMOTION.md",
    "STAGE_B_UPDATER_EVIDENCE.md",
    "CURRENT_STATE.md",
    "ACTIVATION_READINESS.md",
    "ROUTE_INVENTORY.md",
)


class FingerprintError(ValueError):
    """The input is not usable; the message names the rule."""


# ------------------------------------------------------------------ globs ---
def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """``**`` spans directories, ``*`` and ``?`` stay inside one path segment.

    A pattern without a slash matches the file name in any directory, as
    .gitignore does: ``*.md`` matches ``docs/a.md`` and ``README.md``.
    """
    pattern = pattern.strip().lstrip("/")
    if not pattern:
        raise FingerprintError("empty glob")
    anchored = "/" in pattern.rstrip("/")
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    body = "".join(out)
    prefix = "^" if anchored else "^(?:.*/)?"
    return re.compile(prefix + body + "$")


def is_protected(path: str) -> bool:
    """Protected paths are in the fingerprint whatever the exclusion list says."""
    if path in PROTECTED_FILES or path in PROTECTED_DOCUMENTS:
        return True
    if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
        return True
    lowered = path.lower()  # Windows is case-insensitive: run.PS1 runs
    return any(lowered.endswith(suffix) for suffix in PROTECTED_SUFFIXES)


def _protected_samples() -> list[str]:
    """One concrete path per protected class, to test a glob against."""
    samples = [prefix + "sample.txt" for prefix in PROTECTED_PREFIXES]
    samples += list(PROTECTED_FILES)
    samples += ["sample" + suffix for suffix in PROTECTED_SUFFIXES]
    samples += ["scripts/nested/sample.py", ".github/workflows/ci.yml"]
    return samples


@dataclass(frozen=True)
class Exclusions:
    globs: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]

    def excludes(self, path: str) -> bool:
        if is_protected(path):
            return False
        return any(p.match(path) for p in self.patterns)


def parse_exclusions(text: str) -> Exclusions:
    globs: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line in {"*", "**", "**/*", "/"}:
            raise FingerprintError(f"line {lineno}: glob {line!r} would exclude everything")
        regex = glob_to_regex(line)
        hit = [s for s in _protected_samples() if regex.match(s)]
        if hit:
            raise FingerprintError(f"line {lineno}: glob {line!r} would exclude protected path {hit[0]!r}")
        static = re.split(r"[*?\[]", line.lstrip("/"), maxsplit=1)[0]
        if is_protected(static) or any(static.startswith(prefix) for prefix in PROTECTED_PREFIXES):
            raise FingerprintError(f"line {lineno}: glob {line!r} lies under a protected path")
        globs.append(line)
    if not globs:
        raise FingerprintError("exclusion list is empty")
    return Exclusions(globs=tuple(globs), patterns=tuple(glob_to_regex(g) for g in globs))


def load_exclusions(repo_root: Path = ROOT) -> Exclusions:
    path = repo_root / EXCLUSIONS_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FingerprintError(f"{EXCLUSIONS_FILE} cannot be read: {exc}") from exc
    return parse_exclusions(text)


# -------------------------------------------------------------------- git ---
def _git(repo_root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout


def resolve_sha(repo_root: Path, rev: str) -> str:
    code, out = _git(repo_root, "rev-parse", "--verify", f"{rev}^{{commit}}")
    sha = out.strip()
    if code != 0 or not _SHA40.match(sha):
        raise FingerprintError(f"{rev!r} is not a commit in {repo_root}")
    return sha


def tracked_entries(repo_root: Path, sha: str) -> list[tuple[str, str, str]]:
    """(path, mode, object sha) for every blob and gitlink in the commit's tree.

    The mode is part of the identity: an executable bit, a symlink in place
    of a regular file, or a submodule pointer moved to another commit all
    change what a checkout runs, so they change the fingerprint (review
    finding on #2412). Trees are not listed by ``ls-tree -r``; blobs and
    ``commit`` entries (gitlinks) are.
    """
    code, out = _git(repo_root, "ls-tree", "-r", "-z", sha)
    if code != 0:
        raise FingerprintError(f"git ls-tree failed for {sha}")
    entries: list[tuple[str, str, str]] = []
    for record in out.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if len(parts) != 3:
            raise FingerprintError(f"unexpected ls-tree record: {record!r}")
        mode, kind, obj = parts
        if kind not in ("blob", "commit"):
            raise FingerprintError(f"unexpected ls-tree object kind {kind!r} for {path!r}")
        entries.append((path, mode, obj))
    if not entries:
        raise FingerprintError(f"commit {sha} has no tracked files")
    return sorted(entries)


def tracked_blobs(repo_root: Path, sha: str) -> list[tuple[str, str]]:
    """(path, object sha) — kept for callers that only need the pairs."""
    return [(path, obj) for path, _mode, obj in tracked_entries(repo_root, sha)]


def is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    code, _ = _git(repo_root, "merge-base", "--is-ancestor", ancestor, descendant)
    return code == 0


# ------------------------------------------------------------ fingerprint ---
def compute(repo_root: Path, rev: str = "HEAD", exclusions: Exclusions | None = None) -> dict:
    sha = resolve_sha(repo_root, rev)
    exclusions = exclusions or load_exclusions(repo_root)
    included: list[tuple[str, str, str]] = []
    excluded: list[str] = []
    for path, mode, obj in tracked_entries(repo_root, sha):
        if exclusions.excludes(path):
            excluded.append(path)
        else:
            included.append((path, mode, obj))
    digest = hashlib.sha256()
    for path, mode, obj in included:
        digest.update(mode.encode("ascii"))
        digest.update(b"\0")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(obj.encode("ascii"))
        digest.update(b"\n")
    return {
        "schema": SCHEMA,
        "git_sha": sha,
        "release_fingerprint": digest.hexdigest(),
        "included_files": len(included),
        "excluded_files": len(excluded),
        "exclusions": list(exclusions.globs),
        "protected_documents": list(PROTECTED_DOCUMENTS),
    }


def fingerprint(repo_root: Path, rev: str = "HEAD", exclusions: Exclusions | None = None) -> str:
    return compute(repo_root, rev, exclusions)["release_fingerprint"]


def equivalent(repo_root: Path, evidence_rev: str, pinned_rev: str, exclusions: Exclusions | None = None) -> tuple[bool, str]:
    """D4: evidence is the pin, or an ancestor of the pin with the same fingerprint."""
    evidence = resolve_sha(repo_root, evidence_rev)
    pinned = resolve_sha(repo_root, pinned_rev)
    if evidence == pinned:
        return True, "same commit"
    if not is_ancestor(repo_root, evidence, pinned):
        return False, f"{evidence[:12]} is not an ancestor of {pinned[:12]}"
    exclusions = exclusions or load_exclusions(repo_root)
    a = fingerprint(repo_root, evidence, exclusions)
    b = fingerprint(repo_root, pinned, exclusions)
    if a != b:
        return False, f"release fingerprint differs: {a[:12]} (evidence) vs {b[:12]} (pinned)"
    return True, "ancestor with the same release fingerprint"


def changed_paths(repo_root: Path, from_rev: str, to_rev: str) -> list[str]:
    a = resolve_sha(repo_root, from_rev)
    b = resolve_sha(repo_root, to_rev)
    code, out = _git(repo_root, "diff", "--name-only", "-z", f"{a}..{b}")
    if code != 0:
        raise FingerprintError(f"git diff failed for {a[:12]}..{b[:12]}")
    return sorted(p for p in out.split("\0") if p)


def docs_only(repo_root: Path, from_rev: str, to_rev: str, exclusions: Exclusions | None = None) -> tuple[bool, list[str]]:
    """D3: True when every path changed between the two commits is excluded (documentation class).

    Returns the offending paths otherwise. Renames and deletions count by path
    on both sides, which ``--name-only`` already lists.
    """
    exclusions = exclusions or load_exclusions(repo_root)
    offending = [p for p in changed_paths(repo_root, from_rev, to_rev) if not exclusions.excludes(p)]
    return (not offending), offending


# -------------------------------------------------------------------- cli ---
def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    p_compute = sub.add_parser("compute", help="print the release fingerprint of a commit as JSON")
    p_compute.add_argument("rev", nargs="?", default="HEAD")
    p_eq = sub.add_parser("equivalent", help="exit 0 if evidence is the pin or an ancestor with the same fingerprint")
    p_eq.add_argument("evidence")
    p_eq.add_argument("pinned")
    p_ch = sub.add_parser("changed", help="exit 0 if every path changed between two commits is in the documentation class")
    p_ch.add_argument("from_rev")
    p_ch.add_argument("to_rev")
    sub.add_parser("check-exclusions", help="validate the exclusion list")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.repository_root.resolve()
    try:
        if args.command == "compute":
            print(json.dumps(compute(root, args.rev), indent=2, sort_keys=True))
            return 0
        if args.command == "equivalent":
            ok, reason = equivalent(root, args.evidence, args.pinned)
            print(json.dumps({"schema": SCHEMA, "equivalent": ok, "reason": reason}))
            return 0 if ok else 1
        if args.command == "changed":
            ok, offending = docs_only(root, args.from_rev, args.to_rev)
            print(json.dumps({"schema": SCHEMA, "docs_only": ok, "offending_paths": offending}))
            return 0 if ok else 1
        if args.command == "check-exclusions":
            ex = load_exclusions(root)
            print(json.dumps({"schema": SCHEMA, "ok": True, "globs": list(ex.globs), "protected_documents": list(PROTECTED_DOCUMENTS)}))
            return 0
    except FingerprintError as exc:
        print(json.dumps({"schema": SCHEMA, "ok": False, "error": str(exc)}))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
