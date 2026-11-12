#!/usr/bin/env python3
"""Behavioural contract for kaliv_repository_authority_assembler.py.

The assembler builds the repository_authority evidence file from the verdicts
that the four repositories' ``verify-repository-authority.ps1 -Json`` print.

The four fixtures below are real output, byte for byte. Each was captured on
12 Nov 2026 by running that repository's verifier in PowerShell 7.4.6 against
the fake ``gh`` of its own contract test, with passing classic protection:

- ModelRig  at ``40e38adc`` (pull request 2395)
- BodyRig   at ``9cf2c5ec``
- VisionRig at ``efe0c15c``
- VoiceRig  at ``6067684a``

The head revisions in them belong to the throw-away checkouts of those runs.
Every assembled file goes through the real qualifier, also through its command
line.

Run: python3 tests/worker_kaliv_repository_authority_assembler.py
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kaliv_repository_authority_assembler.py"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


assembler = _load("kaliv_repository_authority_assembler", SCRIPT)
qualifier = _load(
    "kaliv_repository_authority_qualifier",
    ROOT / "scripts" / "kaliv_repository_authority_qualifier.py",
)

REAL: dict[str, str] = {
    "modelrig": (
        r'{"agent3_activation_authority":false,"authority_mode":"classic","branch":"main","cla'
        r'ssic":{"errors":[],"missing_checks":[],"mode":"classic","passed":true,"pull_request_'
        r'bypass_categories":[],"required_check_app_id":15368,"required_checks":["agent3-memor'
        r'y-dpapi-windows","agent3-python","analyze (go)","analyze (python)","android-compile"'
        r',"browser-use-runtime-contract","desktop-compile","desktop-dpapi-windows","exact-hea'
        r'd-core","full-test-log","legacy-merge-tree-equivalence","test / test","test / test-w'
        r'indows-appliance","test / test-windows-tool-isolation"],"source_bound_checks":["agen'
        r't3-memory-dpapi-windows","agent3-python","analyze (go)","analyze (python)","android-'
        r'compile","browser-use-runtime-contract","desktop-compile","desktop-dpapi-windows","e'
        r'xact-head-core","full-test-log","legacy-merge-tree-equivalence","test / test","test '
        r'/ test-windows-appliance","test / test-windows-tool-isolation"],"strict_required_sta'
        r'tus_checks":true,"warnings":[],"wrong_source_checks":[]},"errors":[],"format":"model'
        r'rig-repository-authority","head_revision":"709b1dca8cf6fa70d787ae7c54cc441d57ff16b2"'
        r',"passed":true,"physical_validation_authority":false,"production_activation":false,"'
        r'protected":true,"repository":"Ternedal/ModelRig","required_status_check_app_id":1536'
        r'8,"required_status_checks":["test / test","test / test-windows-appliance","test / te'
        r'st-windows-tool-isolation","browser-use-runtime-contract","android-compile","desktop'
        r'-compile","desktop-dpapi-windows","agent3-memory-dpapi-windows","analyze (go)","anal'
        r'yze (python)","agent3-python","full-test-log","exact-head-core","legacy-merge-tree-e'
        r'quivalence"],"rulesets":{"errors":["no active branch ruleset applies to main"],"miss'
        r'ing_checks":["test / test","test / test-windows-appliance","test / test-windows-tool'
        r'-isolation","browser-use-runtime-contract","android-compile","desktop-compile","desk'
        r'top-dpapi-windows","agent3-memory-dpapi-windows","analyze (go)","analyze (python)","'
        r'agent3-python","full-test-log","exact-head-core","legacy-merge-tree-equivalence"],"m'
        r'ode":"ruleset","passed":false,"warnings":[]},"version":1,"warnings":[]}'
        '\n'
    ),
    "bodyrig": (
        r'{"authority_mode":"classic","branch":"main","classic":{"errors":[],"missing_checks":'
        r'[],"mode":"classic","passed":true,"pull_request_bypass_categories":[],"required_chec'
        r'k_app_id":15368,"required_check_sources":{"CodeQL":57789,"acceptance-windows":15368,'
        r'"adapter-log-handle":15368,"test (3.11)":15368,"test (3.12)":15368,"test-windows-pyt'
        r'hon":15368},"required_checks":["CodeQL","acceptance-windows","adapter-log-handle","t'
        r'est (3.11)","test (3.12)","test-windows-python"],"source_bound_checks":["CodeQL","ac'
        r'ceptance-windows","adapter-log-handle","test (3.11)","test (3.12)","test-windows-pyt'
        r'hon"],"strict_required_status_checks":true,"warnings":[],"wrong_source_checks":[]},"'
        r'errors":[],"format":"bodyrig-repository-authority","head_revision":"35920cae2eea366b'
        r'f4305060912aca2d8f5636db","passed":true,"physical_acceptance_authority":false,"produ'
        r'ction_activation":false,"protected":true,"repository":"Ternedal/BodyRig","required_s'
        r'tatus_check_app_id":15368,"required_status_check_sources":{"CodeQL":57789,"acceptanc'
        r'e-windows":15368,"adapter-log-handle":15368,"test (3.11)":15368,"test (3.12)":15368,'
        r'"test-windows-python":15368},"required_status_checks":["test (3.11)","test (3.12)","'
        r'test-windows-python","acceptance-windows","adapter-log-handle","CodeQL"],"rulesets":'
        r'{"errors":["no active branch ruleset applies to main"],"missing_checks":["test (3.11'
        r')","test (3.12)","test-windows-python","acceptance-windows","adapter-log-handle","Co'
        r'deQL"],"mode":"ruleset","passed":false,"warnings":[]},"version":1,"warnings":[]}'
        '\n'
    ),
    "visionrig": (
        r'{"format":"visionrig-repository-authority","version":1,"repository":"Ternedal/Vision'
        r'Rig","branch":"main","head_revision":"9ab6f1e2b7d67cf93fb80160fad66d4d096b4f5c","git'
        r'hub_head_revision":"9ab6f1e2b7d67cf93fb80160fad66d4d096b4f5c","protected":true,"auth'
        r'ority_mode":"classic","required_status_checks":[{"context":"test","app_id":15368}],"'
        r'passed":true,"errors":[],"production_activation":false}'
        '\n'
    ),
    "voicerig": (
        r'{"format":"voicerig-repository-authority","version":1,"repository":"Ternedal/VoiceRi'
        r'g","branch":"main","head_revision":"e1f901cbf1da74f73eedd60aeb45ee69f41244b3","githu'
        r'b_head_revision":"e1f901cbf1da74f73eedd60aeb45ee69f41244b3","protected":true,"author'
        r'ity_mode":"classic","required_status_checks":[{"context":"unit","app_id":15368},{"co'
        r'ntext":"packaged-contract","app_id":15368},{"context":"ownership-smoke","app_id":153'
        r'68},{"context":"windows-service-smoke","app_id":15368},{"context":"Analyze (python)"'
        r',"app_id":15368},{"context":"Analyze (javascript-typescript)","app_id":15368}],"pass'
        r'ed":true,"errors":[],"production_activation":false}'
        '\n'
    ),
}
SLOTS = ("modelrig", "bodyrig", "visionrig", "voicerig")
PINS = {slot: json.loads(REAL[slot])["head_revision"] for slot in SLOTS}

CHECKS = 0


def check(condition: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(label)


class Case:
    """One evidence directory with the four captured verdicts in it."""

    def __init__(self, base: Path) -> None:
        self.dir = base
        self.files = {slot: base / f"{slot}.json" for slot in SLOTS}
        for slot in SLOTS:
            self.files[slot].write_bytes(REAL[slot].encode("utf-8"))
        self.pins = dict(PINS)
        self.output = base / "repository-authority-evidence.json"
        self.record = base / "repository-authority-evidence-assembly.json"

    def edit(self, slot: str, change: Callable[[dict], None]) -> None:
        verdict = json.loads(REAL[slot])
        change(verdict)
        self.files[slot].write_text(
            json.dumps(verdict, separators=(",", ":")) + "\n", encoding="utf-8"
        )

    def assemble(self, **overrides: Any) -> dict:
        arguments: dict[str, Any] = {
            "verdict_files": self.files,
            "pins": self.pins,
            "output": self.output,
            "record": self.record,
        }
        arguments.update(overrides)
        return assembler.assemble(**arguments)

    def refused(self, fragment: str, label: str, **overrides: Any) -> None:
        before = sorted(path.name for path in self.dir.iterdir())
        try:
            self.assemble(**overrides)
        except assembler.AssemblerError as exc:
            check(fragment in str(exc), f"{label}: wrong reason: {exc}")
        else:
            raise AssertionError(f"{label}: was not refused")
        after = sorted(path.name for path in self.dir.iterdir())
        check(before == after, f"{label}: a refusal wrote {set(after) - set(before)}")

    def cli(self, *extra: str) -> subprocess.CompletedProcess:
        command = [sys.executable, str(SCRIPT)]
        for slot in SLOTS:
            command += [f"--{slot}", str(self.files[slot]), f"--pin-{slot}", self.pins[slot]]
        command += ["--output", str(self.output), *extra]
        return subprocess.run(command, capture_output=True, text=True, timeout=120)


def case(run: Callable[[Case], None]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        run(Case(Path(tmp)))


def qualifier_cli(path: Path) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = qualifier.main([str(path)])
    return code, json.loads(buffer.getvalue())


# --------------------------------------------------------------------------
# The four real verdicts
# --------------------------------------------------------------------------

def real_verdicts_assemble(c: Case) -> None:
    assembly = c.assemble()
    evidence_bytes = c.output.read_bytes()
    evidence = json.loads(evidence_bytes)

    check(evidence["schema"] == qualifier.SCHEMA, "evidence carries the qualifier's schema")
    check(evidence["production_activation"] is False, "evidence activates nothing")
    check(
        [item["repository"] for item in evidence["repositories"]]
        == list(qualifier.REQUIRED_REPOSITORIES),
        "the four repositories are in the qualifier's order",
    )
    for slot, item in zip(SLOTS, evidence["repositories"]):
        raw = c.files[slot].read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        check(item["git_sha"] == PINS[slot], f"{slot}: git_sha is the verdict's head")
        check(item["live_repository_authority_passed"] is True, f"{slot}: marked passed")
        check(
            item["evidence_ref"]
            == f"repository-authority-verdict:{item['repository']}:{PINS[slot]}:sha256:{digest}",
            f"{slot}: the reference is derived from the verdict file's bytes",
        )

    code, verdict = qualifier_cli(c.output)
    check(code == 0 and verdict["state"] == "QUALIFIED", "the qualifier's CLI accepts the file")
    check(
        verdict["release_evidence_ref"]
        == "kaliv-repository-authority:" + ":".join(PINS[slot] for slot in SLOTS) + ":"
        + verdict["release_evidence_ref"].rsplit(":", 1)[1],
        "the release reference names the four pins in order",
    )
    check(
        assembly["release_evidence_ref"] == verdict["release_evidence_ref"],
        "the record names the reference the qualifier gives",
    )

    record = json.loads(c.record.read_bytes())
    check(record == assembly, "the record on disk is what assemble() returned")
    check(record["schema"] == assembler.RECORD_SCHEMA, "record schema")
    check(
        record["evidence"]
        == {"file": c.output.name, "sha256": hashlib.sha256(evidence_bytes).hexdigest()},
        "the record binds the evidence file by hash",
    )
    check(
        record["pins"] == {assembler.REPOSITORIES[slot][0]: PINS[slot] for slot in SLOTS},
        "the record lists the pins",
    )
    for slot, described in zip(SLOTS, record["verdicts"]):
        raw = c.files[slot].read_bytes()
        check(described["file"] == c.files[slot].name, f"{slot}: record names the file")
        check(described["sha256"] == hashlib.sha256(raw).hexdigest(), f"{slot}: record hash")
        check(described["bytes"] == len(raw), f"{slot}: record size")
        check(described["encoding"] == "utf-8", f"{slot}: record encoding")
        check(described["authority_mode"] == "classic", f"{slot}: record mode")
        check(
            described["required_status_checks"]
            == json.loads(REAL[slot])["required_status_checks"],
            f"{slot}: record repeats the checks the verdict names",
        )
    check(record["production_activation"] is False, "the record activates nothing")
    check(len(record["limitations"]) >= 3, "the record states what it does not prove")


def assembling_twice_changes_nothing(c: Case) -> None:
    first = c.assemble()
    stamp = (c.output.read_bytes(), c.record.read_bytes())
    second = c.assemble()
    check(first == second, "the same verdicts give the same record")
    check(stamp == (c.output.read_bytes(), c.record.read_bytes()), "and the same files")


def other_evidence_is_not_replaced(c: Case) -> None:
    c.assemble()
    kept = c.output.read_bytes()
    c.output.write_bytes(kept + b" ")
    c.refused("already exists with other content", "a different evidence file")
    c.output.write_bytes(kept)
    c.record.write_bytes(b"{}\n")
    c.refused("already exists with other content", "a different record")
    check(c.output.read_bytes() == kept, "the evidence file is left alone")


def a_stale_record_stops_before_the_evidence_is_written(c: Case) -> None:
    c.record.write_bytes(b"{}\n")
    c.refused("already exists with other content", "record in the way")
    check(not c.output.exists(), "no evidence file beside a refused record")


# --------------------------------------------------------------------------
# How PowerShell writes a redirected verdict
# --------------------------------------------------------------------------

def powershell_encodings(c: Case) -> None:
    text = REAL["visionrig"].strip()
    variants = {
        "utf-8-bom": b"\xef\xbb\xbf" + (text + "\r\n").encode("utf-8"),
        "utf-16-le-bom": b"\xff\xfe" + (text + "\r\n").encode("utf-16-le"),
        "utf-16-be-bom": b"\xfe\xff" + (text + "\r\n").encode("utf-16-be"),
        "utf-8": ("\r\n" + text + "\r\n\r\n").encode("utf-8"),
    }
    for name, raw in variants.items():
        for stale in (c.output, c.record):
            stale.unlink(missing_ok=True)
        c.files["visionrig"].write_bytes(raw)
        assembly = c.assemble()
        described = assembly["verdicts"][2]
        check(described["encoding"] == name, f"{name}: recorded as written")
        check(
            described["sha256"] == hashlib.sha256(raw).hexdigest(),
            f"{name}: the hash is of the file as written, mark included",
        )
        check(qualifier_cli(c.output)[0] == 0, f"{name}: qualifies")


def unreadable_files(c: Case) -> None:
    text = REAL["voicerig"].strip()
    human = (
        "VoiceRig repository authority: PASS\nRepository: Ternedal/VoiceRig\n"
        "Branch:     main\n"
    )
    for raw, fragment, label in (
        (b"", "is empty", "an empty file"),
        (b"\r\n  \r\n", "is empty", "a file of blank lines"),
        (b"\xef\xbb\xbf", "is empty", "a byte-order mark and nothing else"),
        (human.encode("utf-8"), "exactly the one JSON verdict", "the human-readable output"),
        ((text + "\n" + text + "\n").encode("utf-8"), "exactly the one JSON verdict", "two verdicts"),
        (("[" + text + "]").encode("utf-8"), "must be a JSON object", "a list"),
        (text.encode("utf-16-le"), "exactly the one JSON verdict", "UTF-16 without a mark"),
        (b"\xff\xfe\x00", "not UTF-8, or UTF-16", "a broken UTF-16 file"),
        (b"\x80\x81", "not UTF-8, or UTF-16", "bytes that are no text"),
        (
            text[:-1].encode("utf-8") + b',"passed":true}',
            "duplicate key",
            "a key given twice",
        ),
        (
            text.replace('"version":1', '"version":NaN').encode("utf-8"),
            "non-finite",
            "a number that is not one",
        ),
    ):
        c.files["voicerig"].write_bytes(raw)
        c.refused(fragment, label)
    c.files["voicerig"].write_bytes(b" " * (1024 * 1024 + 1))
    c.refused("too large", "a file over the limit")
    c.files["voicerig"].unlink()
    c.refused("cannot be read", "a missing file")


# --------------------------------------------------------------------------
# What a verdict must say
# --------------------------------------------------------------------------

def _set(key: str, value: Any) -> Callable[[dict], None]:
    def change(verdict: dict) -> None:
        verdict[key] = value
    return change


def _drop(key: str) -> Callable[[dict], None]:
    def change(verdict: dict) -> None:
        del verdict[key]
    return change


def verdict_rules() -> None:
    other = "f" * 40
    rules: tuple[tuple[str, Callable[[dict], None], str, str], ...] = (
        ("modelrig", _set("passed", False), "passed is not true", "a failing verdict"),
        ("bodyrig", _set("passed", "true"), "passed is not true", "passed as a string"),
        ("visionrig", _set("passed", 1), "passed is not true", "passed as a number"),
        ("voicerig", _drop("passed"), "passed is not true", "no passed field"),
        ("modelrig", _set("errors", ["x"]), "errors is not an empty list", "passed with errors"),
        ("visionrig", _set("errors", None), "errors is not an empty list", "errors missing"),
        ("bodyrig", _set("protected", False), "protected is not true", "unprotected main"),
        ("voicerig", _set("authority_mode", None), "authority_mode is missing", "no mode"),
        ("modelrig", _set("authority_mode", " "), "authority_mode is missing", "blank mode"),
        ("bodyrig", _set("production_activation", True), "production_activation is not false", "activation claimed"),
        ("visionrig", _drop("production_activation"), "production_activation is not false", "activation unstated"),
        ("modelrig", _set("agent3_activation_authority", True), "agent3_activation_authority is not false", "Agent 3 authority claimed"),
        ("modelrig", _set("physical_validation_authority", True), "physical_validation_authority is not false", "physical authority claimed"),
        ("bodyrig", _set("physical_acceptance_authority", True), "physical_acceptance_authority is not false", "acceptance authority claimed"),
        ("voicerig", _set("release_authority", True), "release_authority is not false", "an authority the format does not have"),
        ("modelrig", _set("version", 2), "version is not 1", "another version"),
        ("bodyrig", _set("version", True), "version is not 1", "version as a boolean"),
        ("visionrig", _set("version", "1"), "version is not 1", "version as a string"),
        ("voicerig", _set("version", 1.0), "version is not 1", "version as a float"),
        ("modelrig", _set("format", "bodyrig-repository-authority"), "format is", "another repository's format"),
        ("bodyrig", _set("repository", "Ternedal/ModelRig"), "it is for repository", "another repository"),
        ("visionrig", _set("branch", "release"), "not for branch main", "another branch"),
        ("voicerig", _set("head_revision", PINS["voicerig"].upper()), "head_revision is not", "upper-case head"),
        ("modelrig", _set("head_revision", PINS["modelrig"][:39]), "head_revision is not", "a short head"),
        ("bodyrig", _set("head_revision", None), "head_revision is not", "no head"),
        ("modelrig", _set("head_revision", other), "but the pin is", "ModelRig verified at another commit"),
        ("visionrig", _set("github_head_revision", other), "GitHub's main was not", "VisionRig: GitHub elsewhere"),
        ("voicerig", _drop("github_head_revision"), "GitHub's main was not", "VoiceRig: GitHub's head unstated"),
        ("bodyrig", _set("github_head_revision", other), "GitHub's main was not", "BodyRig: a stated GitHub head must agree"),
    )
    for slot, change, fragment, label in rules:
        def run(c: Case) -> None:
            c.edit(slot, change)
            c.refused(fragment, label)
        case(run)


def both_heads_moved_together_is_still_another_commit(c: Case) -> None:
    other = "e" * 40

    def change(verdict: dict) -> None:
        verdict["head_revision"] = other
        verdict["github_head_revision"] = other

    c.edit("visionrig", change)
    c.refused("but the pin is", "VisionRig verified at another commit")
    c.pins["visionrig"] = other
    assembly = c.assemble()
    check(assembly["pins"]["Ternedal/VisionRig"] == other, "the pin decides, when it matches")


def verdicts_in_the_wrong_slot(c: Case) -> None:
    c.files["visionrig"], c.files["voicerig"] = c.files["voicerig"], c.files["visionrig"]
    c.refused("format is", "VisionRig's and VoiceRig's files swapped")


def one_file_for_two_repositories(c: Case) -> None:
    c.files["voicerig"] = c.files["visionrig"]
    c.refused("its own verdict file", "one file given twice")


def pins_are_exact(c: Case) -> None:
    for value, label in (
        (PINS["bodyrig"].upper(), "an upper-case pin"),
        (PINS["bodyrig"][:12], "a short pin"),
        ("main", "a branch name"),
        ("", "an empty pin"),
        (None, "no pin"),
    ):
        c.pins["bodyrig"] = value
        c.refused("--pin-bodyrig must be a lowercase 40-hex Git SHA", label)
    c.pins = {slot: PINS[slot] for slot in SLOTS[:3]}
    c.refused("exactly one verdict file and one pin", "three pins")


def outputs_do_not_collide(c: Case) -> None:
    c.refused("must be different files", "record on the evidence file", record=c.output)
    c.refused("must be different files", "report on the record", report=c.record)
    c.refused("must not replace a verdict file", "evidence over a verdict", output=c.files["modelrig"])
    c.refused("must not replace a verdict file", "record over a verdict", record=c.files["bodyrig"])
    c.refused("must not replace a verdict file", "report over a verdict", report=c.files["voicerig"])
    for slot in SLOTS:
        check(c.files[slot].read_bytes() == REAL[slot].encode("utf-8"), f"{slot}: verdict untouched")


# --------------------------------------------------------------------------
# The qualifier decides
# --------------------------------------------------------------------------

class _Refusing:
    SCHEMA = qualifier.SCHEMA
    REQUIRED_REPOSITORIES = qualifier.REQUIRED_REPOSITORIES
    RepositoryAuthorityQualificationError = qualifier.RepositoryAuthorityQualificationError

    def __init__(self) -> None:
        self.seen: list[dict] = []

    def qualify(self, value: dict) -> dict:
        self.seen.append(copy.deepcopy(value))
        raise self.RepositoryAuthorityQualificationError("refused by the test")


class _Unsatisfied(_Refusing):
    def qualify(self, value: dict) -> dict:
        self.seen.append(copy.deepcopy(value))
        return {"repository_authority_gate_satisfied": False, "release_evidence_ref": "x"}


def nothing_is_written_unless_the_qualifier_accepts(c: Case) -> None:
    refusing = _Refusing()
    c.refused("the qualifier refused the assembled evidence", "qualifier refuses", qualifier=refusing)
    check(len(refusing.seen) == 1, "the qualifier was asked once")
    check(
        [item["git_sha"] for item in refusing.seen[0]["repositories"]]
        == [PINS[slot] for slot in SLOTS],
        "and was shown the four pins",
    )
    c.refused("did not accept the assembled evidence", "qualifier is not satisfied", qualifier=_Unsatisfied())


def report_comes_from_the_qualifier(c: Case) -> None:
    report = c.dir / "report" / "kaliv-repository-authority-latest.json"
    assembly = c.assemble(report=report)
    code, verdict = qualifier_cli(c.output)
    check(code == 0, "qualifies")
    check(json.loads(report.read_bytes()) == verdict, "the report is the qualifier's verdict")
    check(
        report.read_text(encoding="utf-8") == json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        "written as the qualifier's command line writes it",
    )
    check(assembly["release_evidence_ref"] == verdict["release_evidence_ref"], "same reference")
    c.assemble(report=report)
    check(json.loads(report.read_bytes()) == verdict, "a second run rewrites the same report")


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def command_line(c: Case) -> None:
    done = c.cli()
    check(done.returncode == 0, f"exit 0 on success: {done.stdout[-300:]} {done.stderr[-300:]}")
    printed = json.loads(done.stdout)
    check(printed == json.loads(c.record.read_bytes()), "prints the record it wrote")
    check(
        c.record.name == "repository-authority-evidence-assembly.json",
        "the record's default name follows the evidence file",
    )
    check(qualifier_cli(c.output)[0] == 0, "the file from the command line qualifies")
    check(not list(c.dir.glob("*.tmp")), "no temporary file is left")

    c.edit("bodyrig", _set("passed", False))
    for stale in (c.output, c.record):
        stale.unlink()
    done = c.cli("--report", str(c.dir / "report.json"))
    check(done.returncode == 2, "exit 2 on a refusal")
    answer = json.loads(done.stdout)
    check(answer["ok"] is False and "Ternedal/BodyRig verdict refused" in answer["error"], "says which repository")
    check(not c.output.exists() and not c.record.exists(), "a refusal writes no evidence")
    check(not (c.dir / "report.json").exists(), "and no report")


def command_line_leaves_no_bytecode(c: Case) -> None:
    # A copy of the tool, so bytecode from other tests cannot hide the answer.
    tool = c.dir / "tool" / "scripts"
    tool.mkdir(parents=True)
    for name in ("kaliv_repository_authority_assembler.py", "kaliv_repository_authority_qualifier.py"):
        shutil.copy(ROOT / "scripts" / name, tool / name)
    command = [sys.executable, str(tool / "kaliv_repository_authority_assembler.py")]
    for slot in SLOTS:
        command += [f"--{slot}", str(c.files[slot]), f"--pin-{slot}", c.pins[slot]]
    command += ["--output", str(c.output), "--report", str(c.dir / "report.json")]
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    done = subprocess.run(command, capture_output=True, text=True, timeout=120, env=environment)
    check(done.returncode == 0, f"the copied tool runs: {done.stdout[-300:]} {done.stderr[-300:]}")
    check((c.dir / "report.json").is_file(), "and loaded the qualifier beside it")
    check(
        sorted(path.name for path in tool.iterdir())
        == ["kaliv_repository_authority_assembler.py", "kaliv_repository_authority_qualifier.py"],
        "the tool writes no bytecode beside itself",
    )


def command_line_requires_all_four(c: Case) -> None:
    command = [sys.executable, str(SCRIPT), "--output", str(c.output)]
    for slot in SLOTS[:3]:
        command += [f"--{slot}", str(c.files[slot]), f"--pin-{slot}", c.pins[slot]]
    done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    check(done.returncode == 2, "argparse refuses three repositories")
    check("--voicerig" in done.stderr, "and names the missing one")
    check(not c.output.exists(), "nothing written")


def main() -> None:
    for run in (
        real_verdicts_assemble,
        assembling_twice_changes_nothing,
        other_evidence_is_not_replaced,
        a_stale_record_stops_before_the_evidence_is_written,
        powershell_encodings,
        unreadable_files,
        both_heads_moved_together_is_still_another_commit,
        verdicts_in_the_wrong_slot,
        one_file_for_two_repositories,
        pins_are_exact,
        outputs_do_not_collide,
        nothing_is_written_unless_the_qualifier_accepts,
        report_comes_from_the_qualifier,
        command_line,
        command_line_leaves_no_bytecode,
        command_line_requires_all_four,
    ):
        case(run)
    verdict_rules()
    print(f"Kaliv repository authority assembler contract: {CHECKS} checks PASS")


if __name__ == "__main__":
    main()
