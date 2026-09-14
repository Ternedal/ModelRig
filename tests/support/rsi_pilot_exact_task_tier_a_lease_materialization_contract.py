"""Adversarial contract for ADR-DC-036 non-executing Tier-A lease materialization."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control import catalog  # noqa: E402
from kaliv_dev_control._tier_a_lease import TierAExecutionLease  # noqa: E402
from kaliv_dev_control._tier_a_materialization import LeasedCatalogMaterializer  # noqa: E402
from kaliv_dev_control.catalog import (  # noqa: E402
    IsolationAttestation,
    IsolationBoundary,
    NetworkMode,
    ToolBinding,
    Toolchain,
)
from kaliv_dev_control.physical_isolation import (  # noqa: E402
    HmacIsolationReportSigner,
    PhysicalProbeResult,
    ProbeName,
    WindowsIsolationPhysicalReport,
    WindowsPhysicalIsolationVerifier,
    write_signed_report,
)
from kaliv_dev_control.runtime_closure_builder import (  # noqa: E402
    VERSION_CHECK_COMMAND_ID,
    VERSION_CHECK_TOOL_ID,
    modelrig_version_check_closure_catalog,
)
from kaliv_dev_control.tier_a_authority import (  # noqa: E402
    tier_a_toolhost_sha256,
    workspace_root_authority_sha256,
)
import kaliv_dev_control.improvement_pilot_exact_task_development_task_binding as binding  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_admission as admission  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_plan_requirements as plan_req  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_tier_a_lease_materialization as tier  # noqa: E402
import kaliv_dev_control._improvement_pilot_exact_task_tier_a_lease_materialization_production_boundary as production  # noqa: E402
from rsi_pilot_exact_task_development_task_binding_contract import (  # noqa: E402
    _registry,
    _task,
)
from rsi_pilot_exact_task_execution_plan_requirements_contract import (  # noqa: E402
    _live_receipt,
)

PROFILE_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-tier-a-version-check-profile-v1.schema.json"
)
EVIDENCE_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-tier-a-lease-materialization-v1.schema.json"
)
KEY_ID = "adr-dc-036-physical-key"
SECRET = b"adr-dc-036-physical-isolation-secret-01"
STARTED = "2026-09-14T08:30:00Z"
COMPLETED = "2026-09-14T08:40:00Z"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, OSError):
        return
    raise AssertionError("ADR-DC-036 unexpectedly accepted invalid authority")


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _profile_payload(
    *,
    executable: Path,
    executable_sha256: str,
    workspace: Path,
    attestation: IsolationAttestation,
    process_memory_bytes: int = tier.PILOT_EXACT_TASK_TIER_A_PROCESS_MEMORY_BYTES,
    active_process_limit: int = tier.PILOT_EXACT_TASK_TIER_A_ACTIVE_PROCESS_LIMIT,
) -> bytes:
    return _canonical(
        {
            "schema": tier.PILOT_EXACT_TASK_TIER_A_PROFILE_SCHEMA,
            "profile_id": tier.PILOT_EXACT_TASK_TIER_A_PROFILE_ID,
            "tool_binding": {
                "tool_id": VERSION_CHECK_TOOL_ID,
                "executable": str(executable),
                "executable_sha256": executable_sha256,
            },
            "workspace_root": str(workspace),
            "control_plane_root": str(ROOT.resolve()),
            "isolation_attestation": attestation.to_dict(),
            "physical_verifier": {
                "max_age_seconds": 366 * 24 * 60 * 60,
                "max_file_bytes": 2_000_000,
                "trusted_keys": [
                    {"key_id": KEY_ID, "secret_hex": SECRET.hex()}
                ],
            },
            "process_memory_bytes": process_memory_bytes,
            "active_process_limit": active_process_limit,
        }
    )


def _authority_fixture(binding_proof):
    temp = tempfile.TemporaryDirectory(prefix="rsi-exact-task-tier-a-lease-")
    root = Path(temp.name).resolve()
    workspace = root / "workspace"
    evidence_root = root / "evidence"
    runtime_root = root / "runtime"
    workspace.mkdir()
    evidence_root.mkdir()
    runtime_root.mkdir()

    executable = (runtime_root / "modelrig-version-check.exe").resolve()
    executable.write_bytes(b"ADR-DC-036 reviewed version check fixture\n")
    executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
    reviewed_catalog = modelrig_version_check_closure_catalog()
    assert reviewed_catalog.sha256 == tier.PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256
    toolchain = Toolchain(
        (
            ToolBinding(
                VERSION_CHECK_TOOL_ID,
                str(executable),
                executable_sha256,
            ),
        )
    )
    task = binding_proof.development_task
    task_sha256 = hashlib.sha256(
        task.canonical_json().encode("utf-8")
    ).hexdigest()
    probes = tuple(
        PhysicalProbeResult(
            name=name,
            passed=True,
            receipt_sha256=hashlib.sha256(
                ("adr-dc-036:" + name.value).encode("utf-8")
            ).hexdigest(),
            detail=f"ADR-DC-036 fixture for {name.value}",
            observed_at=COMPLETED,
        )
        for name in ProbeName
    )
    report = WindowsIsolationPhysicalReport(
        report_id="adr-dc-036-physical-report",
        task_id=task.task_id,
        task_sha256=task_sha256,
        repository=task.repository,
        base_sha=task.base_sha,
        catalog_sha256=reviewed_catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        rig_id="adr-dc-036-test-rig",
        rig_fingerprint_sha256="1" * 64,
        candidate_version="adr-dc-036-contract",
        windows_build="ADR-DC-036 deterministic contract",
        toolhost_sha256=tier_a_toolhost_sha256(ROOT.resolve()),
        workspace_root_sha256=workspace_root_authority_sha256(workspace),
        collected_by="adr-dc-036-collector",
        approved_by="adr-dc-036-approver",
        started_at=STARTED,
        completed_at=COMPLETED,
        boot_marker_before_sha256="2" * 64,
        boot_marker_after_sha256="3" * 64,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        probes=probes,
    )
    signed = HmacIsolationReportSigner(KEY_ID, SECRET).sign(report)
    signed_hash = write_signed_report(
        (evidence_root / "signed-report.json").resolve(),
        signed,
    )
    attestation = IsolationAttestation(
        task_id=task.task_id,
        task_sha256=task_sha256,
        repository=task.repository,
        base_sha=task.base_sha,
        catalog_sha256=reviewed_catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        boundary=IsolationBoundary.OS_ISOLATED,
        network_mode=NetworkMode.DENY,
        evidence_sha256=(signed_hash,),
    )
    profile_payload = _profile_payload(
        executable=executable,
        executable_sha256=executable_sha256,
        workspace=workspace,
        attestation=attestation,
    )
    profile = tier._parse_profile_payload(profile_payload)
    verifier = WindowsPhysicalIsolationVerifier(
        evidence_root,
        {KEY_ID: SECRET},
        max_age=timedelta(days=366),
        now=lambda: datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc),
        max_file_bytes=2_000_000,
    )
    leased = LeasedCatalogMaterializer(
        reviewed_catalog,
        verifier,
    ).materialize(task, toolchain, attestation)
    return (
        temp,
        workspace,
        evidence_root,
        executable,
        executable_sha256,
        profile_payload,
        profile,
        leased,
    )


def _retarget_catalog(mapping: dict, catalog_sha256: str) -> dict:
    changed = json.loads(json.dumps(mapping))
    changed["catalog_sha256"] = catalog_sha256
    changed["isolation_attestation"]["catalog_sha256"] = catalog_sha256
    changed["execution_lease"]["catalog_sha256"] = catalog_sha256
    attestation = IsolationAttestation.from_mapping(changed["isolation_attestation"])
    lease = TierAExecutionLease.from_mapping(changed["execution_lease"])
    changed["isolation_attestation_sha256"] = hashlib.sha256(
        attestation.canonical_json().encode("utf-8")
    ).hexdigest()
    changed["execution_lease_sha256"] = lease.sha256
    return changed


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    source_temp, ledger_temp, receipt = _live_receipt()
    fixture_temp = None
    try:
        requirements = plan_req.build_pilot_exact_task_execution_plan_requirements(
            receipt
        )
        task = _task(requirements)
        binding_proof = binding._bind_verified_development_task(
            plan_requirements=requirements,
            admission_receipt=receipt,
            registry_payload=_registry(requirements, task),
        )
        (
            fixture_temp,
            workspace,
            evidence_root,
            executable,
            executable_sha256,
            profile_payload,
            profile,
            leased,
        ) = _authority_fixture(binding_proof)

        # The upstream pilot fixture intentionally carries a synthetic workspace
        # path hash. Patch only that deterministic seam while exercising the real
        # Tier-A domain-separated workspace authority and toolhost bindings.
        original_path_sha = tier._implementation._path_sha256
        try:
            tier._implementation._path_sha256 = (
                lambda _path: binding_proof.workspace_root_path_sha256
            )
            inner_capability = tier._materialize_verified_tier_a_lease(
                development_task_binding=binding_proof,
                admission_receipt=receipt,
                profile=profile,
                leased_registry=leased,
            )
        finally:
            tier._implementation._path_sha256 = original_path_sha

        capability = tier.PilotExactTaskTierALeaseCapability._from_internal(
            inner_capability
        )
        proof = capability.evidence
        assert capability.capability_authenticated is True
        assert not hasattr(capability, "leased_registry")
        assert "_extract_live_leased_registry" not in tier.__all__
        assert tier._extract_live_leased_registry(capability) is leased
        assert proof.schema == tier.PILOT_EXACT_TASK_TIER_A_LEASE_SCHEMA
        assert proof.authority == tier.PILOT_EXACT_TASK_TIER_A_LEASE_AUTHORITY
        assert proof.development_task_binding_sha256 == binding_proof.sha256
        assert proof.admission_receipt_sha256 == receipt.sha256
        assert proof.execution_nonce_sha256 == receipt.execution_nonce_sha256
        assert proof.catalog_sha256 == tier.PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256
        assert proof.toolchain_sha256 == leased.toolchain.sha256
        assert proof.isolation_attestation == leased.attestation
        assert proof.execution_lease == leased.lease
        assert proof.fixed_command_id == VERSION_CHECK_COMMAND_ID
        assert proof.workspace_root_path_sha256 == binding_proof.workspace_root_path_sha256
        assert proof.workspace_root_authority_sha256 == workspace_root_authority_sha256(
            workspace
        )
        assert proof.workspace_root_authority_sha256 != proof.workspace_root_path_sha256
        assert proof.toolhost_sha256 == tier_a_toolhost_sha256(ROOT.resolve())
        assert proof.process_memory_bytes == 128 * 1024 * 1024
        assert proof.active_process_limit == 1
        assert capability.workspace_root == workspace
        assert capability.control_plane_root == ROOT.resolve()
        assert capability.process_memory_bytes == 128 * 1024 * 1024
        assert capability.active_process_limit == 1
        assert proof.host_profile_verified is True
        assert proof.reviewed_catalog_verified is True
        assert proof.exact_toolchain_materialized is True
        assert proof.isolation_attestation_verified is True
        assert proof.execution_lease_materialized is True
        assert proof.workspace_authority_verified is True
        assert proof.toolhost_authority_verified is True

        forced_false = (
            "runtime_closure_materialized",
            "execution_plan_materialized",
            "execution_consumed",
            "task_execution_started",
            "task_execution_completed",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        for field in forced_false:
            assert getattr(proof, field) is False
            _reject(
                lambda field=field: tier.PilotExactTaskTierALeaseMaterialization.from_mapping(
                    {**proof.to_dict(), field: True}
                )
            )

        # Durable evidence remains inert and round-trips, but cannot recreate a
        # live leased-registry capability.
        replayed = tier.PilotExactTaskTierALeaseMaterialization.from_mapping(
            proof.to_dict()
        )
        assert replayed == proof
        assert replayed.sha256 == proof.sha256
        assert not hasattr(replayed, "_inner")
        assert not hasattr(replayed, "leased_registry")

        # The private structural evidence parser alone can accept a self-consistent
        # alternate catalog identity. The public durable boundary must reject it,
        # proving the reviewed catalog hash is an actual replay invariant rather
        # than merely a true boolean flag.
        alternate_catalog = _retarget_catalog(proof.to_dict(), "f" * 64)
        internal_replay = tier._implementation.PilotExactTaskTierALeaseMaterialization.from_mapping(
            alternate_catalog
        )
        assert internal_replay.catalog_sha256 == "f" * 64
        _reject(
            lambda: tier.PilotExactTaskTierALeaseMaterialization.from_mapping(
                alternate_catalog
            )
        )
        _reject(
            lambda: tier.PilotExactTaskTierALeaseMaterialization.from_mapping(
                {
                    **proof.to_dict(),
                    "process_memory_bytes": 256 * 1024 * 1024,
                }
            )
        )
        _reject(
            lambda: tier.PilotExactTaskTierALeaseMaterialization.from_mapping(
                {**proof.to_dict(), "active_process_limit": 2}
            )
        )

        # Without the deterministic fixture seam, the real path hash does not
        # match the synthetic signed pilot hash and must fail closed.
        _reject(
            lambda: tier._materialize_verified_tier_a_lease(
                development_task_binding=binding_proof,
                admission_receipt=receipt,
                profile=profile,
                leased_registry=leased,
            )
        )

        # A reloaded ADR-DC-033 receipt cannot regain live materialization authority.
        reloaded_receipt = admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded_receipt.transaction_authenticated is False
        _reject(
            lambda: tier._materialize_verified_tier_a_lease(
                development_task_binding=binding_proof,
                admission_receipt=reloaded_receipt,
                profile=profile,
                leased_registry=leased,
            )
        )

        # Production exposes no caller-selected profile, verifier, evidence root
        # or catalog. It validates live provenance before any host-profile read.
        originals = (
            production._require_windows_host,
            production._require_elevated_operator,
            production._read_keyring_bytes,
            production._canonical_profile_path,
            production._require_host_controlled_evidence_root,
            tier._implementation._path_sha256,
        )
        calls = []
        current_payload = [profile_payload]
        try:
            production._require_windows_host = lambda: None
            production._require_elevated_operator = lambda: None
            production._canonical_profile_path = lambda: Path("/fixed/adr-dc-036-profile.json")
            production._require_host_controlled_evidence_root = lambda: evidence_root

            def fake_read(path, *, require_host_control):
                calls.append((path, require_host_control))
                return current_payload[0]

            production._read_keyring_bytes = fake_read
            tier._implementation._path_sha256 = (
                lambda _path: binding_proof.workspace_root_path_sha256
            )
            production_capability = tier.materialize_pilot_exact_task_tier_a_lease(
                development_task_binding=binding_proof,
                admission_receipt=receipt,
            )
            assert production_capability.capability_authenticated is True
            assert calls == [(Path("/fixed/adr-dc-036-profile.json"), True)]
            _reject(
                lambda: tier.materialize_pilot_exact_task_tier_a_lease(
                    development_task_binding=binding_proof,
                    admission_receipt=receipt,
                    profile_payload=profile_payload,
                )
            )

            calls.clear()
            _reject(
                lambda: tier.materialize_pilot_exact_task_tier_a_lease(
                    development_task_binding=binding_proof,
                    admission_receipt=reloaded_receipt,
                )
            )
            assert calls == []

            current_payload[0] = _profile_payload(
                executable=executable,
                executable_sha256=executable_sha256,
                workspace=workspace,
                attestation=leased.attestation,
                process_memory_bytes=256 * 1024 * 1024,
            )
            _reject(
                lambda: tier.materialize_pilot_exact_task_tier_a_lease(
                    development_task_binding=binding_proof,
                    admission_receipt=receipt,
                )
            )
        finally:
            (
                production._require_windows_host,
                production._require_elevated_operator,
                production._read_keyring_bytes,
                production._canonical_profile_path,
                production._require_host_controlled_evidence_root,
                tier._implementation._path_sha256,
            ) = originals

        profile_schema = json.loads(PROFILE_SCHEMA.read_text(encoding="utf-8"))
        profile_props = profile_schema["properties"]
        assert profile_schema["additionalProperties"] is False
        assert profile_props["schema"]["const"] == tier.PILOT_EXACT_TASK_TIER_A_PROFILE_SCHEMA
        assert profile_props["profile_id"]["const"] == tier.PILOT_EXACT_TASK_TIER_A_PROFILE_ID
        assert profile_props["tool_binding"]["properties"]["tool_id"]["const"] == (
            VERSION_CHECK_TOOL_ID
        )
        assert profile_props["process_memory_bytes"]["const"] == 128 * 1024 * 1024
        assert profile_props["active_process_limit"]["const"] == 1
        assert (
            profile_props["isolation_attestation"]["allOf"][1]["properties"]
            ["catalog_sha256"]["const"]
            == tier.PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256
        )

        evidence_schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
        evidence_props = evidence_schema["properties"]
        assert evidence_schema["additionalProperties"] is False
        assert set(evidence_props) == set(proof.to_dict())
        assert evidence_props["schema"]["const"] == tier.PILOT_EXACT_TASK_TIER_A_LEASE_SCHEMA
        assert evidence_props["authority"]["const"] == tier.PILOT_EXACT_TASK_TIER_A_LEASE_AUTHORITY
        assert evidence_props["catalog_sha256"]["const"] == (
            tier.PILOT_EXACT_TASK_TIER_A_REVIEWED_CATALOG_SHA256
        )
        assert evidence_props["fixed_command_id"]["const"] == VERSION_CHECK_COMMAND_ID
        assert evidence_props["process_memory_bytes"]["const"] == 128 * 1024 * 1024
        assert evidence_props["active_process_limit"]["const"] == 1
        for field in forced_false:
            assert evidence_props[field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_exact_task_tier_a_lease_materialization" not in root_source
        public_source = inspect.getsource(tier).lower()
        impl_source = inspect.getsource(tier._implementation).lower()
        production_source = inspect.getsource(production).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
            "run_verified_tier_a_command",
            "run_single_verified_tier_a_command_with_receipt",
        ):
            assert forbidden not in public_source, forbidden
            assert forbidden not in impl_source, forbidden
            assert forbidden not in production_source, forbidden
    finally:
        if fixture_temp is not None:
            fixture_temp.cleanup()
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
