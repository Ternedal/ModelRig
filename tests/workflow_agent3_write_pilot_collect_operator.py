#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent3_write_pilot_collect_one_click.py"
LAUNCHER = ROOT / "START_AGENT3_WRITE_PILOT.cmd"
RUNBOOK = ROOT / "AGENT3_WRITE_PILOT_COLLECT.md"
SOURCE = code_of(SCRIPT)
LAUNCHER_SOURCE = code_of(LAUNCHER)
RUNBOOK_SOURCE = code_of(RUNBOOK)

spec = importlib.util.spec_from_file_location("t022_collect_operator_test", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


check("collector operator exists", SCRIPT.is_file())
check("combined Windows launcher exists", LAUNCHER.is_file())
check("collector runbook exists", RUNBOOK.is_file())
check(
    "top-level launcher delegates only through the final gate",
    "agent3_write_pilot_final_gate_operator.py" in LAUNCHER_SOURCE
    and "agent3_write_pilot_collect_one_click.py" not in LAUNCHER_SOURCE
    and "agent3_write_pilot_negative_operator.py" not in LAUNCHER_SOURCE
    and "agent3_write_pilot_positive_one_click.py" not in LAUNCHER_SOURCE,
)
check(
    "collector is pinned to the exact final branch and version",
    'BRANCH = "agent/t022-write-pilot-collector"' in SOURCE
    and 'VERSION = "1.58.146"' in SOURCE,
)
check(
    "collector adds no write HTTP transport",
    "urllib.request" not in SOURCE
    and 'method="POST"' not in SOURCE
    and 'method="PUT"' not in SOURCE
    and 'method="PATCH"' not in SOURCE
    and 'method="DELETE"' not in SOURCE,
)
check(
    "collector reuses the negative physical entrypoint and established forensic judge",
    "negative_entry.main()" in SOURCE
    and "report_module.collect_report(" in SOURCE
    and "report_module.load_bound_negative_evidence(" in SOURCE,
)
check(
    "rolling report is removed before physical work can fail",
    SOURCE.index("_archive_rolling_report(identity)")
    < SOURCE.index("paths = _run_physical_pipeline()"),
)
check(
    "positive and negative sidecars are checked before forensic collect",
    SOURCE.index("_load_positive(identity_map)")
    < SOURCE.rindex("_load_negative(")
    < SOURCE.index("report = _collect(paths)"),
)
check(
    "artifact policy rejects traversal and every symlink component",
    '".." in relative.parts' in SOURCE
    and "cursor.is_symlink()" in SOURCE
    and "resolved.relative_to(allowed_root.resolve())" in SOURCE,
)
check(
    "positive physical binding covers all three artifact classes",
    'for field in ("preview_artifact", "approval_artifact", "outcome_artifact")' in SOURCE
    and "common.RUN_COUNT" in SOURCE
    and "set(range(1, common.RUN_COUNT + 1))" in SOURCE,
)
check(
    "negative physical binding covers responses and both clients",
    'set(screenshots) != {"windows", "android"}' in SOURCE
    and "response_sha256" in SOURCE
    and "journal_final_sha256" in SOURCE,
)
check(
    "green report is evidence only and never activation",
    'report.get("production_activation") is not False' in SOURCE
    and "ikke merge, release eller produktionsaktivering" in SOURCE,
)
check(
    "runbook leaves the final dormant gate open",
    "Del 4 er en separat dormant CI/final-gate" in RUNBOOK_SOURCE
    and "T-022 ikke afsluttet" in RUNBOOK_SOURCE,
)

old_core_branch = module.core.BRANCH
old_positive_branch = module.positive.BRANCH
old_core_version = module.core.VERSION
old_positive_version = module.positive.VERSION
module.configure_candidate()
check(
    "branch override reaches both negative and positive operators",
    module.core.BRANCH == module.BRANCH
    and module.positive.BRANCH == module.BRANCH
    and module.core.VERSION == module.VERSION
    and module.positive.VERSION == module.VERSION,
)
module.core.BRANCH = old_core_branch
module.positive.BRANCH = old_positive_branch
module.core.VERSION = old_core_version
module.positive.VERSION = old_positive_version

identity = {
    "version": module.VERSION,
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
}
check(
    "candidate fields accept exact identity",
    module._candidate_fields(identity, identity, "candidate") == [],
)
drifted = dict(identity)
drifted["git_sha"] = "c" * 40
check(
    "candidate fields reject SHA drift",
    any("git_sha" in item for item in module._candidate_fields(drifted, identity, "candidate")),
)

with tempfile.TemporaryDirectory(prefix="kaliv-t022-artifacts-", dir=ROOT) as tmp:
    allowed = Path(tmp)
    file_path = allowed / "screen.png"
    file_path.write_bytes(b"physical-screen")
    artifact = {
        "path": str(file_path.relative_to(ROOT)),
        "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        "bytes": file_path.stat().st_size,
    }
    try:
        accepted = module._safe_relative_file(
            artifact,
            label="fixture",
            allowed_root=allowed,
        ) == file_path.resolve()
    except Exception:
        accepted = False
    check("exact in-root artifact is accepted", accepted)

    bad_hash = dict(artifact)
    bad_hash["sha256"] = "0" * 64
    try:
        module._safe_relative_file(bad_hash, label="bad_hash", allowed_root=allowed)
        hash_rejected = False
    except module.CollectorError:
        hash_rejected = True
    check("artifact hash tampering is rejected", hash_rejected)

    bad_size = dict(artifact)
    bad_size["bytes"] += 1
    try:
        module._safe_relative_file(bad_size, label="bad_size", allowed_root=allowed)
        size_rejected = False
    except module.CollectorError:
        size_rejected = True
    check("artifact byte-count tampering is rejected", size_rejected)

    traversal = dict(artifact)
    traversal["path"] = "validation/../VERSION"
    try:
        module._safe_relative_file(traversal, label="traversal", allowed_root=allowed)
        traversal_rejected = False
    except module.CollectorError:
        traversal_rejected = True
    check("artifact traversal is rejected", traversal_rejected)

    outside = ROOT / "VERSION"
    outside_artifact = {
        "path": str(outside.relative_to(ROOT)),
        "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
        "bytes": outside.stat().st_size,
    }
    try:
        module._safe_relative_file(outside_artifact, label="outside", allowed_root=allowed)
        outside_rejected = False
    except module.CollectorError:
        outside_rejected = True
    check("artifact outside the declared evidence root is rejected", outside_rejected)

    link = allowed / "linked.png"
    symlink_supported = True
    try:
        link.symlink_to(file_path)
    except OSError:
        symlink_supported = False
    if symlink_supported:
        linked = {
            "path": str(link.relative_to(ROOT)),
            "sha256": artifact["sha256"],
            "bytes": artifact["bytes"],
        }
        try:
            module._safe_relative_file(linked, label="linked", allowed_root=allowed)
            link_rejected = False
        except module.CollectorError:
            link_rejected = True
        check("artifact symlink is rejected", link_rejected)
    else:
        check("artifact symlink is rejected", True)

with tempfile.TemporaryDirectory(prefix="kaliv-t022-report-archive-") as tmp:
    old_validation = module.VALIDATION
    old_report = module.REPORT
    module.VALIDATION = Path(tmp)
    module.REPORT = Path(tmp) / "agent3-write-pilot-latest.json"
    module.REPORT.write_text('{"success":true}\n', encoding="utf-8")
    archived = module._archive_rolling_report("a" * 40)
    check(
        "old rolling report is archived rather than overwritten",
        archived is not None
        and archived.is_file()
        and not module.REPORT.exists()
        and json.loads(archived.read_text(encoding="utf-8"))["success"] is True,
    )
    module.VALIDATION = old_validation
    module.REPORT = old_report

original_safe_stage = module.negative_entry.safe_positive_stage
original_negative_main = module.negative_entry.main
fixture_paths = {
    "agent_db": Path("agent.db"),
    "approval_db": Path("approval.db"),
    "audit_db": Path("audit.db"),
    "notes": Path("notes.md"),
}


def fixture_stage():
    return ({"pilot_id": "pilot"}, {"runs": []}, fixture_paths, "secret")


def fixture_main():
    module.negative_entry.safe_positive_stage()
    return 0


module.negative_entry.safe_positive_stage = fixture_stage
module.negative_entry.main = fixture_main
try:
    captured_paths = module._run_physical_pipeline()
finally:
    module.negative_entry.safe_positive_stage = original_safe_stage
    module.negative_entry.main = original_negative_main
check(
    "physical pipeline captures exactly the four forensic paths",
    captured_paths == fixture_paths,
)

module.negative_entry.safe_positive_stage = fixture_stage
module.negative_entry.main = lambda: 7
try:
    try:
        module._run_physical_pipeline()
        nonzero_rejected = False
    except module.CollectorError:
        nonzero_rejected = True
finally:
    module.negative_entry.safe_positive_stage = original_safe_stage
    module.negative_entry.main = original_negative_main
check("non-zero physical pipeline exit is rejected", nonzero_rejected)

original_collect = module.report_module.collect_report
captured_collect: dict[str, object] = {}


def fake_collect(**kwargs):
    captured_collect.update(kwargs)
    return {"success": True, "production_activation": False, "blockers": []}


module.report_module.collect_report = fake_collect
try:
    collected = module._collect(fixture_paths)
finally:
    module.report_module.collect_report = original_collect
check(
    "collector receives every exact evidence and ledger path",
    collected["success"] is True
    and captured_collect == {
        "manifest_path": module.MANIFEST,
        "negative_path": module.NEGATIVE_JSON,
        "negative_journal_path": module.NEGATIVE_JOURNAL,
        "rig_validation_path": module.RIG_REPORT,
        "agent_db": fixture_paths["agent_db"],
        "approval_db": fixture_paths["approval_db"],
        "audit_db": fixture_paths["audit_db"],
        "notes_path": fixture_paths["notes"],
    },
)

originals = {
    "configure_candidate": module.configure_candidate,
    "ensure_candidate": module.positive.ensure_candidate,
    "candidate_identity": module.common.candidate_identity,
    "archive": module._archive_rolling_report,
    "physical": module._run_physical_pipeline,
    "positive": module._load_positive,
    "negative": module._load_negative,
    "collect": module._collect,
    "atomic": module.common._atomic_json,
    "heading": module.stage.heading,
    "ok": module.stage.ok,
    "note": module.stage.note,
}
order: list[str] = []
written: list[dict[str, object]] = []
manifest_fixture = {"pilot_id": "pilot", "runs": []}
identity_fixture = {
    "version": module.VERSION,
    "git_sha": "d" * 40,
    "code_sha256": "e" * 64,
    "identity_source": "git",
}
module.configure_candidate = lambda: order.append("configure")
module.positive.ensure_candidate = lambda: order.append("ensure") or identity_fixture["git_sha"]
module.common.candidate_identity = lambda _root: order.append("identity") or identity_fixture
module._archive_rolling_report = lambda _sha: order.append("archive")
module._run_physical_pipeline = lambda: order.append("physical") or fixture_paths
module._load_positive = lambda _identity: order.append("positive") or (manifest_fixture, b"manifest", {})
module._load_negative = lambda **_kwargs: order.append("negative") or {}
module._collect = lambda _paths: order.append("collect") or {
    "success": True,
    "production_activation": False,
    "blockers": [],
}
module.common._atomic_json = lambda path, value: written.append({"path": path, "value": value})
module.stage.heading = lambda _text: None
module.stage.ok = lambda _text: None
module.stage.note = lambda _text: None
try:
    green_exit = module.main()
finally:
    module.configure_candidate = originals["configure_candidate"]
    module.positive.ensure_candidate = originals["ensure_candidate"]
    module.common.candidate_identity = originals["candidate_identity"]
    module._archive_rolling_report = originals["archive"]
    module._run_physical_pipeline = originals["physical"]
    module._load_positive = originals["positive"]
    module._load_negative = originals["negative"]
    module._collect = originals["collect"]
    module.common._atomic_json = originals["atomic"]
    module.stage.heading = originals["heading"]
    module.stage.ok = originals["ok"]
    module.stage.note = originals["note"]
check(
    "green orchestration is exact and atomically writes the report",
    green_exit == 0
    and order == [
        "configure",
        "ensure",
        "identity",
        "archive",
        "physical",
        "identity",
        "positive",
        "negative",
        "collect",
    ]
    and len(written) == 1
    and written[0]["path"] == module.REPORT
    and written[0]["value"]["production_activation"] is False,
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-022 FORENSIC COLLECT OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
