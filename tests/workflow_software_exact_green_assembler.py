#!/usr/bin/env python3
"""Contract for scripts/kaliv_software_exact_green_assembler.py (V1 gate 1).

GitHub is replaced by an in-memory API with the same paths and paging. Every
assembled file goes through the real qualifier.

Run: python3 tests/workflow_software_exact_green_assembler.py
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kaliv_software_exact_green_assembler.py"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


asm = _load("software_exact_green_assembler", SCRIPT)
qualifier = _load("software_exact_green_qualifier_for_test", ROOT / "scripts" / "kaliv_software_exact_green_qualifier.py")

PINS = {
    "modelrig": "1" * 40,
    "bodyrig": "2" * 40,
    "visionrig": "3" * 40,
    "voicerig": "4" * 40,
}
CHECKS = 0
FAILED: list[str] = []


def check(condition: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILED.append(label)
        print(f"  FAIL: {label}")


def run(rid: int, name: str, sha: str, conclusion: str = "success", status: str = "completed",
        created: str = "2026-11-14T10:00:00Z", attempt: int = 1) -> dict[str, Any]:
    return {"id": rid, "run_attempt": attempt, "name": name, "path": f".github/workflows/{name}.yml",
            "event": "push", "head_sha": sha, "status": status, "conclusion": conclusion,
            "created_at": created, "html_url": f"https://example.invalid/runs/{rid}", "extra": "dropped"}


def check_run(cid: int, name: str, sha: str, conclusion: str | None = "success", status: str = "completed") -> dict[str, Any]:
    return {"id": cid, "name": name, "app": {"slug": "github-actions"}, "head_sha": sha,
            "status": status, "conclusion": conclusion, "completed_at": "2026-11-14T10:05:00Z"}


class FakeGitHub:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.commits: dict[tuple[str, str], str] = {}
        self.runs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.checks: dict[tuple[str, str], list[dict[str, Any]]] = {}
        rid = 1000
        for slot, (repository, required) in asm.REPOSITORIES.items():
            sha = PINS[slot]
            self.commits[(repository, sha)] = sha
            self.runs[(repository, sha)] = []
            for name in required:
                rid += 1
                self.runs[(repository, sha)].append(run(rid, name, sha))
            self.checks[(repository, sha)] = [check_run(rid * 10 + i, f"job-{i}", sha) for i in range(3)]

    def __call__(self, path: str) -> Any:
        self.calls.append(path)
        parsed = urllib.parse.urlsplit(path)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        parts = parsed.path.split("/")
        repository = "/".join(parts[1:3])
        page, per = int(query.get("page", 1)), int(query.get("per_page", 30))
        if parts[3] == "commits" and len(parts) == 5:
            sha = self.commits.get((repository, parts[4]))
            if sha is None:
                raise asm.AssemblerError(f"gh api {path} failed: HTTP 422 No commit found")
            return {"sha": sha}
        if parts[3] == "actions":
            items = self.runs.get((repository, query["head_sha"]), [])
            key = "workflow_runs"
        else:
            items = self.checks.get((repository, parts[4]), [])
            key = "check_runs"
        return {"total_count": len(items), key: copy.deepcopy(items[(page - 1) * per: page * per])}


def refused(github: FakeGitHub, needle: str, label: str, pins: dict[str, str] | None = None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        try:
            asm.assemble(pins or PINS, out, api=github, qualifier=qualifier)
        except asm.AssemblerError as exc:
            check(needle in str(exc), f"{label}: {exc}")
        else:
            check(False, f"{label}: was not refused")
        check(not out.exists(), f"{label}: nothing is written")


def everything_green_assembles() -> None:
    github = FakeGitHub()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        record = asm.assemble(PINS, out, api=github, qualifier=qualifier)
        names = sorted(p.name for p in out.iterdir())
        check(names == sorted([*(f"{s}-github-actions.json" for s in PINS),
                               "software-exact-green-evidence.json", "software-exact-green-assembly.json"]),
              f"the directory holds exactly the captures, evidence and record: {names}")
        evidence = json.loads((out / "software-exact-green-evidence.json").read_bytes())
        verdict = qualifier.qualify(evidence)
        check(verdict["state"] == "QUALIFIED", "the written evidence qualifies with the real qualifier")
        check(record["qualifier_verdict"] == verdict, "the record carries that verdict")
        for entry, slot in zip(evidence["repositories"], PINS):
            capture = (out / f"{slot}-github-actions.json").read_bytes()
            digest = hashlib.sha256(capture).hexdigest()
            check(entry["evidence_ref"].endswith(":sha256:" + digest), f"{slot}: the reference binds its capture file")
            check(f"@{PINS[slot]}:exact-head-run:" in entry["evidence_ref"], f"{slot}: the reference names pin and run")
            judged = json.loads(capture)
            check("extra" not in json.dumps(judged), f"{slot}: the capture keeps only judged fields")
            check(set(judged["judged_runs"]) == set(asm.REPOSITORIES[slot][1]), f"{slot}: every required run is kept")
        check(all("/repos/" not in c and not c.startswith("/") for c in github.calls), "relative REST paths only")
        check(not [p for p in Path(tmp).rglob("*.staged")], "no staged files left")


def a_missing_exact_head_run_refuses() -> None:
    github = FakeGitHub()
    key = ("Ternedal/VisionRig", PINS["visionrig"])
    github.runs[key] = [r for r in github.runs[key] if r["name"] != asm.EXACT_HEAD]
    refused(github, "dispatch it for the pin", "VisionRig without exact-head")


def the_newest_run_decides() -> None:
    github = FakeGitHub()
    key = ("Ternedal/BodyRig", PINS["bodyrig"])
    github.runs[key].append(run(9001, asm.EXACT_HEAD, PINS["bodyrig"], "failure", created="2026-11-15T10:00:00Z"))
    refused(github, "newest exact-head-qualification run 9001 is completed/failure", "a newer failed run")

    github = FakeGitHub()
    github.runs[key].append(run(9002, asm.EXACT_HEAD, PINS["bodyrig"], "failure", created="2026-11-13T10:00:00Z"))
    with tempfile.TemporaryDirectory() as tmp:
        asm.assemble(PINS, Path(tmp) / "out", api=github, qualifier=qualifier)
        evidence = json.loads((Path(tmp) / "out" / "software-exact-green-evidence.json").read_bytes())
        ref = [e for e in evidence["repositories"] if e["repository"] == "Ternedal/BodyRig"][0]["evidence_ref"]
        check(":exact-head-run:9002/" not in ref, "an older failure followed by a success passes, citing the success")

    github = FakeGitHub()
    key = ("Ternedal/ModelRig", PINS["modelrig"])
    github.runs[key].append(run(9003, "ci", PINS["modelrig"], None, status="in_progress", created="2026-11-15T10:00:00Z"))
    refused(github, "newest ci run 9003 is in_progress/None", "a required run still in progress")


def one_bad_check_run_refuses() -> None:
    for conclusion, status in (("failure", "completed"), ("cancelled", "completed"), ("timed_out", "completed"),
                               ("action_required", "completed"), (None, "in_progress"), (None, "queued")):
        github = FakeGitHub()
        github.checks[("Ternedal/VoiceRig", PINS["voicerig"])].append(
            check_run(77, "late-job", PINS["voicerig"], conclusion, status))
        refused(github, "check run 'late-job'", f"a check run {status}/{conclusion}")
    github = FakeGitHub()
    github.checks[("Ternedal/VoiceRig", PINS["voicerig"])].append(check_run(78, "skip", PINS["voicerig"], "skipped"))
    with tempfile.TemporaryDirectory() as tmp:
        asm.assemble(PINS, Path(tmp) / "out", api=github, qualifier=qualifier)
        check(True, "skipped check runs pass")
    github = FakeGitHub()
    github.checks[("Ternedal/VoiceRig", PINS["voicerig"])] = []
    refused(github, "no check runs on the commit", "a commit without check runs")


def paging_reaches_every_check_run() -> None:
    github = FakeGitHub()
    key = ("Ternedal/ModelRig", PINS["modelrig"])
    github.checks[key] = [check_run(5000 + i, f"job-{i}", PINS["modelrig"]) for i in range(230)]
    github.checks[key][-1]["conclusion"] = "failure"
    refused(github, "check run 'job-229'", "a failure on the third page")
    pages = [c for c in github.calls if "check-runs" in c and "ModelRig" in c]
    check(len(pages) == 3, f"three pages were read: {pages}")


def runs_for_another_commit_do_not_count() -> None:
    github = FakeGitHub()
    key = ("Ternedal/VoiceRig", PINS["voicerig"])
    for r in github.runs[key]:
        if r["name"] == asm.EXACT_HEAD:
            r["head_sha"] = "9" * 40
    refused(github, "no exact-head-qualification run for the pin", "an exact-head run for another commit")
    github = FakeGitHub()
    github.checks[key].append(check_run(79, "other-commit", "9" * 40, "failure"))
    with tempfile.TemporaryDirectory() as tmp:
        asm.assemble(PINS, Path(tmp) / "out", api=github, qualifier=qualifier)
        check(True, "a failed check run on another commit is not this pin's")


def pins_are_exact() -> None:
    for bad in ("main", "v2.0.20", "1" * 12, "A" * 40, "1" * 41):
        pins = dict(PINS, modelrig=bad)
        refused(FakeGitHub(), "full lowercase 40-hex SHA", f"pin {bad!r}", pins)
    github = FakeGitHub()
    github.commits[("Ternedal/BodyRig", PINS["bodyrig"])] = "5" * 40
    refused(github, "is not a commit of that repository", "a pin GitHub resolves to another commit")
    refused(FakeGitHub(), "exactly one pin per core repository", "a missing pin",
            {k: v for k, v in PINS.items() if k != "voicerig"})


def the_qualifier_decides_before_writing() -> None:
    class Refuses:
        def qualify(self, _value: Any) -> Any:
            raise qualifier.SoftwareExactGreenError("refused for the test")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        try:
            asm.assemble(PINS, out, api=FakeGitHub(), qualifier=Refuses())
        except asm.AssemblerError as exc:
            check("refused for the test" in str(exc), "the qualifier's reason is passed on")
        else:
            check(False, "a qualifier refusal stops the assembly")
        check(not out.exists(), "and nothing is written")


def an_existing_directory_is_not_reused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        out.mkdir()
        (out / "keep.txt").write_text("mine")
        try:
            asm.assemble(PINS, out, api=FakeGitHub(), qualifier=qualifier)
        except asm.AssemblerError as exc:
            check("new directory" in str(exc), str(exc))
        else:
            check(False, "an existing directory is refused")
        check(sorted(p.name for p in out.iterdir()) == ["keep.txt"], "and left as it was")


def command_line() -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, cwd=ROOT, timeout=60)
    check(proc.returncode == 0 and all(f"--pin-{s}" in proc.stdout for s in PINS) and "--out" in proc.stdout,
          "--help lists the four pins and --out")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--pin-modelrig", "main", "--pin-bodyrig", "2" * 40,
                           "--pin-visionrig", "3" * 40, "--pin-voicerig", "4" * 40, "--out", "unused"],
                          capture_output=True, text=True, cwd=ROOT, timeout=60)
    check(proc.returncode == 2 and json.loads(proc.stdout)["state"] == "REFUSED", "a bad pin exits 2 with REFUSED")
    check(not (ROOT / "unused").exists(), "and writes nothing")
    check(not list((ROOT / "scripts" / "__pycache__").glob("kaliv_software_exact_green_assembler*")),
          "no bytecode for the assembler")


def the_runbook_names_the_assembler() -> None:
    sys.path.insert(0, str(ROOT / "tests" / "support"))
    from source_code import code_of  # noqa: E402
    doc = code_of(ROOT / "docs" / "KALIV_SOFTWARE_EXACT_GREEN_QUALIFICATION.md")
    check("kaliv_software_exact_green_assembler.py" in doc, "the runbook names the assembler")


def main() -> None:
    for fn in (everything_green_assembles, a_missing_exact_head_run_refuses, the_newest_run_decides,
               one_bad_check_run_refuses, paging_reaches_every_check_run, runs_for_another_commit_do_not_count,
               pins_are_exact, the_qualifier_decides_before_writing, an_existing_directory_is_not_reused,
               command_line, the_runbook_names_the_assembler):
        fn()
    if FAILED:
        print(f"===== SOFTWARE EXACT-GREEN ASSEMBLER: {CHECKS - len(FAILED)} passed, {len(FAILED)} failed =====")
        raise SystemExit(1)
    print(f"===== SOFTWARE EXACT-GREEN ASSEMBLER: {CHECKS} passed, 0 failed =====")


if __name__ == "__main__":
    main()
