#!/usr/bin/env python3
from __future__ import annotations

import builtins
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts" / "agent3_write_pilot_negative_one_click.py"
ENTRY_PATH = ROOT / "scripts" / "agent3_write_pilot_negative_operator.py"
LAUNCHER = ROOT / "START_AGENT3_WRITE_PILOT_NEGATIVE.cmd"
RUNBOOK = ROOT / "AGENT3_WRITE_PILOT_NEGATIVE.md"
CORE_SOURCE = code_of(CORE_PATH)
ENTRY_SOURCE = code_of(ENTRY_PATH)
LAUNCHER_SOURCE = code_of(LAUNCHER)
RUNBOOK_SOURCE = code_of(RUNBOOK)

spec = importlib.util.spec_from_file_location("t022_negative_operator_test", ENTRY_PATH)
assert spec is not None and spec.loader is not None
entry = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = entry
spec.loader.exec_module(entry)
core = entry.core

checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


check("negative recorder core exists", CORE_PATH.is_file())
check("safe negative entrypoint exists", ENTRY_PATH.is_file())
check("Windows negative launcher exists", LAUNCHER.is_file())
check("negative operator runbook exists", RUNBOOK.is_file())
check(
    "launcher invokes only the safe entrypoint",
    "agent3_write_pilot_negative_operator.py" in LAUNCHER_SOURCE
    and "agent3_write_pilot_negative_one_click.py" not in LAUNCHER_SOURCE,
)
check(
    "negative stack is pinned to one exact candidate branch",
    'BRANCH = "agent/t022-write-pilot-negative-operator"' in CORE_SOURCE
    and "positive.BRANCH = BRANCH" in CORE_SOURCE
    and "core.positive.main()" in ENTRY_SOURCE,
)
check(
    "operator does not send adversarial HTTP requests",
    "urllib.request" not in CORE_SOURCE
    and 'method="POST"' not in CORE_SOURCE
    and 'method="PUT"' not in CORE_SOURCE
    and 'method="PATCH"' not in CORE_SOURCE
    and 'method="DELETE"' not in CORE_SOURCE,
)
check(
    "existing append-only recorder owns all case transitions",
    "cases_module.begin_case(" in CORE_SOURCE
    and "cases_module.observe_request(" in CORE_SOURCE
    and "cases_module.finish_case(" in CORE_SOURCE
    and "cases_module.finalize(" in CORE_SOURCE,
)
check(
    "all seven exact negative cases are present",
    all(f'"{name}"' in CORE_SOURCE for name in core.CASES)
    and len(core.CASES) == 7,
)
check(
    "negative response bodies and both client screenshots are retained",
    "response-{number}.bin" in CORE_SOURCE
    and "observation-{number}-windows.png" in CORE_SOURCE
    and "observation-{number}-android.png" in CORE_SOURCE,
)
check(
    "ordinary response text is read from clipboard rather than synthesized",
    "Get-Clipboard -Raw" in CORE_SOURCE
    and "Clipboard-response body er tomt" in CORE_SOURCE,
)
check(
    "physical observations store only hashed run identities",
    '"run_id_sha256": common._sha_text(run_id)' in CORE_SOURCE
    and '"run_id": run_id' not in CORE_SOURCE,
)
check(
    "resume requires exact journal to physical-observation parity",
    "len(existing_observations) != len(physical_items)" in CORE_SOURCE
    and "journal og screenshots er uenige" in CORE_SOURCE,
)
check(
    "safe entrypoint measures reused marker baseline instead of assuming zero",
    "note_before = core.note_count" in ENTRY_SOURCE
    and "core.POSITIVE_ORDINALS.get(name)" in ENTRY_SOURCE,
)
check(
    "safe entrypoint resumes an interrupted positive stage on the same branch",
    "should_resume = bool(pending)" in ENTRY_SOURCE
    and "core.positive.main()" in ENTRY_SOURCE
    and "core.ensure_positive_stage = safe_positive_stage" in ENTRY_SOURCE,
)
check(
    "operator-owned evidence remains non-activating",
    CORE_SOURCE.count('"production_activation": False') >= 3
    and "production_activation=false" in CORE_SOURCE,
)
check(
    "runbook leaves forensic collection explicitly open",
    "T-022 er stadig ikke grøn" in RUNBOOK_SOURCE
    and "forensic collector" in RUNBOOK_SOURCE
    and "sender ikke selv et adversarial request" in RUNBOOK_SOURCE,
)

for name, statuses in {
    "deny": [200],
    "timeout": [409],
    "changed_args": [409],
    "stale_revision": [409],
    "replay": [409],
    "concurrent_approval": [409, 200],
    "stop_retry_replan": [200, 202, 409],
}.items():
    try:
        core.validate_statuses(name, statuses)
        ok = True
    except Exception:
        ok = False
    check(f"{name} accepts its exact status contract", ok)

try:
    core.validate_statuses("concurrent_approval", [200, 200])
    bad_concurrent_rejected = False
except core.OperatorError:
    bad_concurrent_rejected = True
check("concurrent approval rejects two successes", bad_concurrent_rejected)

try:
    core.validate_statuses("stop_retry_replan", [200, 409])
    short_stop_rejected = False
except core.OperatorError:
    short_stop_rejected = True
check("stop/retry/replan rejects fewer than three observations", short_stop_rejected)

