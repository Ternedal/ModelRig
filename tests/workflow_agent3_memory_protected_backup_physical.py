#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "scripts" / "agent3_memory_protected_backup_physical_gate.py"
OPERATOR_PATH = ROOT / "scripts" / "agent3_memory_protected_backup_physical.py"
ADAPTER_PATH = ROOT / "scripts" / "proof_t033_current.py"
LAUNCHER_PATH = ROOT / "START_AGENT3_MEMORY_BACKUP_PHYSICAL.cmd"
DOC_PATH = ROOT / "AGENT3_MEMORY_PROTECTED_BACKUP_PHYSICAL.md"

gate_spec = importlib.util.spec_from_file_location("t033_backup_physical_gate_test", GATE_PATH)
assert gate_spec is not None and gate_spec.loader is not None
gate = importlib.util.module_from_spec(gate_spec)
gate_spec.loader.exec_module(gate)

adapter_spec = importlib.util.spec_from_file_location("t033_campaign_id_adapter_test", ADAPTER_PATH)
assert adapter_spec is not None and adapter_spec.loader is not None
adapter = importlib.util.module_from_spec(adapter_spec)
adapter_spec.loader.exec_module(adapter)

NOW = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
CANDIDATE = {
    "version": "1.58.147",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
}
CAMPAIGN_ID = "t033-20260729-080000-abcd1234"
OWNER_SID = "S-1-5-21-1000-2000-3000-1001"
PROBE_SID = "S-1-5-21-1000-2000-3000-1002"

checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def raises_runtime(fn) -> bool:
    try:
        fn()
    except RuntimeError:
        return True
    return False


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def make_baseline(root: Path):
    campaign_rel = Path(
        "validation/agent3-memory-protected-backup-physical"
    ) / CAMPAIGN_ID
    campaign = root / campaign_rel
    campaign.mkdir(parents=True)
    artifact_names = {
        "source_database": b"source-ciphertext",
        "backup_database": b"backup-ciphertext",
        "backup_manifest": b'{"schema":"backup"}\n',
        "restored_database": b"restored-ciphertext",
        "same_user_log": b'{"raw_values_logged":false}\n',
        "probe_request": b'{"production_activation":false}\n',
    }
    artifacts = []
    for name, raw in artifact_names.items():
        suffix = ".sqlite3" if "database" in name else ".json"
        path = campaign / f"{name}{suffix}"
        path.write_bytes(raw)
        artifacts.append(
            {
                "name": name,
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha(raw),
                "bytes": len(raw),
            }
        )
    state = {
        "schema": gate.STATE_SCHEMA,
        "prepared_at": NOW.isoformat().replace("+00:00", "Z"),
        "campaign_id": CAMPAIGN_ID,
        "campaign_path": str(campaign_rel).replace("\\", "/"),
        "operator": "Anders",
        "candidate": copy.deepcopy(CANDIDATE),
        "owner": {"username": "rig\\anders", "sid": OWNER_SID},
        "canaries": {
            "private_value_sha256": "c" * 64,
            "private_source_sha256": "d" * 64,
            "secret_value_sha256": "e" * 64,
            "memory_ids": {"private": "memory-private", "secret": "memory-secret"},
        },
        "checks": {
            "source_migrated": True,
            "bundle_verified": True,
            "same_user_restore": True,
            "destination_absent_before_restore": True,
            "protected_values_reopened": 2,
            "restored_single_file": True,
            "sensitive_plaintext_matches": 0,
            "scanned_files": [item["path"] for item in artifacts],
        },
        "artifacts": artifacts,
        "probe_request": {
            "public_request_path": "C:/Users/Public/Documents/Kaliv-T033/request.json",
            "public_probe_path": "C:/Users/Public/Documents/Kaliv-T033/probe.json",
            "backup_database_sha256": next(
                item["sha256"] for item in artifacts if item["name"] == "backup_database"
            ),
        },
        "production_activation": False,
    }
    backup_digest = next(
        item["sha256"] for item in artifacts if item["name"] == "backup_database"
    )
    probe = {
        "schema": gate.PROBE_SCHEMA,
        "observed_at": (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "campaign_id": CAMPAIGN_ID,
        "candidate": copy.deepcopy(CANDIDATE),
        "owner_sid": OWNER_SID,
        "probe_identity": {"username": "rig\\probe", "sid": PROBE_SID},
        "backup_database_sha256": backup_digest,
        "result": "dpapi_denied",
        "error_type": "ProtectedMemoryBackupError",
        "error_code": "current_key_scope_denied",
        "destination_absent": True,
        "production_activation": False,
    }
    return state, probe, campaign


def judge(root: Path, state, probe, *, candidate=CANDIDATE, now=NOW + timedelta(minutes=10)):
    return gate.judge(
        root=root,
        state=state,
        probe=probe,
        candidate=candidate,
        now=now,
    )[0]


with tempfile.TemporaryDirectory(prefix="kaliv-t033-physical-") as tmp:
    root = Path(tmp)
    state, probe, campaign = make_baseline(root)
    check("complete physical evidence baseline is green", judge(root, state, probe) == [])

    changed = copy.deepcopy(state)
    changed["candidate"]["git_sha"] = "f" * 40
    check(
        "candidate drift fails closed",
        any("candidate.git_sha mismatch" in error for error in judge(root, changed, probe)),
    )

    changed_probe = copy.deepcopy(probe)
    changed_probe["probe_identity"]["sid"] = OWNER_SID
    check(
        "same Windows SID cannot satisfy cross-user scope",
        any("owner Windows SID" in error for error in judge(root, state, changed_probe)),
    )

    changed_probe = copy.deepcopy(probe)
    changed_probe["result"] = "unexpected_success"
    changed_probe["error_type"] = None
    changed_probe["error_code"] = "cross_user_restore_succeeded"
    changed_probe["destination_absent"] = False
    errors = judge(root, state, changed_probe)
    check(
        "cross-user success and visible destination fail",
        any("did not prove DPAPI denial" in error for error in errors)
        and any("visible restore destination" in error for error in errors),
    )

    changed = copy.deepcopy(state)
    changed["checks"]["sensitive_plaintext_matches"] = 1
    check(
        "plaintext canary discovery fails",
        any("plaintext was found" in error for error in judge(root, changed, probe)),
    )

    changed = copy.deepcopy(state)
    changed["checks"]["protected_values_reopened"] = 1
    check(
        "incomplete same-user key-open coverage fails",
        any("exactly two" in error for error in judge(root, changed, probe)),
    )

    artifact = next(item for item in state["artifacts"] if item["name"] == "backup_database")
    artifact_path = root / artifact["path"]
    original = artifact_path.read_bytes()
    artifact_path.write_bytes(original + b"tamper")
    check(
        "artifact tamper fails",
        any("mismatch" in error for error in judge(root, state, probe)),
    )
    artifact_path.write_bytes(original)

    changed_probe = copy.deepcopy(probe)
    changed_probe["backup_database_sha256"] = "0" * 64
    check(
        "probe bundle digest drift fails",
        any("backup digest mismatch" in error for error in judge(root, state, changed_probe)),
    )

    stale_state = copy.deepcopy(state)
    stale_state["prepared_at"] = (NOW - timedelta(hours=25)).isoformat().replace(
        "+00:00", "Z"
    )
    check(
        "stale physical evidence fails",
        any("old" in error or "spans" in error for error in judge(root, stale_state, probe)),
    )

    future_probe = copy.deepcopy(probe)
    future_probe["observed_at"] = (NOW + timedelta(hours=2)).isoformat().replace(
        "+00:00", "Z"
    )
    check(
        "future probe fails",
        any("future" in error for error in judge(root, state, future_probe)),
    )

    changed = copy.deepcopy(state)
    changed["production_activation"] = True
    check(
        "production activation fails closed",
        any("activated production" in error for error in judge(root, changed, probe)),
    )

check("canonical campaign id is accepted", adapter._validated_campaign_id(CAMPAIGN_ID) == CAMPAIGN_ID)
bad_ids = (
    "",
    "t033-20260729-080000-ABCDEF12",
    "t033-20260729-080000-abc123",
    "../" + CAMPAIGN_ID,
    CAMPAIGN_ID + "/probe",
    CAMPAIGN_ID + "\\probe",
)
check(
    "campaign-id path addressing fails closed on malformed values",
    all(raises_runtime(lambda value=value: adapter._validated_campaign_id(value)) for value in bad_ids),
)

original_public = os.environ.get("PUBLIC")
with tempfile.TemporaryDirectory(prefix="t033-public-") as tmp:
    os.environ["PUBLIC"] = tmp
    paths = adapter._campaign_paths(CAMPAIGN_ID)
    expected_public = Path(tmp) / "Documents" / "Kaliv-T033" / CAMPAIGN_ID
    expected_state = (
        ROOT
        / "validation"
        / "agent3-memory-protected-backup-physical"
        / CAMPAIGN_ID
        / "state.json"
    )
    check("campaign id derives canonical public request", paths["request"] == expected_public / "request.json")
    check("campaign id derives canonical public probe", paths["probe"] == expected_public / "probe.json")
    check("campaign id derives canonical repository state", paths["state"] == expected_state)
    check(
        "probe campaign-id expands to existing physical operator args",
        adapter._expand_campaign_args(["probe", "--campaign-id", CAMPAIGN_ID])
        == [
            "probe",
            "--request",
            str(expected_public / "request.json"),
            "--output",
            str(expected_public / "probe.json"),
        ],
    )
    check(
        "collect campaign-id expands to existing physical operator args",
        adapter._expand_campaign_args(["collect", "--campaign-id", CAMPAIGN_ID])
        == ["collect", "--state", str(expected_state), "--probe", str(expected_public / "probe.json")],
    )

if original_public is None:
    os.environ.pop("PUBLIC", None)
else:
    os.environ["PUBLIC"] = original_public

legacy = ["probe", "--request", "request.json", "--output", "probe.json"]
check("legacy explicit-path mode is unchanged", adapter._expand_campaign_args(legacy) == legacy)
check(
    "campaign-id cannot be mixed with explicit paths",
    raises_runtime(
        lambda: adapter._expand_campaign_args(
            ["probe", "--campaign-id", CAMPAIGN_ID, "--output", "elsewhere.json"]
        )
    ),
)
check(
    "campaign-id is restricted to probe or collect",
    raises_runtime(lambda: adapter._expand_campaign_args(["prepare", "--campaign-id", CAMPAIGN_ID])),
)

with tempfile.TemporaryDirectory(prefix="t033-campaign-state-") as tmp:
    original_campaign_root = adapter.CAMPAIGN_ROOT
    adapter.CAMPAIGN_ROOT = Path(tmp)
    try:
        campaign = adapter.CAMPAIGN_ROOT / CAMPAIGN_ID
        campaign.mkdir(parents=True)
        (campaign / "state.json").write_text(
            json.dumps({"campaign_id": CAMPAIGN_ID, "candidate": {"git_sha": CANDIDATE["git_sha"]}}),
            encoding="utf-8",
        )
        check(
            "prepare hint resolves state bound to exact candidate",
            adapter._latest_campaign_id(CANDIDATE["git_sha"]) == CAMPAIGN_ID,
        )
        check(
            "state from another candidate cannot become hint authority",
            adapter._latest_campaign_id("b" * 40) is None,
        )
    finally:
        adapter.CAMPAIGN_ROOT = original_campaign_root

operator_text = code_of(OPERATOR_PATH)
adapter_text = code_of(ADAPTER_PATH)
gate_text = code_of(GATE_PATH)
launcher_text = code_of(LAUNCHER_PATH)
doc_text = code_of(DOC_PATH)
doc_lower = doc_text.lower()

check(
    "operator is three-phase and Windows-only",
    all(token in operator_text for token in ('sub.add_parser("prepare")', 'sub.add_parser("probe")', 'sub.add_parser("collect")'))
    and 'platform.system() != "Windows"' in operator_text,
)
check(
    "operator requires exact human attestation",
    "JEG HAR KØRT T-033 BACKUP RESTORE PÅ WINDOWS RIGGEN" in operator_text
    and "operator attestation did not match" in operator_text,
)
check(
    "operator proves a distinct Windows SID",
    'identity["sid"].lower() == str(owner_sid).lower()' in operator_text
    and 'result = "same_sid"' in operator_text,
)
check(
    "operator never stores raw protected canaries in state",
    '"private_value_sha256"' in operator_text
    and '"private_source_sha256"' in operator_text
    and '"secret_value_sha256"' in operator_text
    and '"private_value": private_value' not in operator_text
    and '"secret_value": secret_value' not in operator_text,
)
check(
    "operator scans UTF-8 and UTF-16 artifacts",
    '("utf-8", "utf-16-le", "utf-16-be")' in operator_text
    and '"sensitive_plaintext_matches": matches' in operator_text,
)
check(
    "cross-user probe accepts only bounded DPAPI denial",
    'result = "dpapi_denied"' in operator_text
    and '"current_key_scope_denied"' in operator_text
    and '"dpapi_unprotect_denied"' in operator_text,
)
check(
    "launcher defaults to prepare and preserves failures",
    "memory_protected_backup_physical.py prepare" in launcher_text
    and "exit /b %EXIT_CODE%" in launcher_text,
)
check(
    "gate is independent and always non-activating",
    "The gate never decrypts memory" in gate_text
    and '"production_activation": False' in gate_text,
)
check(
    "adapter delegates translated args to unchanged physical operator",
    "expanded = _expand_campaign_args(values)" in adapter_text
    and "result = int(op.main(expanded))" in adapter_text,
)
check(
    "adapter prints short runas campaign-id probe after prepare",
    "runas /user:<ANDEN-BRUGER>" in adapter_text
    and "probe --campaign-id {campaign_id}" in adapter_text,
)
check(
    "runbook binds campaign-id to ergonomics only",
    "--campaign-id" in doc_text
    and "operator ergonomics only" in doc_lower
    and "same physical windows" in doc_lower
    and "dpapi" in doc_lower,
)
check(
    "runbook states CI is not physical rig proof",
    "CI is not" in doc_text
    and "actual ModelRig Windows profile" in doc_text
    and "production" in doc_text,
)
check(
    "operator exposes no merge release or production action",
    all(token not in operator_text for token in ("git push", "git merge", "gh pr merge", "production_activation\": True")),
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 PHYSICAL BACKUP OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
