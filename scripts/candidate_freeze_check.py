#!/usr/bin/env python3
"""Freeze an unpublished physical-validation candidate without weakening release freeze.

This is the pre-release half of the staged physical promotion contract. It is
explicitly different from ``freeze_check.py``:

* ``freeze_check.py`` proves an exact published release and remains unchanged;
* this command proves one unpublished, pushed candidate SHA is coherent, contains
  current ``origin/main`` and has all four software gates green on that exact SHA;
* its receipt always says release validation is still pending and production is
  not activated.

Usage from the repository root:

    python scripts/candidate_freeze_check.py --expected-sha <40-hex-sha>

A GitHub token must be supplied through ``GITHUB_TOKEN`` or ``GH_TOKEN``. The
command never changes git state or runtime configuration. It writes one ignored
receipt under ``validation/`` only after every check passes.
"""
from __future__ import annotations

# Candidate inspection must not create the bytecode that its own freeze gate
# correctly forbids. Set both interpreter and child-process contracts before
# importing the worker fingerprint module or invoking version_tool.
import os
import sys
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
REPO = "Ternedal/ModelRig"
SCHEMA = "kaliv-pre-release-candidate-freeze/v1"
DEFAULT_REPORT = Path("validation/pre-release-candidate-freeze-latest.json")
REQUIRED_WORKFLOWS = (
    "ci",
    "agent3-diagnostics",
    "agent3-full-diagnostics",
    "codeql",
)
MAX_JSON_BYTES = 1024 * 1024
MAX_AGE_HOURS = 24.0
_CLOCK_SKEW = timedelta(minutes=5)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


class CandidateFreezeError(RuntimeError):
    """The unpublished candidate cannot be frozen truthfully."""


def _run(root: Path, *args: str) -> tuple[int, str]:
    try:
        process = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CandidateFreezeError(f"command could not complete: {' '.join(args)}") from exc
    return process.returncode, (process.stdout or process.stderr or "").strip()


