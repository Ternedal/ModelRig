#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "scripts" / "proof_t033_current.py"
DOC_PATH = ROOT / "AGENT3_MEMORY_PROTECTED_BACKUP_PHYSICAL.md"

spec = importlib.util.spec_from_file_location("t033_campaign_id_adapter_test", ADAPTER_PATH)
assert spec is not None and spec.loader is not None
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

CAMPAIGN_ID = "t033-20260824-104800-abcd1234"
CANDIDATE_SHA = "a" * 40
checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def raises_runtime(fn) -> bool:
    try:
        fn()
    except RuntimeError:
        return True
    return False


check("canonical campaign id is accepted", adapter._validated_campaign_id(CAMPAIGN_ID) == CAMPAIGN_ID)

bad_ids = (
    "",
    "t033-20260824-104800-ABCDEF12",
    "t033-20260824-104800-abc123",
    "t033-20260824-104800-abcdef1234",
    "../" + CAMPAIGN_ID,
    CAMPAIGN_ID + "/probe",
    CAMPAIGN_ID + "\\probe",
    "x" + CAMPAIGN_ID,
)
check(
    "path-like malformed and non-canonical ids fail closed",
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
    check("campaign id derives the canonical public request", paths["request"] == expected_public / "request.json")
    check("campaign id derives the canonical public probe", paths["probe"] == expected_public / "probe.json")
    check("campaign id derives the canonical repository state", paths["state"] == expected_state)
    check(
        "probe campaign-id mode expands to the existing physical operator arguments",
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
        "collect campaign-id mode expands to the existing physical operator arguments",
        adapter._expand_campaign_args(["collect", "--campaign-id", CAMPAIGN_ID])
        == ["collect", "--state", str(expected_state), "--probe", str(expected_public / "probe.json")],
    )

if original_public is None:
    os.environ.pop("PUBLIC", None)
else:
    os.environ["PUBLIC"] = original_public

legacy = ["probe", "--request", "request.json", "--output", "probe.json"]
check("legacy explicit-path probe mode is unchanged", adapter._expand_campaign_args(legacy) == legacy)
check(
    "campaign-id cannot be mixed with explicit output paths",
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
        older = adapter.CAMPAIGN_ROOT / "t033-20260824-100000-11111111"
        older.mkdir(parents=True)
        (older / "state.json").write_text(
            json.dumps({"campaign_id": older.name, "candidate": {"git_sha": CANDIDATE_SHA}}),
            encoding="utf-8",
        )
        newest = adapter.CAMPAIGN_ROOT / CAMPAIGN_ID
        newest.mkdir()
        (newest / "state.json").write_text(
            json.dumps({"campaign_id": CAMPAIGN_ID, "candidate": {"git_sha": CANDIDATE_SHA}}),
            encoding="utf-8",
        )
        check(
            "prepare hint resolves the newest state bound to the exact candidate",
            adapter._latest_campaign_id(CANDIDATE_SHA) == CAMPAIGN_ID,
        )
        check(
            "state from another candidate cannot become the campaign hint",
            adapter._latest_campaign_id("b" * 40) is None,
        )
    finally:
        adapter.CAMPAIGN_ROOT = original_campaign_root

adapter_text = ADAPTER_PATH.read_text(encoding="utf-8")
doc_text = DOC_PATH.read_text(encoding="utf-8")
doc_lower = doc_text.lower()
check(
    "adapter delegates to the unchanged physical operator after path expansion",
    "expanded = _expand_campaign_args(values)" in adapter_text
    and "result = int(op.main(expanded))" in adapter_text,
)
check(
    "adapter prints the short runas campaign-id probe after prepare",
    "runas /user:<ANDEN-BRUGER>" in adapter_text
    and "probe --campaign-id {campaign_id}" in adapter_text,
)
check(
    "runbook documents campaign-id as ergonomics rather than new evidence semantics",
    "--campaign-id" in doc_text
    and "operator ergonomics only" in doc_lower
    and "same physical windows" in doc_lower
    and "dpapi" in doc_lower,
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 CAMPAIGN-ID OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