for name, before_after in {
    "deny": (0, 0, 10, 10),
    "timeout": (0, 0, 10, 10),
    "changed_args": (0, 0, 10, 10),
    "stale_revision": (0, 0, 10, 10),
    "replay": (1, 1, 10, 10),
    "concurrent_approval": (0, 1, 10, 11),
    "stop_retry_replan": (1, 1, 10, 10),
}.items():
    try:
        core.validate_deltas(
            name,
            note_before=before_after[0],
            note_after=before_after[1],
            approval_before=before_after[2],
            approval_after=before_after[3],
        )
        ok = True
    except Exception:
        ok = False
    check(f"{name} accepts its exact note/approval delta", ok)

try:
    core.validate_deltas(
        "replay",
        note_before=1,
        note_after=2,
        approval_before=10,
        approval_after=10,
    )
    replay_duplicate_rejected = False
except core.OperatorError:
    replay_duplicate_rejected = True
check("replay rejects a duplicate append", replay_duplicate_rejected)

original_input = builtins.input
try:
    builtins.input = lambda _prompt: "NEGATIVE REPLAY OBS 1 REGISTRERET"
    core.require_phrase("replay", 1)
    exact_phrase_ok = True
except Exception:
    exact_phrase_ok = False
finally:
    builtins.input = original_input
check("exact negative attestation phrase is accepted", exact_phrase_ok)

try:
    builtins.input = lambda _prompt: "ja"
    try:
        core.require_phrase("replay", 1)
        weak_phrase_rejected = False
    except core.OperatorError:
        weak_phrase_rejected = True
finally:
    builtins.input = original_input
check("ordinary yes cannot attest a negative observation", weak_phrase_rejected)

with tempfile.TemporaryDirectory(prefix="kaliv-t022-negative-entry-") as tmp:
    root = Path(tmp)
    manifest_path = root / "manifest.json"
    notes_path = root / "notes.md"
    approval_path = root / "approvals.db"
    manifest = {
        "pilot_id": "pilot-test",
        "runs": [
            {"ordinal": 1, "marker": "KALIV-T022:test:P:01:a", "run_id": "run-1"},
            {"ordinal": 2, "marker": "KALIV-T022:test:P:02:b", "run_id": "run-2"},
        ],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    notes_path.write_text("KALIV-T022:test:P:01:a\nKALIV-T022:test:P:02:b\n", encoding="utf-8")
    approval_path.write_bytes(b"fixture")

    old_manifest = core.MANIFEST
    old_load = core.common._load_json
    old_note_count = core.note_count
    old_approval_count = core.approval_count
    old_begin = core.cases_module.begin_case
    old_verify = core.store.verify_journal
    old_state = core.store._state
    core.MANIFEST = manifest_path
    core.common._load_json = lambda _path: (manifest, b"manifest")
    core.note_count = lambda path, marker: path.read_text(encoding="utf-8").count(marker)
    core.approval_count = lambda _path: 20
    captured: dict[str, object] = {}

    def fake_begin(**kwargs):
        captured.update(kwargs)
        return "a" * 32, manifest["runs"][kwargs["positive_ordinal"] - 1]["marker"]

    core.cases_module.begin_case = fake_begin
    core.store.verify_journal = lambda _path: ([{"kind": "fixture"}], "f" * 64)
    core.store._state = lambda _rows: (
        {},
        {
            "a" * 32: {
                "begin": {"payload": {"marker": captured.get("marker", manifest["runs"][0]["marker"])}},
                "observations": [],
                "finish": None,
            }
        },
    )
    case_id, marker, _state = entry.safe_case_start(
        name="replay",
        index={},
        paths={"notes": notes_path, "approval_db": approval_path},
    )
    check(
        "replay begins with the real existing positive marker count",
        case_id == "a" * 32
        and marker == manifest["runs"][0]["marker"]
        and captured.get("note_count") == 1
        and captured.get("approval_count") == 20
        and captured.get("positive_ordinal") == 1,
    )

    captured.clear()
    core.cases_module.begin_case = lambda **kwargs: (
        captured.update(kwargs) or "b" * 32,
        "KALIV-T022:test:N:deny",
    )
    core.store._state = lambda _rows: (
        {},
        {
            "b" * 32: {
                "begin": {"payload": {"marker": "KALIV-T022:test:N:deny"}},
                "observations": [],
                "finish": None,
            }
        },
    )
    entry.safe_case_start(
        name="deny",
        index={},
        paths={"notes": notes_path, "approval_db": approval_path},
    )
    check(
        "unique negative marker begins at zero without a positive ordinal",
        captured.get("note_count") == 0
        and captured.get("positive_ordinal") is None,
    )

    core.MANIFEST = old_manifest
    core.common._load_json = old_load
    core.note_count = old_note_count
    core.approval_count = old_approval_count
    core.cases_module.begin_case = old_begin
    core.store.verify_journal = old_verify
    core.store._state = old_state

with tempfile.TemporaryDirectory(
    prefix="kaliv-t022-negative-response-",
    dir=ROOT,
) as tmp:
    old_evidence = core.EVIDENCE_DIR
    core.EVIDENCE_DIR = Path(tmp)
    artifact = core.response_artifact("deny", 1, '{"status":"denied"}\n')
    raw = (Path(tmp) / "deny" / "response-1.bin").read_bytes()
    check(
        "response artifact preserves exact UTF-8 body and hash",
        raw == b'{"status":"denied"}\n'
        and artifact["sha256"] == core.hashlib.sha256(raw).hexdigest()
        and artifact["bytes"] == len(raw),
    )
    core.EVIDENCE_DIR = old_evidence

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-022 NEGATIVE PHYSICAL OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
