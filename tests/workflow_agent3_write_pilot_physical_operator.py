#!/usr/bin/env python3
from __future__ import annotations

import builtins
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent3_write_pilot_physical_one_click.py"
SOURCE = SCRIPT.read_text(encoding="utf-8")
spec = importlib.util.spec_from_file_location("t022_physical_operator", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


def with_input(value: str, call):
    original = builtins.input
    builtins.input = lambda _prompt="": value
    try:
        return call()
    finally:
        builtins.input = original


check(
    "operator is version-bound to its exact T-022 branch",
    module.BRANCH == "agent/t022-write-pilot-physical-operator"
    and module.VERSION == "1.58.146",
)
check(
    "operator exposes exactly the seven accepted negative cases",
    module.NEGATIVE_CASES
    == (
        "deny",
        "timeout",
        "changed_args",
        "stale_revision",
        "replay",
        "concurrent_approval",
        "stop_retry_replan",
    ),
)
check(
    "approval enforcement is explicit while normal task routing remains off",
    'os.environ["KALIV_AGENT3_APPROVAL_REQUIRED"] = "1"' in SOURCE
    and '"KALIV_AGENT3_TASK_UI": "0"' in SOURCE
    and '"KALIV_AGENT3_ENABLED": "1"' in SOURCE
    and '"KALIV_TOOLS_ENABLED": "1"' in SOURCE,
)
check(
    "paired token and shared approval secret are entered hidden",
    "getpass.getpass" in SOURCE
    and "MODELRIG_TOKEN (skjult, gemmes ikke)" in SOURCE
    and "KALIV_AGENT3_APPROVAL_SECRET (skjult, gemmes ikke)" in SOURCE,
)
check(
    "approval secret is never persisted in operator state",
    '"approval_secret"' not in SOURCE
    and '"MODELRIG_TOKEN":' not in SOURCE
    and '"KALIV_AGENT3_APPROVAL_SECRET":' not in SOURCE,
)
check(
    "wizard contains no merge push tag release or activation command",
    all(
        marker not in SOURCE
        for marker in (
            'git("merge"',
            'git("push"',
            'git("tag"',
            "merge_pull_request",
            "enable_auto_merge",
            '"production_activation": True',
            "production_activation=true",
        )
    ),
)
check(
    "preflight occurs before any positive or negative physical work",
    SOURCE.index("ensure_preflight(") < SOURCE.index("run_positive_cases(")
    < SOURCE.index("run_negative_cases("),
)
check(
    "preflight is the real read-only gate and records an immutable digest",
    "preflight.run_preflight(" in SOURCE
    and "prepared_manifest_sha256" in SOURCE
    and "preflight_sha256" in SOURCE
    and 'report.get("success") is not True' in SOURCE,
)
check(
    "positive runs use exact manifest markers and single-use binding",
    'marker = str(item["marker"])' in SOURCE
    and "pilot.bind_run(manifest, ordinal, run_id)" in SOURCE
    and "pilot._atomic_json(MANIFEST, manifest)" in SOURCE,
)
check(
    "each positive run is immediately checked in all forensic sources",
    "pilot._validate_success_run(" in SOURCE
    and "pilot.load_run_records" in SOURCE
    and "pilot.load_approval_rows" in SOURCE
    and "pilot.load_audit_rows" in SOURCE
    and "marker_count(snapshot, marker)" in SOURCE,
)
check(
    "positive UI and approval both require exact phrases",
    "require_exact(f\"{POSITIVE_ATTEST_PREFIX} {ordinal:02d}\")" in SOURCE
    and "require_exact(f\"{APPROVAL_ATTEST_PREFIX} {ordinal:02d}\")" in SOURCE,
)

with_input("PREVIEWET T-022 01", lambda: module.require_exact("PREVIEWET T-022 01"))
check("exact positive preview attestation is accepted", True)
wrong_failed = False
try:
    with_input("ja", lambda: module.require_exact("PREVIEWET T-022 01"))
except module.OperatorError:
    wrong_failed = True
check("generic yes cannot attest a physical preview", wrong_failed)

with_input("KVITTERING T-022 replay", lambda: module.require_exact("KVITTERING T-022 replay"))
check("exact negative receipt attestation is accepted", True)

check(
    "resume and destructive new-session choices require exact phrases",
    "FORTSÆT T-022" in SOURCE
    and "NY T-022 KAMPAGNE" in SOURCE
    and "Tidligere T-022-session er bevaret" in SOURCE,
)
check(
    "negative evidence is initialized only after positive processing",
    SOURCE.index("run_positive_cases(manifest, paths, adb)")
    < SOURCE.index("run_negative_cases(manifest, paths)"),
)
check(
    "negative cases use the append-only recorder lifecycle",
    "recorder._init(NEGATIVE_JOURNAL, MANIFEST)" in SOURCE
    and "journal.begin_case(" in SOURCE
    and "journal.observe_request(" in SOURCE
    and "journal.finish_case(" in SOURCE
    and "recorder.finalize(NEGATIVE_JOURNAL, MANIFEST)" in SOURCE,
)
check(
    "exact response bodies are captured in real files and bounded",
    'run(["notepad.exe", str(path)], timeout=3600)' in SOURCE
    and "journal_store.MAX_RESPONSE_BYTES" in SOURCE
    and "response_path=response" in SOURCE,
)
check(
    "run ids are entered hidden but retained where the forensic schema requires them",
    "completed run-id (skjult; gemmes kandidatbundet i manifestet)" in SOURCE
    and "Run-id for observation" in SOURCE
    and "run_id=raw_run_id" in SOURCE,
)
check(
    "Android approval client is exact-head built and exactly one device is required",
    '":app:assembleDebug"' in SOURCE
    and '[adb, "install", "-r", str(apk)]' in SOURCE
    and "if len(devices) != 1" in SOURCE
    and module.ANDROID_AGENT3_EXTRA == "dk.ternedal.modelrig.extra.AGENT3",
)
check(
    "desktop and Android use explicit developer surfaces",
    '"--args=--agent3"' in SOURCE
    and "launch_android_agent3(adb)" in SOURCE
    and "launch_desktop_agent3()" in SOURCE,
)
check(
    "the final verdict comes only from the independent forensic collector",
    "pilot.collect_report(" in SOURCE
    and 'if report.get("success") is not True' in SOURCE
    and "pilot._atomic_json(FINAL_REPORT, report)" in SOURCE,
)

for name, statuses, note_delta, approval_delta in (
    ("deny", [200], 0, 0),
    ("timeout", [409], 0, 0),
    ("changed_args", [409], 0, 0),
    ("stale_revision", [409], 0, 0),
    ("replay", [409], 0, 0),
    ("concurrent_approval", [409, 200], 1, 1),
    ("stop_retry_replan", [200, 202, 409], 0, 0),
):
    contract = module.negative_contract(name)
    begin = {"note_count_before": 5, "approval_use_count_before": 7}
    finish = {
        "note_count_after": 5 + note_delta,
        "approval_use_count_after": 7 + approval_delta,
    }
    errors = module.verify_negative_result(
        name=name,
        begin_payload=begin,
        finish_payload=finish,
        statuses=statuses,
    )
    check(f"{name} exact negative contract is accepted", errors == [])

wrong = module.verify_negative_result(
    name="concurrent_approval",
    begin_payload={"note_count_before": 0, "approval_use_count_before": 0},
    finish_payload={"note_count_after": 2, "approval_use_count_after": 2},
    statuses=[200, 200],
)
check(
    "duplicate concurrent success is red",
    any("HTTP-statusser" in error for error in wrong)
    and any("note-delta" in error for error in wrong)
    and any("approval-delta" in error for error in wrong),
)

wrong = module.verify_negative_result(
    name="stop_retry_replan",
    begin_payload={"note_count_before": 1, "approval_use_count_before": 20},
    finish_payload={"note_count_after": 2, "approval_use_count_after": 21},
    statuses=[200, 201],
)
check(
    "short or side-effecting stop retry replan evidence is red",
    any("færre end tre" in error for error in wrong)
    and any("ikke-tilladt" in error for error in wrong)
    and any("note-delta" in error for error in wrong),
)

identity = {
    "version": module.VERSION,
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
}
with tempfile.TemporaryDirectory(prefix="kaliv-t022-operator-") as tmp:
    original_state = module.OPERATOR_STATE
    try:
        module.OPERATOR_STATE = Path(tmp) / "nested" / "state.json"
        paths = {
            "data_dir": Path(tmp) / "data",
            "tools_dir": Path(tmp) / "tools",
            "agent_db": Path(tmp) / "agent.db",
            "approval_db": Path(tmp) / "approval.db",
            "audit_db": Path(tmp) / "audit.db",
            "notes": Path(tmp) / "tools" / "notes.md",
        }
        state = module.save_state(
            identity=identity,
            pilot_id="pilot-1",
            prepared_manifest_sha256="c" * 64,
            paths=paths,
            preflight_sha256="d" * 64,
            status="preflight_green",
        )
        parsed = json.loads(module.OPERATOR_STATE.read_text(encoding="utf-8"))
        check(
            "operator state is atomic, candidate-bound and non-activating",
            parsed == state
            and parsed["production_activation"] is False
            and parsed["candidate"]["git_sha"] == "a" * 40
            and not module.OPERATOR_STATE.with_name(
                module.OPERATOR_STATE.name + ".tmp"
            ).exists(),
        )
        check(
            "operator state contains paths and hashes but no secrets",
            parsed["preflight_sha256"] == "d" * 64
            and "token" not in json.dumps(parsed).lower()
            and "secret" not in json.dumps(parsed).lower(),
        )
    finally:
        module.OPERATOR_STATE = original_state

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-022 PHYSICAL OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
