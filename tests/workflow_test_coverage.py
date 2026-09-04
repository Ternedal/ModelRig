"""Contract test: every repository and landed DevControl test is reached by CI.

Run: python3 tests/workflow_test_coverage.py
"""
from __future__ import annotations

import fnmatch
import importlib
import importlib.util
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
    "test_asymmetric_authority.py",
    "test_bounded_subprocess.py",
    "test_campaign_review.py",
    "test_draft_pr_readiness_durable_h10.py",
    "test_durable_publication.py",
    "test_foundation.py",
    "test_h10k_tier_a_environment_extraction.py",
    "test_h10l_tier_a_error_extraction.py",
    "test_h10m_tier_a_lease_model_extraction.py",
    "test_h10n_tier_a_path_authority_extraction.py",
    "test_h10o_tier_a_materialization_extraction.py",
    "test_h10q_tier_a_legacy_plan_extraction.py",
    "test_h10r_tier_a_legacy_runner_extraction.py",
    "test_h5d_public_authorization_surface.py",
    "test_publisher_authorization_chain_v2.py",
    "test_publisher_authorization_v2.py",
    "test_publisher_keyring_state.py",
    "test_publisher_recovery_authorization_h6.py",
    "test_publisher_recovery_primary_h9.py",
    "test_publisher_recovery_receipt_finalizer_h8.py",
    "test_publisher_recovery_receipt_v3_h7.py",
    "test_publisher_recovery_signature_window_h6.py",
    "test_dc_l13_local_candidate_boundary.py",
    "test_slice10k_publisher_authorization.py",
    "test_slice10l_local_candidate_materialization.py",
    "test_physical_isolation_durable_publication_h10b.py",
    "test_proposal_reload.py",
    "test_publisher_dry_run_durable_publication_h10c.py",
    "test_review_reload.py",
    "test_runtime_staging_concurrency_h10h.py",
    "test_semantic_review_core_cleanup_h10e.py",
    "test_semantic_review_durable_publication_h10d.py",
    "test_slice10_runtime_staging.py",
    "test_slice10b_runtime_binding.py",
    "test_slice10c_output_result.py",
    "test_slice10d_runtime_closure.py",
    "test_slice10e_version_check_closure.py",
    "test_slice10g_command_receipt.py",
    "test_slice10h_semantic_review.py",
    "test_slice10i_draft_pr_readiness.py",
    "test_slice10j_publisher_dry_run.py",
    "test_slice2.py",
    "test_slice5.py",
    "test_slice6.py",
    "test_slice6_hardening.py",
    "test_slice9.py",
    "test_slice9_schemas.py",
    "test_store_proposal.py",
    "test_streaming_publication_h10g.py",
    "test_trusted_git_runtime.py",
    "test_trusted_git_runtime_recovery.py",
}
observed_modules = {
    path.name for path in (root / "devcontrol/tests").glob("test_*.py")
}
check(
    observed_modules == expected_modules,
    f"the fifty-one DC-L01–L13 test modules are present: {sorted(observed_modules)}",
)

worker_requirements = (root / "worker/requirements.txt").read_text(encoding="utf-8")
pyproject = (root / "devcontrol/pyproject.toml").read_text(encoding="utf-8")
check(
    # Reviewed 4/9/2026 for the 50.0.0 -> 50.0.1 move: src/rust/src/backend/ed25519.rs
    # and hazmat/primitives/asymmetric/ed25519.py are byte-identical between the
    # sdists; the only source change is a clippy allow in serialization.rs, and
    # the changelog's only entry is wheels rebuilt with OpenSSL 4.0.2.
    worker_requirements.count("cryptography==50.0.1") == 1,
    "the CI/runtime environment pins the reviewed Ed25519 implementation exactly once",
)
check(
    pyproject.count('"cryptography==50.0.1"') == 1,
    "the DevControl package metadata pins the same Ed25519 implementation",
)

