"""Contract test: every repository and landed DevControl test is reached by CI.

Run: python3 tests/workflow_test_coverage.py
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
workflow = (root / ".github/workflows/_tests.yml").read_text(encoding="utf-8")
sys.path.insert(0, str(root / "devcontrol/src"))

from kaliv_dev_control.catalog import (
    CatalogError,
    ModelRigCommandCatalog,
    ProjectCommandSpec,
    TaskBoundCommandRegistry,
    modelrig_command_catalog,
)
from kaliv_dev_control.commands import CommandPolicyError, CommandTemplate
from kaliv_dev_control.contract import DevelopmentTask

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


match = re.search(r"for f in ([^;]+); do", workflow)
check(match is not None, "the workflow still runs repository tests through a readable glob loop")
if match is None:
    raise SystemExit(1)
patterns = match.group(1).split()
check(len(patterns) >= 2, f"repository test globs found: {' '.join(patterns)}")

repository_tests = sorted(
    path.relative_to(root).as_posix() for path in (root / "tests").glob("*.py")
)
missed = [
    path
    for path in repository_tests
    if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
]
check(len(repository_tests) > 10, f"{len(repository_tests)} repository test files on disk")
check(not missed, "every repository test file matches a CI pattern" if not missed else f"unreached: {missed}")

self_test = ["tests/agent_smoke.py", "tests/worker_unit.py"]
self_test_missed = [
    path
    for path in self_test
    if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
]
check(self_test_missed == ["tests/agent_smoke.py"], "coverage self-test detects a file outside CI globs")

command = (
    "PYTHONPATH=devcontrol/src python3 -m unittest discover "
    "-s devcontrol/tests -p 'test_*.py' -v"
)
check(command in workflow, "CI runs the exact DevControl unittest discovery command")

expected_modules = {
    "test_bounded_subprocess.py",
    "test_campaign_review.py",
    "test_durable_publication.py",
    "test_foundation.py",
    "test_h10k_tier_a_environment_extraction.py",
    "test_h10l_tier_a_error_extraction.py",
    "test_h10m_tier_a_lease_model_extraction.py",
    "test_h10n_tier_a_path_authority_extraction.py",
    "test_h10o_tier_a_materialization_extraction.py",
    "test_h10q_tier_a_legacy_plan_extraction.py",
    "test_h10r_tier_a_legacy_runner_extraction.py",
    "test_physical_isolation_durable_publication_h10b.py",
    "test_proposal_reload.py",
    "test_review_reload.py",
    "test_runtime_staging_concurrency_h10h.py",
    "test_slice10_runtime_staging.py",
    "test_slice10b_runtime_binding.py",
    "test_slice10c_output_result.py",
    "test_slice10d_runtime_closure.py",
    "test_slice10e_version_check_closure.py",
    "test_slice2.py",
    "test_slice5.py",
    "test_slice6.py",
    "test_slice6_hardening.py",
    "test_slice9.py",
    "test_slice9_schemas.py",
    "test_store_proposal.py",
    "test_streaming_publication_h10g.py",
}
observed_modules = {
    path.name for path in (root / "devcontrol/tests").glob("test_*.py")
}
check(
    observed_modules == expected_modules,
    f"the twenty-eight DC-L01–L08 test modules are present: {sorted(observed_modules)}",
)

receipt_schema = json.loads(
    (root / "devcontrol/schemas/development-github-read-receipt-v1.schema.json").read_text(encoding="utf-8")
)
repository_pattern = re.compile(receipt_schema["properties"]["repository"]["pattern"])
check(repository_pattern.fullmatch("Ternedal/ModelRig") is not None, "receipt schema accepts canonical ModelRig repository")
check(
    all(
        repository_pattern.fullmatch(value) is None
        for value in ("./ModelRig", "Ternedal/..", "Ternedal/Model Rig", "Ternedal/\x00ModelRig")
    ),
    "receipt schema rejects dot segments, whitespace and NUL authority",
)

catalog = modelrig_command_catalog()
check(isinstance(catalog, ModelRigCommandCatalog) and catalog.command_ids == (), "DC-L03 default command catalog is empty and dormant")
removed_ids = (
    "modelrig.version.check",
    "modelrig.devcontrol.tests",
    "modelrig.workflow.test-coverage",
    "modelrig.backend.vet",
    "modelrig.backend.tests",
)
removed = True
for command_id in removed_ids:
    try:
        catalog.resolve(command_id)
    except CatalogError:
        continue
    removed = False
check(removed, "no Python or Go command ID is exposed by the default catalog")

runtime_closed = True
for tool_id in ("python", "go", "sandbox"):
    try:
        ProjectCommandSpec(
            "modelrig.runtime.probe",
            tool_id,
            ("probe",),
            ".",
            10,
            {},
        )
    except CatalogError:
        continue
    runtime_closed = False
check(runtime_closed, "Python, Go and direct sandbox command runtimes fail closed")

static_spec = ProjectCommandSpec(
    "modelrig.static.probe",
    "statictool",
    ("probe",),
    ".",
    10,
    {"CI": "1"},
)
check(
    dict(static_spec.env)
    == {
        "CI": "1",
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "LC_CTYPE": "C",
        "TZ": "UTC",
    },
    "custom static commands receive the fixed reviewed process environment",
)

blocked_environment = True
for key, value in (
    ("PATH", "/attacker/bin"),
    ("PYTHONPATH", "."),
    ("PYTHONUSERBASE", "."),
    ("GOROOT", "."),
    ("GOTOOLCHAIN", "auto"),
    ("LD_PRELOAD", "/tmp/x.so"),
):
    try:
        ProjectCommandSpec(
            "modelrig.static.probe",
            "statictool",
            ("probe",),
            ".",
            10,
            {key: value},
        )
    except CatalogError:
        continue
    blocked_environment = False
check(blocked_environment, "ambient loader, interpreter, toolchain and PATH authority is rejected")

snapshot_task = DevelopmentTask.from_mapping(
    {
        "schema": "kaliv-development-task/v1",
        "task_id": "DC_L03_SNAPSHOT",
        "repository": "Ternedal/ModelRig",
        "base_sha": "a" * 40,
        "goal": "Prove exact task binding.",
        "acceptance_criteria": ["Registry cannot be retargeted."],
        "risk": "low",
        "allowed_paths": ["devcontrol/**"],
        "protected_paths": [".github/**"],
        "allowed_command_ids": ["modelrig.static.probe"],
        "required_tests": ["exact task binding"],
        "budget": {
            "max_changed_files": 1,
            "max_added_lines": 1,
            "max_deleted_lines": 0,
            "max_attempts": 1,
            "max_runtime_seconds": 30,
            "max_output_bytes": 4096,
        },
        "merge_authority": "human",
    }
)
registry = TaskBoundCommandRegistry(
    (
        CommandTemplate(
            "modelrig.static.probe",
            ("/proc/self/fd/100", "probe"),
            ".",
            30,
            {"PATH": "/usr/bin:/bin"},
        ),
    ),
    snapshot_task,
    object(),
    "/proc/self/fd/101",
)
private_task = registry.execution_task(snapshot_task)
check(private_task is not snapshot_task and private_task.canonical_json() == snapshot_task.canonical_json(), "registry reconstructs one private exact-task snapshot")
check(registry.sandbox_bootstrap_mode(private_task) == "static", "task-bound registry uses the static sandbox protocol")
retargeted = DevelopmentTask.from_mapping({**snapshot_task.to_dict(), "base_sha": "b" * 40})
try:
    registry.resolve(retargeted, "modelrig.static.probe")
except CommandPolicyError:
    retarget_rejected = True
else:
    retarget_rejected = False
check(retarget_rejected, "task-bound registry rejects cross-task retargeting")

native_windows_contracts = (
    "tests/support/windows_job_contract.py",
    "tests/support/windows_job_close_contract.py",
    "tests/support/windows_restricted_contract.py",
    "tests/support/windows_tier_a_environment_contract.py",
    "tests/worker_toolhost.py",
    "tests/support/windows_bounded_subprocess_contract.py",
    "tests/support/windows_catalog_tier_a_contract.py",
)
check(
    all(path in workflow for path in native_windows_contracts),
    "CI reaches every landed product-side and DC-L08 native Windows contract",
)
check(
    "tests/support/windows_tier_a_receipt_contract.py" not in workflow,
    "DC-L08 leaves the command-receipt Windows contract deferred to DC-L09",
)
check(
    "kaliv_dev_control.tier_a_execution_v3" in workflow
    and "kaliv_dev_control.tier_a_execution\"" not in workflow,
    "CI activates the private v3 executor without landing the final public facade",
)

product_modules = (
    "worker/app/toolhost.py",
    "worker/app/windows_capture.py",
    "worker/app/windows_job.py",
    "worker/app/windows_restricted.py",
    "worker/app/windows_runtime_guard.py",
    "worker/app/windows_tier_a.py",
)
check(
    all(
        "kaliv_dev_control" not in (root / path).read_text(encoding="utf-8")
        for path in product_modules
    ),
    "landed product code does not import DevControl",
)

allowlist = json.loads(
    (root / "docs/devcontrol/dc-l03/exact-path-allowlist.json").read_text(encoding="utf-8")
)
paths = allowlist.get("paths") or allowlist.get("allowed_paths")
check(isinstance(paths, list) and len(paths) == 16 and len(set(paths)) == 16, "DC-L03 exact path allowlist contains 16 unique paths")

print(f"\n===== TEST COVERAGE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
