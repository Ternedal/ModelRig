#!/usr/bin/env python3
from __future__ import annotations

import builtins
import importlib.util
import json
import pathlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent3_write_pilot_positive_one_click.py"
LAUNCHER = ROOT / "START_AGENT3_WRITE_PILOT_POSITIVE.cmd"
RUNBOOK = ROOT / "AGENT3_WRITE_PILOT_POSITIVE.md"
SOURCE = code_of(SCRIPT)
LAUNCHER_SOURCE = code_of(LAUNCHER)
RUNBOOK_SOURCE = code_of(RUNBOOK)

spec = importlib.util.spec_from_file_location("t022_positive_operator_test", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


check("operator script exists", SCRIPT.is_file())
check("Windows launcher exists", LAUNCHER.is_file())
check("operator runbook exists", RUNBOOK.is_file())
check(
    "launcher invokes only the positive operator",
    "agent3_write_pilot_positive_one_click.py" in LAUNCHER_SOURCE
    and "merge" not in LAUNCHER_SOURCE.lower()
    and "git push" not in LAUNCHER_SOURCE.lower(),
)
check(
    "operator is pinned to its exact candidate branch",
    'BRANCH = "agent/t022-write-pilot-positive-operator"' in SOURCE
    and 'VERSION = "1.58.146"' in SOURCE,
)
check(
    "operator invokes the authenticated GET-only preflight",
    "preflight.run_preflight(" in SOURCE
    and SOURCE.index("run_preflight(manifest_path=MANIFEST")
    < SOURCE.index("for ordinal in pending"),
)
check(
    "operator does not implement a write HTTP transport",
    "urllib.request" not in SOURCE
    and 'method="POST"' not in SOURCE
    and 'method="PUT"' not in SOURCE
    and 'method="PATCH"' not in SOURCE
    and 'method="DELETE"' not in SOURCE,
)
check(
    "operator exposes no confirmation or approval endpoint",
    "/confirm" not in SOURCE
    and "/approve" not in SOURCE
    and "/start" not in SOURCE
    and "/cancel" not in SOURCE,
)
check(
    "operator explicitly refuses to start a write-enabled stack",
    "starter ikke en write-aktiveret stack" in SOURCE
    and "starter bevidst **ikke** selv en write-aktiveret stack" in RUNBOOK_SOURCE,
)
check(
    "three exact physical attestations are required per run",
    "PREVIEW {ordinal:02d} NOTE_APPEND MATCHER" in SOURCE
    and "APPROVAL {ordinal:02d} ENHED GODKENDT" in SOURCE
    and "OUTCOME {ordinal:02d} COMPLETED SYNLIG" in SOURCE
    and SOURCE.count("require_phrase(") >= 4,
)
check(
    "operator captures preview approval and outcome artifacts",
    "preview-windows.png" in SOURCE
    and "approval-android.png" in SOURCE
    and "outcome-windows.png" in SOURCE,
)
check(
    "operator opens only existing developer surfaces",
    '"--args=--agent3"' in SOURCE
    and "ANDROID_AGENT3_EXTRA" in SOURCE,
)
check(
    "operator uses the established forensic manifest binding",
    "bind_run(manifest, ordinal, run_id)" in SOURCE
    and "_atomic_json(MANIFEST, manifest)" in SOURCE,
)
check(
    "separate observations store only run-id hash",
    '"run_id_sha256": _sha_text(run_id)' in SOURCE
    and '"run_id": run_id' not in SOURCE,
)
check(
    "resume requires the original preflight and observations",
    "preflight/observationsjournal mangler" in SOURCE
    and "resume må ikke rekonstrueres bagefter" in SOURCE
    and "observed_ordinals != set(bound)" in SOURCE,
)
check(
    "both operator-owned record types stay non-activating",
    SOURCE.count('"production_activation": False') >= 2
    and "production_activation=false" in SOURCE,
)
check(
    "runbook leaves negative and forensic work explicitly open",
    "syv negative cases" in RUNBOOK_SOURCE
    and "forensic collector" in RUNBOOK_SOURCE
    and "T-022 er stadig ikke grøn" in RUNBOOK_SOURCE,
)

manifest = {
    "pilot_id": "pilot-test",
    "operator": "Anders",
    "runs": [
        {"ordinal": 1, "marker": "KALIV-T022:test:P:01:a", "run_id": "run-1"},
        {"ordinal": 2, "marker": "KALIV-T022:test:P:02:b", "run_id": None},
    ],
}
identity = {
    "version": module.VERSION,
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
}
preflight_report = {
    "generated_at": "2026-07-29T14:00:00Z",
    "evidence": {
        "manifest_sha256": "c" * 64,
        "rig_validation_report_sha256": "d" * 64,
    },
}
android = {"serial_sha256": "e" * 64, "model": "Pixel 6a", "os_version": "17"}

bound, pending = module.manifest_progress(manifest)
check("progress separates bound and pending ordinals", bound == [1] and pending == [2])

observations = module.new_observations(manifest, identity, preflight_report, android)
check(
    "new observations are exact-candidate bound and red by default",
    observations["candidate"]["git_sha"] == identity["git_sha"]
    and observations["preflight"]["manifest_sha256"] == "c" * 64
    and observations["runs"] == []
    and observations["production_activation"] is False,
)

observations["runs"] = [{"ordinal": 1}]
check(
    "resume accepts only exact bound-ordinal parity",
    module.validate_resume(observations, manifest, identity) == [],
)
changed = json.loads(json.dumps(observations))
changed["candidate"]["git_sha"] = "f" * 40
check(
    "resume rejects candidate drift",
    any("candidate.git_sha mismatch" in error for error in module.validate_resume(changed, manifest, identity)),
)
changed = json.loads(json.dumps(observations))
changed["runs"] = []
check(
    "resume rejects reconstructed or missing physical observations",
    any("bound ordinals" in error for error in module.validate_resume(changed, manifest, identity)),
)

original_input = builtins.input
try:
    builtins.input = lambda _prompt: "PREVIEW 03 NOTE_APPEND MATCHER"
    module.require_phrase("PREVIEW 03 NOTE_APPEND MATCHER")
    exact_phrase_ok = True
except Exception:
    exact_phrase_ok = False
finally:
    builtins.input = original_input
check("exact attestation phrase is accepted", exact_phrase_ok)

try:
    builtins.input = lambda _prompt: "ja"
    try:
        module.require_phrase("PREVIEW 03 NOTE_APPEND MATCHER")
        weak_phrase_rejected = False
    except module.OperatorError:
        weak_phrase_rejected = True
finally:
    builtins.input = original_input
check("ordinary yes cannot attest a physical observation", weak_phrase_rejected)

with tempfile.TemporaryDirectory(prefix="kaliv-t022-positive-") as tmp:
    tmp_root = Path(tmp)
    old_manifest_path = module.MANIFEST
    old_observations_path = module.OBSERVATIONS
    old_bind_run = module.bind_run
    module.MANIFEST = tmp_root / "manifest.json"
    module.OBSERVATIONS = tmp_root / "observations.json"

    fixture_manifest = {
        "pilot_id": "pilot-test",
        "runs": [
            {"ordinal": 1, "marker": "KALIV-T022:test:P:01:a", "run_id": None}
        ],
    }
    fixture_observations = {
        "schema": module.OBSERVATIONS_SCHEMA,
        "runs": [],
        "production_activation": False,
    }

    def fake_bind(value, ordinal, run_id):
        assert ordinal == 1
        assert run_id == "real-run-id"
        value["runs"][0]["run_id"] = run_id

    module.bind_run = fake_bind
    artifact = {"path": "validation/example.png", "sha256": "1" * 64, "bytes": 10}
    module.record_run(
        manifest=fixture_manifest,
        observations=fixture_observations,
        ordinal=1,
        run_id="real-run-id",
        preview_artifact=artifact,
        approval_artifact=artifact,
        outcome_artifact=artifact,
    )
    saved_manifest = json.loads(module.MANIFEST.read_text(encoding="utf-8"))
    saved_observations = json.loads(module.OBSERVATIONS.read_text(encoding="utf-8"))
    check(
        "recording atomically binds the forensic manifest",
        saved_manifest["runs"][0]["run_id"] == "real-run-id",
    )
    check(
        "physical observation stores hashes but not raw run id",
        saved_observations["runs"][0]["run_id_sha256"]
        == module._sha_text("real-run-id")
        and "real-run-id" not in module.OBSERVATIONS.read_text(encoding="utf-8"),
    )
    check(
        "recorded physical run retains all three artifact receipts",
        set(saved_observations["runs"][0])
        >= {"preview_artifact", "approval_artifact", "outcome_artifact"},
    )
    check(
        "recorded physical run remains non-activating",
        saved_observations["runs"][0]["production_activation"] is False,
    )

    module.MANIFEST = old_manifest_path
    module.OBSERVATIONS = old_observations_path
    module.bind_run = old_bind_run

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-022 POSITIVE PHYSICAL OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
