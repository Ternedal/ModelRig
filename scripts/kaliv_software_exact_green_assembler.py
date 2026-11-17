#!/usr/bin/env python3
"""Assemble the software_exact_green evidence (V1 gate 1) from GitHub Actions.

``kaliv_software_exact_green_qualifier.py`` takes one entry per core repository
with ``exact_head_qualified``, ``software_green`` and an evidence reference.
Until now those were typed by hand from four Actions pages, which is not
evidence. This tool reads them from GitHub for the four pins the operator
names, keeps what it read, and refuses if any repository is not green.

What it reads, per repository and pin (read-only ``gh api``)
------------------------------------------------------------
- ``commits/<sha>``: the pin exists and is exactly that commit.
- ``actions/runs?head_sha=<sha>``: every workflow run for the commit.
- ``commits/<sha>/check-runs``: every check run for the commit.

What it requires
----------------
- ``exact_head_qualified``: the newest ``exact-head-qualification`` run for
  the pin, on exactly that ``head_sha``, completed with success. VisionRig
  runs it only on ``workflow_dispatch``: dispatch it for the pin first.
- ``software_green``: the newest run of each required workflow (below)
  completed with success, and every check run on the commit completed with
  success, skipped or neutral. One failed, cancelled, timed-out or pending
  check run is enough to refuse.
- The assembled file passes the qualifier before anything is written.

What it writes
--------------
A new directory (``mkdir`` refuses an existing one, so it is this run's own)
with one ``<repo>-github-actions.json`` per repository (the
runs and check runs it judged, reduced to the fields it judged), the evidence
file, and an assembly record. Each evidence reference is::

    github-actions:<owner>/<repo>@<sha>:exact-head-run:<id>/<attempt>:sha256:<captured file>

It changes nothing on GitHub, dispatches nothing and activates nothing. A
refusal writes nothing. An I/O error while writing can leave that new
directory incomplete: delete it and run again.

Run
---
    python scripts/kaliv_software_exact_green_assembler.py `
        --pin-modelrig <sha> --pin-bodyrig <sha> --pin-visionrig <sha> --pin-voicerig <sha> `
        --out validation\\software-exact-green\\<date>

Exit code 0: QUALIFIED and written. 2: refused, nothing written.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SCHEMA = "kaliv-system/software-exact-green-evidence/v1"
CAPTURE_SCHEMA = "kaliv-system/software-exact-green-github-capture/v1"
RECORD_SCHEMA = "kaliv-system/software-exact-green-assembly/v1"
EXACT_HEAD = "exact-head-qualification"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
PER_PAGE = 100
MAX_PAGES = 10
OK_CHECK_CONCLUSIONS = {"success", "skipped", "neutral"}

# slot -> (repository, workflows whose newest run for the pin must be green)
REPOSITORIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "modelrig": ("Ternedal/ModelRig", ("ci", "codeql", "agent3-full-diagnostics", EXACT_HEAD)),
    "bodyrig": ("Ternedal/BodyRig", ("ci", "codeql", EXACT_HEAD)),
    "visionrig": ("Ternedal/VisionRig", ("tests", EXACT_HEAD)),
    "voicerig": ("Ternedal/VoiceRig", ("tests", "CodeQL", "windows-lifecycle", EXACT_HEAD)),
}


class AssemblerError(RuntimeError):
    """The evidence cannot be assembled; nothing was written."""


def gh_api(path: str) -> Any:
    """Read one GitHub REST path with the operator's ``gh`` login."""
    proc = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        capture_output=True, text=True, check=False, timeout=120,
    )
    if proc.returncode != 0:
        raise AssemblerError(f"gh api {path} failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssemblerError(f"gh api {path} did not return JSON") from exc


def _pages(api: Callable[[str], Any], path: str, key: str) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        body = api(f"{path}{'&' if '?' in path else '?'}per_page={PER_PAGE}&page={page}")
        if not isinstance(body, Mapping) or not isinstance(body.get(key), list):
            raise AssemblerError(f"{path} did not return a {key} list")
        batch = body[key]
        items.extend(batch)
        total = body.get("total_count")
        if len(batch) < PER_PAGE or (isinstance(total, int) and len(items) >= total):
            return items
    raise AssemblerError(f"{path} has more than {MAX_PAGES * PER_PAGE} entries")


def _newest(runs: list[Mapping[str, Any]], name: str) -> Mapping[str, Any] | None:
    named = [r for r in runs if r.get("name") == name]
    if not named:
        return None
    return max(named, key=lambda r: (str(r.get("created_at") or ""), int(r.get("id") or 0), int(r.get("run_attempt") or 0)))


def _run_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": run.get("id"),
        "run_attempt": run.get("run_attempt"),
        "name": run.get("name"),
        "path": run.get("path"),
        "event": run.get("event"),
        "head_sha": run.get("head_sha"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"),
        "html_url": run.get("html_url"),
    }


def _check_summary(check: Mapping[str, Any]) -> dict[str, Any]:
    app = check.get("app") if isinstance(check.get("app"), Mapping) else {}
    return {
        "id": check.get("id"),
        "name": check.get("name"),
        "app": app.get("slug"),
        "head_sha": check.get("head_sha"),
        "status": check.get("status"),
        "conclusion": check.get("conclusion"),
        "completed_at": check.get("completed_at"),
    }


def judge(slot: str, pin: str, api: Callable[[str], Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one repository at ``pin``; return (capture, judgement) or refuse."""
    repository, required = REPOSITORIES[slot]
    commit = api(f"repos/{repository}/commits/{pin}")
    if not isinstance(commit, Mapping) or commit.get("sha") != pin:
        raise AssemblerError(f"{repository}: {pin} is not a commit of that repository")

    runs = _pages(api, f"repos/{repository}/actions/runs?head_sha={pin}", "workflow_runs")
    checks = _pages(api, f"repos/{repository}/commits/{pin}/check-runs", "check_runs")
    runs = [r for r in runs if r.get("head_sha") == pin]
    checks = [c for c in checks if c.get("head_sha") == pin]

    problems: list[str] = []
    judged: dict[str, Mapping[str, Any]] = {}
    for name in required:
        run = _newest(runs, name)
        if run is None:
            hint = " (VisionRig: dispatch it for the pin)" if name == EXACT_HEAD and slot == "visionrig" else ""
            problems.append(f"no {name} run for the pin{hint}")
            continue
        judged[name] = run
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            problems.append(f"newest {name} run {run.get('id')} is {run.get('status')}/{run.get('conclusion')}")
    if not checks:
        problems.append("no check runs on the commit")
    for check in checks:
        if check.get("status") != "completed" or check.get("conclusion") not in OK_CHECK_CONCLUSIONS:
            problems.append(f"check run {check.get('name')!r} is {check.get('status')}/{check.get('conclusion')}")
    if problems:
        raise AssemblerError(f"{repository} @ {pin[:12]} is not exact-head green: " + "; ".join(problems))

    exact = judged[EXACT_HEAD]
    capture = {
        "schema": CAPTURE_SCHEMA,
        "repository": repository,
        "git_sha": pin,
        "required_workflows": list(required),
        "judged_runs": {name: _run_summary(run) for name, run in judged.items()},
        "check_runs": sorted((_check_summary(c) for c in checks), key=lambda c: (str(c["name"]), int(c["id"] or 0))),
        "production_activation": False,
    }
    judgement = {"repository": repository, "exact_run": exact}
    return capture, judgement


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def load_qualifier() -> Any:
    path = ROOT / "scripts" / "kaliv_software_exact_green_qualifier.py"
    spec = importlib.util.spec_from_file_location("kaliv_software_exact_green_qualifier", path)
    if spec is None or spec.loader is None:
        raise AssemblerError("the qualifier cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_new(path: Path, data: bytes) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".staged")
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)  # the directory is new and this run's own
    finally:
        staged.unlink(missing_ok=True)


def assemble(
    pins: Mapping[str, str],
    out: Path,
    *,
    api: Callable[[str], Any] = gh_api,
    qualifier: Any = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    if set(pins) != set(REPOSITORIES):
        raise AssemblerError("exactly one pin per core repository is required")
    for slot, pin in pins.items():
        if not isinstance(pin, str) or _SHA40.fullmatch(pin) is None:
            raise AssemblerError(f"--pin-{slot} must be a full lowercase 40-hex SHA, not a branch, tag or short SHA")
    if out.exists():
        raise AssemblerError(f"{out} already exists; every assembly gets a new directory")
    qual = qualifier if qualifier is not None else load_qualifier()

    captures: dict[str, bytes] = {}
    entries: list[dict[str, Any]] = []
    for slot in REPOSITORIES:
        capture, judgement = judge(slot, pins[slot], api)
        data = _canonical(capture)
        captures[slot] = data
        exact = judgement["exact_run"]
        entries.append({
            "repository": judgement["repository"],
            "git_sha": pins[slot],
            "exact_head_qualified": True,
            "software_green": True,
            "evidence_ref": (
                f"github-actions:{judgement['repository']}@{pins[slot]}:"
                f"exact-head-run:{exact.get('id')}/{exact.get('run_attempt')}:"
                f"sha256:{hashlib.sha256(data).hexdigest()}"
            ),
        })

    evidence = {"schema": EVIDENCE_SCHEMA, "repositories": entries, "production_activation": False}
    try:
        verdict = qual.qualify(evidence)
    except Exception as exc:  # the qualifier's own error type
        raise AssemblerError(f"the qualifier refused the assembled evidence: {exc}") from exc
    if verdict.get("state") != "QUALIFIED":
        raise AssemblerError("the qualifier did not return QUALIFIED")

    evidence_bytes = _canonical(evidence)
    record = {
        "schema": RECORD_SCHEMA,
        "assembled_at": clock().isoformat().replace("+00:00", "Z"),
        "pins": dict(pins),
        "captures_sha256": {slot: hashlib.sha256(d).hexdigest() for slot, d in captures.items()},
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "qualifier_verdict": verdict,
        "limitations": [
            "GitHub's answer at assembly time; a re-run that later fails is not seen.",
            "Required workflows are this tool's list per repository, not read from branch protection.",
        ],
        "production_activation": False,
    }

    out.mkdir(parents=True)
    for slot, data in captures.items():
        _write_new(out / f"{slot}-github-actions.json", data)
    _write_new(out / "software-exact-green-evidence.json", evidence_bytes)
    _write_new(out / "software-exact-green-assembly.json", _canonical(record))
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for slot in REPOSITORIES:
        parser.add_argument(f"--pin-{slot}", required=True, metavar="SHA")
    parser.add_argument("--out", type=Path, required=True, help="new directory for this assembly")
    args = parser.parse_args(argv)
    pins = {slot: getattr(args, f"pin_{slot}") for slot in REPOSITORIES}
    try:
        record = assemble(pins, args.out)
    except AssemblerError as exc:
        print(json.dumps({"state": "REFUSED", "error": str(exc), "production_activation": False}, indent=2))
        return 2
    print(json.dumps(record["qualifier_verdict"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
