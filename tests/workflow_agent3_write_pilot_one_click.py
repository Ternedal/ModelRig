#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / "scripts" / "agent3_write_pilot_one_click.py"
LAUNCHER = ROOT / "START_AGENT3_WRITE_PILOT.cmd"
RUNBOOK = ROOT / "AGENT3_WRITE_PILOT_PHYSICAL.md"

source = WIZARD.read_text(encoding="utf-8")
launcher = LAUNCHER.read_text(encoding="utf-8")
runbook = RUNBOOK.read_text(encoding="utf-8")
ast.parse(source, filename=str(WIZARD))

checks = {
    "wizard is exact branch and version bound": (
        'BRANCH = "agent/t022-write-pilot-one-click"' in source
        and 'VERSION = "1.58.146"' in source
        and "stage.ensure_candidate()" in source
        and 'identity.get("working_tree_clean") is not True' in source
        and 'identity.get("version_stamps_consistent") is not True' in source
    ),
    "wizard requires physical backend approval mode": (
        '"KALIV_AGENT3_ENABLED": "1"' in source
        and '"KALIV_TOOLS_ENABLED": "1"' in source
        and '"KALIV_AGENT3_APPROVAL_REQUIRED": "1"' in source
        and "KALIV_AGENT3_APPROVAL_SECRET" in source
    ),
    "secrets are entered hidden and not added to state": (
        source.count("getpass.getpass") >= 4
        and '"MODELRIG_TOKEN"' not in source[source.index('state = {'):source.index('save_state(state)', source.index('state = {'))]
        and '"KALIV_AGENT3_APPROVAL_SECRET"' not in source[source.index('state = {'):source.index('save_state(state)', source.index('state = {'))]
    ),
    "exactly one Android device is required": (
        'if len(devices) != 1:' in source
        and "adb devices" not in source
        and 'run([adb, "devices"]' in source
    ),
    "exact-head Android APK is built and installed": (
        '":app:assembleDebug"' in source
        and 'run([adb, "install", "-r", str(apk)])' in source
    ),
    "developer Android and desktop surfaces are opened": (
        "ANDROID_AGENT3_EXTRA" in source
        and '"--args=--agent3"' in source
        and "launch_android(adb)" in source
        and "launch_desktop()" in source
    ),
    "live preflight runs before physical evidence": (
        "preflight.run_preflight(" in source
        and 'if not report.get("success"):' in source
        and "common.prepare_manifest(" in source
    ),
    "positive inventory is the schema-owned twenty runs": (
        'for item in manifest["runs"]:' in source
        and "common.RUN_COUNT" in source
        and 'f"T-022 POSITIV {ordinal:02d}/20"' in source
    ),
    "positive preview and append require distinct exact phrases": (
        'POSITIVE_PREVIEW_PREFIX = "PREVIEW GODKENDT"' in source
        and 'POSITIVE_APPEND_PREFIX = "APPEND BEKRÆFTET"' in source
        and "require_phrase(f\"{POSITIVE_PREVIEW_PREFIX} {ordinal:02d}\")" in source
        and "require_phrase(f\"{POSITIVE_APPEND_PREFIX} {ordinal:02d}\")" in source
    ),
    "ordinary yes or Enter cannot attest a positive run": (
        "def require_phrase(expected: str)" in source
        and "if entered != expected:" in source
        and 'input("  Godkend fysisk på Android' in source
        and "require_phrase" in source
    ),
    "interrupted positive bind has fail-closed recovery": (
        'POSITIVE_RECOVERY_PREFIX = "GENOPTAG POSITIV"' in source
        and "if existing == 0:" in source
        and "elif existing == 1:" in source
        and "else:" in source
        and "verify_positive(" in source
    ),
    "positive run is verified across all four forensic sources": (
        "forensics.load_run_records" in source
        and "forensics.load_approval_rows" in source
        and "forensics.load_audit_rows" in source
        and 'Path(paths["notes"])' in source
        and "forensics._validate_success_run(" in source
    ),
    "manifest binding happens only after forensic success": (
        source.index("errors = verify_positive(")
        < source.index("common.bind_run(manifest, ordinal, run_id)")
        and source.index('if errors:')
        < source.index("common.bind_run(manifest, ordinal, run_id)")
    ),
    "journal is initialized only after all twenty manifest bindings": (
        'if len(complete) != common.RUN_COUNT:' in source
        and source.index('if len(complete) != common.RUN_COUNT:')
        < source.index("journal_store._init(JOURNAL, MANIFEST)")
        and source.index("common.bind_run(manifest, ordinal, run_id)")
        < source.index("journal_store._init(JOURNAL, MANIFEST)")
    ),
    "negative inventory comes from the strict shared schema": (
        "for name in common._NEGATIVE_CASES:" in source
        and all(
            name in source
            for name in (
                "deny",
                "timeout",
                "changed_args",
                "stale_revision",
                "replay",
                "concurrent_approval",
                "stop_retry_replan",
            )
        )
    ),
    "negative cases require exact human attestation": (
        'NEGATIVE_PREFIX = "NEGATIV CASE OBSERVERET"' in source
        and "require_phrase(f\"{NEGATIVE_PREFIX} {name}\")" in source
    ),
    "negative HTTP contracts match the strict validator": (
        '"deny": (200,)' in source
        and '"timeout": (409,)' in source
        and '"changed_args": (409,)' in source
        and '"stale_revision": (409,)' in source
        and '"replay": (409,)' in source
        and 'sorted(statuses) != [200, 409]' in source
        and 'code not in {200, 202, 409}' not in source
    ),
    "response bodies and hidden run ids enter the append-only journal": (
        "capture_response(name, index)" in source
        and "journal_cases.observe_request(" in source
        and "response_path=response_path" in source
        and "getpass.getpass(f\"  Run-id for observation" in source
    ),
    "an open negative case is resumed rather than duplicated": (
        "def journal_status()" in source
        and "open_case" in source
        and "Genoptager åben" in source
        and "mere end én åben negativ case" in source
    ),
    "strict existing finalizer and collector own green status": (
        "journal_cases.finalize(JOURNAL, MANIFEST)" in source
        and "pilot.collect_report(" in source
        and 'if not report.get("success"):' in source
        and 'state["phase"] = "complete"' in source
    ),
    "all state and reports remain non-activating": (
        source.count('"production_activation": False') >= 2
        and 'stage.ok("production_activation=false")' in source
        and "production_activation=true" not in source.lower()
    ),
    "wizard has no direct approval or confirmation endpoint": not any(
        token in source
        for token in (
            "/approve",
            "/confirmation/approve",
            "approval_token=",
            "mint_approval",
            "send_approval",
        )
    ),
    "wizard has no merge push tag release or activation command": not any(
        token in source
        for token in (
            'git("merge"',
            'git("push"',
            'git("tag"',
            "gh release",
            "production_activation = True",
        )
    ),
    "Windows launcher invokes only the wizard and preserves exit status": (
        "agent3_write_pilot_one_click.py" in launcher
        and "set EXITCODE=%errorlevel%" in launcher
        and "exit /b %EXITCODE%" in launcher
        and "git " not in launcher.lower()
    ),
    "runbook documents human-only evidence and safe resume": (
        "kan ikke se UI’et" in runbook
        and "PREVIEW GODKENDT NN" in runbook
        and "APPEND BEKRÆFTET NN" in runbook
        and "GENOPTAG POSITIV NN" in runbook
        and "NEGATIV CASE OBSERVERET <case-navn>" in runbook
        and "journalen til det endelige manifest" in runbook
        and "production_activation=false" in runbook
    ),
}

failed = [label for label, ok in checks.items() if not ok]
for label, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-022 WRITE PILOT ONE-CLICK: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
