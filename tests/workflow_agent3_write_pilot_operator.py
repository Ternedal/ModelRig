#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent3_write_pilot_one_click.py"
LAUNCHER = ROOT / "START_AGENT3_WRITE_PILOT_PHYSICAL.cmd"
RUNBOOK = ROOT / "AGENT3_WRITE_PILOT_PHYSICAL.md"

source = SCRIPT.read_text(encoding="utf-8")
launcher = LAUNCHER.read_text(encoding="utf-8")
runbook = RUNBOOK.read_text(encoding="utf-8")
compile(source, str(SCRIPT), "exec")

spec = importlib.util.spec_from_file_location("t022_write_pilot_operator_test", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.stage.note = lambda _message: None

checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


check(
    "operator is pinned to the exact dormant branch and version",
    'BRANCH = "agent/t022-write-pilot-operator"' in source
    and 'VERSION = "1.58.146"' in source,
)
check(
    "operator uses only authenticated GET for live verification",
    'urllib.request.Request(BASE_URL + path, method="GET")' in source
    and 'method="POST"' not in source
    and 'method="PUT"' not in source
    and 'method="PATCH"' not in source
    and 'method="DELETE"' not in source,
)
check(
    "operator cannot invoke repository publication commands",
    all(
        token not in source
        for token in (
            "git push",
            "git merge",
            "git tag",
            "gh release",
            'production_activation\": True',
        )
    ),
)
check(
    "device token and approval secret are read without echo",
    'prompt_secret("MODELRIG_TOKEN")' in source
    and 'prompt_secret("KALIV_AGENT3_APPROVAL_SECRET", minimum=32)' in source
    and "getpass.getpass" in source,
)
check(
    "positive preview and append require distinct exact attestations",
    'PREVIEW_ATTEST_PREFIX = "PREVIEW T022"' in source
    and 'POSITIVE_ATTEST_PREFIX = "APPEND T022"' in source
    and 'require_phrase(f"{PREVIEW_ATTEST_PREFIX} {ordinal:02d}")' in source
    and 'require_phrase(f"{POSITIVE_ATTEST_PREFIX} {ordinal:02d}")' in source,
)
check(
    "negative cases require exact start and done attestations",
    'NEGATIVE_START_PREFIX = "START NEGATIVE"' in source
    and 'NEGATIVE_DONE_PREFIX = "DONE NEGATIVE"' in source
    and 'require_phrase(f"{NEGATIVE_START_PREFIX} {name}")' in source
    and 'require_phrase(f"{NEGATIVE_DONE_PREFIX} {name}")' in source,
)
check(
    "all seven negative cases have explicit guidance",
    all(
        f'"{name}": (' in source
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
    and "for name in common._NEGATIVE_CASES" in source,
)
check(
    "preflight executes before negative journal initialization",
    source.index("preflight.run_preflight(")
    < source.index("journal_store._init(JOURNAL, MANIFEST)"),
)
check(
    "journal initialization is guarded by twenty completed bindings",
    'raise OperatorError("Alle 20 positive runs skal bindes før negative cases.")'
    in source
    and 'if not JOURNAL.exists():\n        journal_store._init(JOURNAL, MANIFEST)'
    in source,
)
check(
    "resume verifies the prepared manifest rather than the mutable bound bytes",
    "prepared_manifest_sha(manifest)" in source
    and "Manifestets forberedte indhold ændrede sig" in source,
)
check(
    "positive run is verified across server route step events note approval and audit",
    all(
        token in source
        for token in (
            'route.get("kind") != "rig_tools_local"',
            'step.get("tool") != "note_append"',
            'step.get("state") != "succeeded"',
            '"approval_consumed"',
            '"confirmation_approved"',
            '"step_succeeded"',
            "note_count(paths.notes, marker) != 1",
            "approval_count_for_run(paths.approval_db, run_id) != 1",
            "audit_count_for_marker(paths.audit_db, marker) != 1",
        )
    ),
)
check(
    "single-use binding is delegated to the existing report CLI",
    '"agent3_write_pilot_report.py"' in source
    and '"bind"' in source
    and '"--ordinal"' in source
    and '"--run-id"' in source,
)
check(
    "negative evidence uses the existing append-only journal implementation",
    "journal_cases.begin_case(" in source
    and "journal_cases.observe_request(" in source
    and "journal_cases.finish_case(" in source
    and "journal_cases.finalize(JOURNAL, MANIFEST)" in source,
)
check(
    "response bodies are captured as exact bytes or an explicit file",
    'body.startswith("@")' in source
    and "destination.write_bytes(raw)" in source
    and 'raw = body.encode("utf-8")' in source,
)
check(
    "operator state is advisory and non-activating",
    '"advisory_only": True' in source
    and '"production_activation": False' in source
    and 'value["advisory_only"] = True' in source
    and 'value["production_activation"] = False' in source,
)
check(
    "evidence is archived only after an exact reset phrase",
    'require_phrase("ARCHIVE T022")' in source
    and "--reset" in source
    and ".unlink(" not in source
    and "shutil.rmtree" not in source,
)
check(
    "safe stop explicitly preserves partial evidence",
    "delvis T-022-evidens er bevaret" in source
    and "slettes aldrig automatisk" in source,
)
check(
    "operator builds and opens the exact Android and desktop developer surfaces",
    '":app:assembleDebug"' in source
    and "ANDROID_AGENT3_EXTRA" in source
    and '"--args=--agent3"' in source,
)
check(
    "launcher propagates phase arguments and preserves nonzero exit",
    "scripts\\agent3_write_pilot_one_click.py %*" in launcher
    and "exit /b %EXIT_CODE%" in launcher
    and "Delvis manifest, journal og operator-state er bevaret." in launcher,
)
check(
    "runbook states that physical actions are not automated",
    "sender ingen POST-, approval-, confirmation-, write-, retry-, cancel- eller"
    in runbook
    and "production_activation=false" in runbook
    and "20/20" in runbook
    and "7/7" in runbook,
)
check(
    "phased resume entrypoints are documented",
    all(
        phase in runbook
        for phase in (
            "--phase prepare",
            "--phase positive",
            "--phase negative",
            "--phase collect",
        )
    ),
)

with tempfile.TemporaryDirectory(prefix="kaliv-t022-approval-store-") as tmp:
    db = Path(tmp) / "approval.db"
    module.ensure_approval_store(db)
    with sqlite3.connect(db) as conn:
        columns = [
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(agent3_approval_uses)"
            ).fetchall()
        ]
        conn.execute(
            "INSERT INTO agent3_approval_uses VALUES (?,?,?,?,?,?,?,?)",
            ("n", "a", 1.0, "run", "step", "device", 0, "token"),
        )
        conn.commit()
    module.ensure_approval_store(db)
    with sqlite3.connect(db) as conn:
        retained = conn.execute(
            "SELECT COUNT(*) FROM agent3_approval_uses"
        ).fetchone()[0]
    check(
        "pristine approval store uses the canonical schema",
        columns
        == [
            "nonce_sha256",
            "action_sha256",
            "used_at",
            "run_id",
            "step_id",
            "device_id",
            "plan_revision",
            "token_sha256",
        ],
    )
    check("existing approval store is never truncated", retained == 1)

fixture = {
    "schema": "kaliv-agent3-write-pilot-manifest/v1",
    "pilot_id": "f" * 32,
    "created_at": "2026-07-27T18:00:00Z",
    "operator": "Anders",
    "target": {
        "version": "1.58.146",
        "git_sha": "a" * 40,
        "code_sha256": "b" * 64,
        "identity_source": "git",
        "rig_validation_report_sha256": "c" * 64,
    },
    "marker_prefix": f"KALIV-T022:{'f' * 32}:P:",
    "runs": [
        {
            "ordinal": ordinal,
            "marker": f"KALIV-T022:{'f' * 32}:P:{ordinal:02d}:{ordinal:032x}",
            "run_id": None,
            "bound_at": None,
        }
        for ordinal in range(1, 21)
    ],
}
prepared_hash = module.prepared_manifest_sha(fixture)
fixture["runs"][0]["run_id"] = "run-1"
fixture["runs"][0]["bound_at"] = "2026-07-27T18:05:00Z"
check(
    "prepared manifest hash survives legitimate run binding",
    module.prepared_manifest_sha(fixture) == prepared_hash,
)

state = module.initial_state(
    {
        "version": "1.58.146",
        "git_sha": "a" * 40,
        "code_sha256": "b" * 64,
        "identity_source": "git",
    }
)
check(
    "fresh resume state cannot claim evidence or activation",
    state["report_success"] is False
    and state["advisory_only"] is True
    and state["production_activation"] is False,
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-022 PHYSICAL OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
