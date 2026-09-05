#!/usr/bin/env python3
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent3_termination_ui_physical_one_click.py"
SOURCE = code_of(SCRIPT)
spec = importlib.util.spec_from_file_location("t023_physical_operator", SCRIPT)
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
    "operator is version-bound to its own exact branch",
    module.BRANCH == "agent/t023-termination-physical-operator"
    and module.VERSION == "1.58.146",
)
check(
    "normal Android task surface uses only the explicit task extra",
    module.ANDROID_TASK_EXTRA == "dk.ternedal.modelrig.extra.AGENT3_TASK"
    and 'extra = ANDROID_TASK_EXTRA if surface == "normal_task" else ANDROID_AGENT3_EXTRA'
    in SOURCE,
)
check(
    "desktop surfaces use the normal task and developer arguments",
    'arg = "--tasks" if surface == "normal_task" else "--agent3"' in SOURCE,
)
check(
    "wizard performs exact readiness validation without production activation",
    module.READINESS_PATH == "/api/v1/experimental/agent3/task-readiness"
    and 'readiness.get("selected_surface") != "agent3_readonly"' in SOURCE
    and 'readiness.get("production_activation") is not False' in SOURCE
    and 'readiness.get("normal_chat_route_unchanged") is not True' in SOURCE,
)
check(
    "Android artifact is a real adb screencap",
    'run([adb, "exec-out", "screencap", "-p"], capture=True, binary=True)' in SOURCE,
)
check(
    "Windows artifact is a real screen capture",
    "CopyFromScreen" in SOURCE and "System.Windows.Forms.Screen" in SOURCE,
)
check(
    "raw run identity is hashed and deleted",
    'sha256_bytes(raw_run_id.encode("utf-8"))' in SOURCE and "del raw_run_id" in SOURCE,
)
check(
    "wizard never writes a production activation true claim",
    '"production_activation": True' not in SOURCE
    and "production_activation=true" not in SOURCE.lower(),
)
check(
    "wizard contains no merge push tag or release command",
    all(
        marker not in SOURCE
        for marker in (
            'git("merge"',
            'git("push"',
            'git("tag"',
            "merge_pull_request",
            "enable_auto_merge",
        )
    ),
)

with_input(
    "OBSERVERET android non_interruptible",
    lambda: module.require_phrase("OBSERVERET", "android", "non_interruptible"),
)
check("exact observation phrase is accepted", True)

wrong_failed = False
try:
    with_input(
        "ja",
        lambda: module.require_phrase("OBSERVERET", "android", "non_interruptible"),
    )
except module.OperatorError:
    wrong_failed = True
check("generic confirmation cannot attest a physical case", wrong_failed)

with_input(
    "KVITTERING windows late_completion",
    lambda: module.require_phrase("KVITTERING", "windows", "late_completion"),
)
check("exact receipt phrase is accepted", True)

identity = {
    "version": "1.58.146",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "identity_source": "git",
}
base_inventory = {
    "none": ["tool:rig_status"],
    "cooperative": ["tool:pull_model"],
    "runtime": [],
}
observations = module.physical.prepare_observations(
    operator="Anders",
    identity=identity,
    inventory=base_inventory,
)
required = module.physical._required_cases(base_inventory)
check(
    "today's candidate has only the three honest base cases",
    required == ("non_interruptible", "cooperative_declaration", "late_completion"),
)

runtime_inventory = dict(base_inventory)
runtime_inventory["runtime"] = ["tool:runtime_demo"]
check(
    "runtime-bound case appears only with an actual runtime capability",
    module.physical._required_cases(runtime_inventory)
    == (
        "non_interruptible",
        "cooperative_declaration",
        "late_completion",
        "runtime_bound",
    ),
)

all_cases = [
    case
    for platform_value in observations["platforms"].values()
    for case in platform_value["cases"]
]
check(
    "prepared physical observations are red and cannot pass by construction",
    all(
        case["run_id_sha256"] == ""
        and case["artifact_sha256"] == ""
        and case["receipt"]["plan"]["state_before"] == ""
        and case["ui"]["shows_plan_scope"] is False
        and case["ui"]["normal_chat_unchanged"] is False
        for case in all_cases
    ),
)
check(
    "prepared observations preserve the non-activation boundary",
    observations["production_activation"] is False,
)

late_android = module.case_by_name(observations, "android", "late_completion")
check(
    "case lookup returns the exact platform-bound case",
    late_android["name"] == "late_completion"
    and late_android["surface"] == "normal_task",
)

missing_failed = False
try:
    module.case_by_name(observations, "android", "runtime_bound")
except module.OperatorError:
    missing_failed = True
check("wizard cannot invent a missing runtime case", missing_failed)

run_id = "opaque-run-123"
check(
    "run-id digest is deterministic SHA-256",
    module.sha256_bytes(run_id.encode("utf-8"))
    == hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
)

with tempfile.TemporaryDirectory(prefix="kaliv-t023-operator-") as tmp:
    path = Path(tmp) / "nested" / "receipt.json"
    module.atomic_json(path, {"production_activation": False, "value": "æøå"})
    parsed = json.loads(path.read_text(encoding="utf-8"))
    check(
        "operator state is written atomically as valid UTF-8 JSON",
        parsed == {"production_activation": False, "value": "æøå"}
        and not path.with_name(path.name + ".tmp").exists(),
    )

check(
    "each recorded case requires both observation and receipt attestations",
    "require_phrase(ATTEST_PREFIX, platform_name, case_name)" in SOURCE
    and "require_phrase(RECEIPT_PREFIX, platform_name, case_name)" in SOURCE,
)
check(
    "final report is produced only through the independent verifier",
    "physical.verify_report(" in SOURCE
    and 'if not report.get("success")' in SOURCE,
)
check(
    "candidate composition stays additive and non-authoritative",
    '"physical_validation_termination_campaign.py"' in SOURCE
    and '"--stage"' in SOURCE
    and '"candidate"' in SOURCE
    and "check=False" in SOURCE,
)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-023 PHYSICAL OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