asymmetric = importlib.import_module("kaliv_dev_control.asymmetric_authority")
semantic = importlib.import_module("kaliv_dev_control.semantic_review")
readiness = importlib.import_module("kaliv_dev_control.draft_pr_readiness")
publisher_dry_run = importlib.import_module("kaliv_dev_control.publisher_dry_run")
check(
    callable(asymmetric.Ed25519AuthorityVerifier),
    "DC-L10 exposes verification-only Ed25519 authority",
)
check(
    callable(semantic.SemanticReviewApprovalGate.ready),
    "DC-L10 exposes the offline semantic-review approval gate",
)
check(
    callable(readiness.DraftPrReadinessGate.ready),
    "DC-L11 exposes deterministic authenticated draft readiness",
)
check(
    callable(publisher_dry_run.PublisherDryRunGate.valid),
    "DC-L11 exposes authenticated publisher dry-run evidence",
)
asymmetric_source = (
    root / "devcontrol/src/kaliv_dev_control/asymmetric_authority.py"
).read_text(encoding="utf-8")
check(
    all(
        token not in asymmetric_source
        for token in (
            "Ed25519PrivateKey",
            "class Ed25519AuthorityIssuer",
            "load_private",
            ".sign(",
        )
    ),
    "the landed asymmetric runtime contains no private-key or signer boundary",
)
readiness_source = (
    root / "devcontrol/src/kaliv_dev_control/draft_pr_readiness.py"
).read_text(encoding="utf-8")
publisher_source = (
    root / "devcontrol/src/kaliv_dev_control/publisher_dry_run.py"
).read_text(encoding="utf-8")
check(
    all(
        token not in readiness_source + publisher_source
        for token in (
            "Authorization:",
            "requests.",
            "urllib",
            "subprocess",
            "create_pull_request",
            "update_pull_request",
            "merge_pull_request",
        )
    ),
    "DC-L11 contains no GitHub, HTTP, credential or process adapter",
)
publisher_authorization = importlib.import_module(
    "kaliv_dev_control.publisher_authorization"
)
publisher_chain = importlib.import_module(
    "kaliv_dev_control.publisher_authorization_chain_v2"
)
publisher_keyring = importlib.import_module(
    "kaliv_dev_control.publisher_keyring_state"
)
publisher_recovery = importlib.import_module(
    "kaliv_dev_control.publisher_recovery_authorization"
)
check(
    callable(publisher_authorization.PublisherAuthorizationVerifierV2)
    and callable(publisher_authorization.PublisherReplayLedgerV2),
    "DC-L12 exposes one-time Ed25519 authorization and replay evidence",
)
check(
    callable(publisher_recovery.PublisherReplayRecoveryAuthorizationVerifierV1),
    "DC-L12 exposes authenticated dual-role recovery verification",
)
check(
    callable(publisher_keyring.RollbackSafeEd25519AuthorityVerifier),
    "DC-L12 requires a rollback-safe external keyring-state verifier",
)
local_materialization = importlib.import_module(
    "kaliv_dev_control.local_candidate_materialization"
)
asymmetric_local_materialization = importlib.import_module(
    "kaliv_dev_control.local_candidate_materialization_h5c"
)
local_support = importlib.import_module(
    "kaliv_dev_control._local_candidate_materialization_legacy"
)
check(
    callable(local_materialization.materialize_local_candidate)
    and callable(local_materialization.verify_local_candidate_materialization)
    and callable(
        asymmetric_local_materialization.materialize_asymmetric_local_candidate
    ),
    "DC-L13 exposes verified local-only candidate materialization",
)
check(
    Path(local_support.__file__).name == "__init__.py"
    and not (
        root
        / "devcontrol/src/kaliv_dev_control/_local_candidate_materialization_legacy.py"
    ).exists()
    and not (
        root / "devcontrol/src/kaliv_dev_control/_compatibility_v1"
    ).exists(),
    "DC-L13 distributes static support without rejected compatibility files",
)
local_support_source = Path(local_support.__file__).read_text(encoding="utf-8")
local_source = (
    root / "devcontrol/src/kaliv_dev_control/local_candidate_materialization.py"
).read_text(encoding="utf-8")
local_h5c_source = (
    root / "devcontrol/src/kaliv_dev_control/local_candidate_materialization_h5c.py"
).read_text(encoding="utf-8")
check(
    all(
        token not in local_support_source
        for token in (
            "import subprocess",
            "globals().update",
            "._compatibility_v1",
            "TrustedLocalGit",
            "subprocess.run",
            "Popen(",
        )
    ),
    "DC-L13 support contains no legacy executable runner or dynamic proxy",
)
check(
    all(
        token not in local_source + local_h5c_source
        for token in (
            "requests.",
            "urllib",
            "http.client",
            "socket.",
            "paramiko",
            "Ed25519PrivateKey",
            "private_key",
            ".sign(",
            "credential.helper",
            "git push",
        )
    ),
    "DC-L13 contains no network, credential, signer or remote-push adapter",
)
support_path = (
    root
    / "devcontrol/src/kaliv_dev_control/_publisher_authorization_legacy/__init__.py"
)
support_source = support_path.read_text(encoding="utf-8")
keyring_source = (
    root / "devcontrol/src/kaliv_dev_control/publisher_keyring_state.py"
).read_text(encoding="utf-8")
check(
    not (
        root
        / "devcontrol/src/kaliv_dev_control/_publisher_authorization_legacy.py"
    ).exists()
    and not (
        root / "devcontrol/src/kaliv_dev_control/_compatibility_v1"
    ).exists(),
    "rejected dynamic legacy and v1 compatibility files are not distributed",
)
check(
    all(
        token not in support_source + keyring_source
        for token in (
            "import hmac",
            "HmacPublisherAuthorizationIssuer",
            "TrustedAuthorizationIssuerKey",
            "Ed25519PrivateKey",
            "private_key",
            ".sign(",
            "globals().update",
            "sys.modules",
            "subprocess",
            "requests.",
        )
    ),
    "DC-L12 support and external-state verifier contain no signing, secret, process or transport boundary",
)
check(
    all(
        token not in keyring_source
        for token in ("Path(", "open(", "read_text", "read_bytes")
    ),
    "rollback-safe keyring state cannot be sourced from a local file",
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
    "tests/support/windows_bounded_subprocess_contract.py",
    "tests/support/windows_restricted_contract.py",
    "tests/support/windows_tier_a_environment_contract.py",
    "tests/worker_toolhost.py",
    "tests/support/windows_catalog_tier_a_contract.py",
    "tests/support/windows_tier_a_receipt_contract.py",
)
check(
    all(path in workflow for path in native_windows_contracts),
    "CI reaches every landed product-side and DC-L09 native Windows contract",
)
check(
    "tests/support/windows_bounded_subprocess_contract.py" in workflow
    and "tests/support/windows_tier_a_receipt_contract.py" in workflow,
    "DC-L09 activates bounded trusted-Git and command-receipt Windows contracts",
)
check(
    "DevControl DC-L10 asymmetric and semantic-review boundary" in workflow,
    "CI contains an explicit offline DC-L10 authority boundary gate",
)
check(
    "DevControl DC-L11 readiness and publisher dry-run boundary" in workflow,
    "CI contains an explicit non-mutating DC-L11 intent boundary gate",
)
check(
    "DevControl DC-L12 authorization and authenticated recovery boundary" in workflow,
    "CI contains an explicit offline DC-L12 authorization/recovery boundary gate",
)

facade = importlib.import_module("kaliv_dev_control.tier_a_execution")
modern = importlib.import_module("kaliv_dev_control.tier_a_execution_v3")
receipt = importlib.import_module("kaliv_dev_control.tier_a_command_receipt")
check(
    facade.run_verified_tier_a_command is modern.run_verified_tier_a_command,
    "the final public facade routes to the sole v3 verified executor",
)
check(
    facade.run_single_verified_tier_a_command_with_receipt
    is receipt.run_single_verified_tier_a_command_with_receipt,
    "the final public facade routes to the sole Git-aware receipt orchestrator",
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