def _api(url: str, token: str) -> Any:
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _build_fingerprint(root: Path) -> str:
    path = root / "worker" / "app" / "build_identity.py"
    spec = importlib.util.spec_from_file_location("candidate_build_identity", path)
    if spec is None or spec.loader is None:
        raise CandidateFreezeError("worker build identity module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.code_fingerprint()
    if not isinstance(value, str) or _SHA64.fullmatch(value) is None:
        raise CandidateFreezeError("worker code fingerprint is invalid")
    return value


def _tracked_tree(root: Path) -> tuple[list[str], str]:
    code, output = _run(root, "git", "ls-tree", "-r", "--name-only", "HEAD")
    if code != 0:
        raise CandidateFreezeError("git could not list the committed candidate tree")
    paths = sorted(line for line in output.splitlines() if line)
    if not paths:
        raise CandidateFreezeError("candidate tree contains no tracked files")
    lines: list[str] = []
    for relative in paths:
        path = root / relative
        try:
            body = path.read_bytes()
        except OSError as exc:
            raise CandidateFreezeError(f"tracked candidate file is missing: {relative}") from exc
        blob = hashlib.sha1(b"blob %d\x00" % len(body) + body).hexdigest()
        lines.append(f"{relative}:{blob}")
    rollup = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return paths, rollup


def _stray_bytecode(root: Path) -> list[str]:
    found: list[str] = []
    for directory, dirnames, filenames in os.walk(root):
        relative_dir = Path(directory).resolve().relative_to(root.resolve())
        if relative_dir == Path("."):
            dirnames[:] = [name for name in dirnames if name not in {".git", "validation"}]
        if "__pycache__" in relative_dir.parts:
            for filename in filenames:
                found.append((relative_dir / filename).as_posix())
            continue
        for filename in filenames:
            if filename.endswith(".pyc"):
                found.append((relative_dir / filename).as_posix())
    return sorted(found)


def _workflow_checks(runs: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    verdicts: dict[str, str] = {}
    errors: list[str] = []
    for name in REQUIRED_WORKFLOWS:
        matching = [run for run in runs if run.get("name") == name]
        if not matching:
            errors.append(f"no {name} run found for this exact candidate SHA")
            continue
        latest = matching[0]
        status = latest.get("status")
        conclusion = latest.get("conclusion")
        if status != "completed":
            errors.append(f"{name} is not complete on this exact candidate SHA ({status})")
            continue
        if conclusion != "success":
            errors.append(f"{name} did not pass on this exact candidate SHA ({conclusion})")
            continue
        verdicts[name] = "success"
    if errors:
        raise CandidateFreezeError("; ".join(errors))
    return verdicts


def _current_identity(root: Path) -> dict[str, Any]:
    code, git_sha = _run(root, "git", "rev-parse", "HEAD")
    if code != 0 or _SHA40.fullmatch(git_sha) is None:
        raise CandidateFreezeError("pre-release candidate freeze requires a git checkout")
    _, branch = _run(root, "git", "branch", "--show-current")
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CandidateFreezeError("VERSION cannot be read") from exc
    version_code, version_detail = _run(
        root, sys.executable, "scripts/version_tool.py", "check"
    )
    _, dirty = _run(root, "git", "status", "--porcelain")
    return {
        "version": version,
        "git_sha": git_sha,
        "branch": branch or None,
        "code_sha256": _build_fingerprint(root),
        "working_tree_clean": not bool(dirty),
        "dirty_entries": len(dirty.splitlines()) if dirty else 0,
        "version_stamps_consistent": version_code == 0,
        "version_check_detail": None if version_code == 0 else version_detail[-500:],
    }


def create_receipt(
    expected_sha: str,
    *,
    root: Path = ROOT,
    report_path: Path = DEFAULT_REPORT,
    token: str | None = None,
    api: Callable[[str, str], Any] = _api,
    now: datetime | None = None,
) -> dict[str, Any]:
    if _SHA40.fullmatch(expected_sha) is None:
        raise CandidateFreezeError("--expected-sha must be a lowercase 40-hex Git SHA")
    root = root.resolve()
    candidate = _current_identity(root)
    errors: list[str] = []
    if candidate["git_sha"] != expected_sha:
        errors.append(
            f"HEAD {candidate['git_sha']} does not equal expected candidate {expected_sha}"
        )
    if candidate["working_tree_clean"] is not True:
        errors.append(
            f"candidate working tree has {candidate['dirty_entries']} uncommitted change(s)"
        )
    if candidate["version_stamps_consistent"] is not True:
        errors.append("candidate version stamps are inconsistent")
    bytecode = _stray_bytecode(root)
    if bytecode:
        errors.append(
            "candidate tree contains Python bytecode: " + ", ".join(bytecode[:5])
        )
    if errors:
        raise CandidateFreezeError("; ".join(errors))

    fetch_code, fetch_detail = _run(root, "git", "fetch", "--quiet", "origin", "main")
    if fetch_code != 0:
        raise CandidateFreezeError(
            "current origin/main could not be fetched: " + fetch_detail[-300:]
        )
    main_code, main_sha = _run(root, "git", "rev-parse", "origin/main")
    if main_code != 0 or _SHA40.fullmatch(main_sha) is None:
        raise CandidateFreezeError("fetched origin/main SHA is unavailable")
    ancestor_code, _ = _run(
        root, "git", "merge-base", "--is-ancestor", main_sha, expected_sha
    )
    if ancestor_code != 0:
        raise CandidateFreezeError(
            f"candidate {expected_sha} does not contain current origin/main {main_sha}"
        )

    github_token = (token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not github_token:
        raise CandidateFreezeError(
            "exact-head software checks require GITHUB_TOKEN or GH_TOKEN in the environment"
        )
    try:
        payload = api(
            f"https://api.github.com/repos/{REPO}/actions/runs"
            f"?head_sha={expected_sha}&per_page=50",
            github_token,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise CandidateFreezeError("GitHub software-check status could not be read") from exc
    runs = payload.get("workflow_runs", []) if isinstance(payload, Mapping) else []
    if not isinstance(runs, list):
        raise CandidateFreezeError("GitHub workflow response is malformed")
    checks = _workflow_checks(runs)
    tree_paths, tree_sha256 = _tracked_tree(root)
    generated = now or datetime.now(timezone.utc)
    receipt = {
        "schema": SCHEMA,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "candidate": candidate,
        "main_anchor": {
            "git_sha": main_sha,
            "ancestor_of_candidate": True,
        },
        "software_checks": checks,
        "tree": {
            "files": len(tree_paths),
            "paths": tree_paths,
            "sha256": tree_sha256,
        },
        "gate": {
            "passed": True,
            "candidate_freeze_complete": True,
            "release_validation_pending": True,
            "release_complete": False,
            "production_activation": False,
        },
    }
    destination = report_path if report_path.is_absolute() else root / report_path
    if destination.is_symlink():
        raise CandidateFreezeError("candidate freeze report path must not be a symlink")
    try:
        destination.resolve().relative_to((root / "validation").resolve())
    except ValueError as exc:
        raise CandidateFreezeError("candidate freeze report must remain under validation/") from exc
    _write_json_atomic(destination, receipt)
    return receipt


def load_receipt(
    root: Path = ROOT,
    *,
    path: Path = DEFAULT_REPORT,
    expected_candidate: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    source = path if path.is_absolute() else root / path
    if source.is_symlink() or not source.exists() or not source.is_file():
        raise CandidateFreezeError("pre-release candidate freeze receipt is missing or irregular")
    size = source.stat().st_size
    if size <= 0 or size > MAX_JSON_BYTES:
        raise CandidateFreezeError("pre-release candidate freeze receipt size is invalid")
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateFreezeError("pre-release candidate freeze receipt is invalid JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise CandidateFreezeError("pre-release candidate freeze schema mismatch")
    generated_raw = value.get("generated_at")
    try:
        generated = datetime.fromisoformat(str(generated_raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateFreezeError("candidate freeze generated_at is invalid") from exc
    if generated.tzinfo is None:
        raise CandidateFreezeError("candidate freeze generated_at lacks timezone")
    current_time = now or datetime.now(timezone.utc)
    generated = generated.astimezone(timezone.utc)
    if generated > current_time + _CLOCK_SKEW:
        raise CandidateFreezeError("candidate freeze receipt is from the future")
    age = current_time - generated
    if age > timedelta(hours=MAX_AGE_HOURS):
        raise CandidateFreezeError(
            f"candidate freeze receipt is {age.total_seconds() / 3600:.1f}h old"
        )

    gate = value.get("gate") if isinstance(value.get("gate"), dict) else {}
    if gate != {
        "passed": True,
        "candidate_freeze_complete": True,
        "release_validation_pending": True,
        "release_complete": False,
        "production_activation": False,
    }:
        raise CandidateFreezeError("candidate freeze gate flags are not exact")
    checks = value.get("software_checks")
    if checks != {name: "success" for name in REQUIRED_WORKFLOWS}:
        raise CandidateFreezeError("candidate freeze software-check set is incomplete")

    recorded = value.get("candidate")
    if not isinstance(recorded, dict):
        raise CandidateFreezeError("candidate freeze identity is missing")
    actual = _current_identity(root)
    for key in ("version", "git_sha", "code_sha256"):
        if recorded.get(key) != actual.get(key):
            raise CandidateFreezeError(f"candidate freeze {key} no longer matches checkout")
    if actual.get("working_tree_clean") is not True:
        raise CandidateFreezeError("candidate checkout became dirty after freeze")
    if actual.get("version_stamps_consistent") is not True:
        raise CandidateFreezeError("candidate version stamps drifted after freeze")
    if expected_candidate is not None:
        for key in ("version", "git_sha", "code_sha256"):
            if expected_candidate.get(key) != recorded.get(key):
                raise CandidateFreezeError(f"candidate freeze {key} mismatches campaign candidate")

    main_anchor = value.get("main_anchor")
    if not isinstance(main_anchor, dict) or main_anchor.get("ancestor_of_candidate") is not True:
        raise CandidateFreezeError("candidate freeze main anchor is missing")
    main_sha = main_anchor.get("git_sha")
    if not isinstance(main_sha, str) or _SHA40.fullmatch(main_sha) is None:
        raise CandidateFreezeError("candidate freeze main SHA is invalid")
    ancestor_code, _ = _run(
        root, "git", "merge-base", "--is-ancestor", main_sha, recorded["git_sha"]
    )
    if ancestor_code != 0:
        raise CandidateFreezeError("recorded main anchor is not an ancestor of candidate")

    tree = value.get("tree") if isinstance(value.get("tree"), dict) else {}
    paths = tree.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(item, str) and item for item in paths):
        raise CandidateFreezeError("candidate freeze tree path list is invalid")
    if len(paths) != len(set(paths)) or paths != sorted(paths):
        raise CandidateFreezeError("candidate freeze tree path list is not canonical")
    current_paths, current_rollup = _tracked_tree(root)
    if paths != current_paths or tree.get("files") != len(current_paths):
        raise CandidateFreezeError("candidate tracked path set changed after freeze")
    if tree.get("sha256") != current_rollup:
        raise CandidateFreezeError("candidate tree rollup changed after freeze")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        receipt = create_receipt(args.expected_sha, report_path=args.report)
    except CandidateFreezeError as exc:
        print(f"NOT FROZEN — {exc}", file=sys.stderr)
        return 1
    candidate = receipt["candidate"]
    print(
        "FROZEN PRE-RELEASE CANDIDATE — "
        f"{candidate['version']} @ {candidate['git_sha']}"
    )
    print("release validation pending; production_activation=false")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
