"""Adversarial production-boundary contract for ADR-DC-011 physical evidence."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control._improvement_physical_campaign_evidence_impl as implementation  # noqa: E402
import kaliv_dev_control._improvement_physical_campaign_evidence_production_boundary as boundary  # noqa: E402
import kaliv_dev_control.improvement_physical_campaign_evidence as evidence  # noqa: E402
from kaliv_dev_control.physical_isolation import WindowsPhysicalIsolationVerifier  # noqa: E402


def _canonical_keyring(*, domain: str = boundary.PHYSICAL_EVIDENCE_AUTHORITY_DOMAIN) -> bytes:
    return json.dumps(
        {
            "schema": boundary.PHYSICAL_EVIDENCE_KEYRING_SCHEMA,
            "authority_domain": domain,
            "trusted_hmac_keys": [
                {
                    "key_id": "physical-evidence-test-key",
                    "secret_hex": "11" * 32,
                }
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _expect_boundary_error(fragment: str, fn) -> None:
    try:
        fn()
    except boundary.PhysicalCampaignEvidenceProductionBoundaryError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            "expected PhysicalCampaignEvidenceProductionBoundaryError "
            f"containing {fragment!r}"
        )


def _expect_evidence_error(fragment: str, fn) -> None:
    try:
        fn()
    except evidence.PhysicalCampaignEvidenceError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalCampaignEvidenceError containing {fragment!r}"
        )


def run_contract() -> None:
    assert implementation._production_evidence_boundary_installed is True

    public = inspect.signature(evidence.collect_physical_campaign_evidence)
    assert set(public.parameters) == {
        "trusted_git",
        "admission",
        "attestation",
        "verifier",
    }
    assert public.parameters["verifier"].default is None

    private = inspect.signature(evidence._collect_physical_campaign_evidence)
    assert {
        "trusted_git",
        "repository_root",
        "operation_root",
        "admission",
        "attestation",
        "verifier",
        "now_provider",
    } <= set(private.parameters)

    # The historical verifier input remains visible only for compatibility and
    # must fail before production host state or transaction inputs are consulted.
    _expect_evidence_error(
        "caller-selected physical evidence verifier",
        lambda: evidence.collect_physical_campaign_evidence(
            trusted_git=None,
            admission=None,
            attestation=None,
            verifier=object(),
        ),
    )

    with tempfile.TemporaryDirectory(prefix="rsi-evidence-boundary-") as directory:
        root = Path(directory).resolve()
        evidence_root = root / "evidence"
        evidence_root.mkdir()
        keyring_path = root / "keyring.json"
        payload = _canonical_keyring()
        keyring_path.write_bytes(payload)
        if os.name == "posix":
            evidence_root.chmod(0o700)
            keyring_path.chmod(0o600)

        loaded = boundary._load_physical_campaign_evidence_verifier_at(
            keyring_path,
            evidence_root,
            require_host_control=False,
        )
        assert type(loaded) is WindowsPhysicalIsolationVerifier
        assert set(loaded.keyring) == {"physical-evidence-test-key"}
        assert loaded.keyring["physical-evidence-test-key"] == bytes.fromhex("11" * 32)
        assert loaded.max_age == boundary._MAX_EVIDENCE_AGE

        keyring_path.write_bytes(_canonical_keyring(domain="another-domain"))
        _expect_boundary_error(
            "another authority domain",
            lambda: boundary._load_physical_campaign_evidence_verifier_at(
                keyring_path,
                evidence_root,
                require_host_control=False,
            ),
        )

        keyring_path.write_bytes(payload + b"\n")
        _expect_boundary_error(
            "not canonical",
            lambda: boundary._load_physical_campaign_evidence_verifier_at(
                keyring_path,
                evidence_root,
                require_host_control=False,
            ),
        )

        malformed = json.loads(payload)
        malformed["trusted_hmac_keys"][0]["secret_hex"] = "aa"
        keyring_path.write_bytes(
            json.dumps(
                malformed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        _expect_boundary_error(
            "secret is invalid",
            lambda: boundary._load_physical_campaign_evidence_verifier_at(
                keyring_path,
                evidence_root,
                require_host_control=False,
            ),
        )

    # Production keeps the already-attested host runtime and creates only an
    # empty cleanup sentinel.  Executable/runtime bytes are never copied into a
    # service-user staging tree after attestation.
    original_require = boundary._require_host_controlled_physical_git_runtime
    dummy_runtime = object()
    boundary._require_host_controlled_physical_git_runtime = lambda value: value
    try:
        with tempfile.TemporaryDirectory(prefix="rsi-evidence-operation-") as directory:
            operation = Path(directory).resolve()
            token = boundary._PRODUCTION_EVIDENCE_CONTEXT.set(True)
            try:
                observed_runtime, cleanup_root = implementation._snapshot_trusted_git_runtime(
                    dummy_runtime,
                    operation_root=operation,
                )
            finally:
                boundary._PRODUCTION_EVIDENCE_CONTEXT.reset(token)
            assert observed_runtime is dummy_runtime
            assert cleanup_root.parent == operation
            assert cleanup_root.is_dir()
            assert list(cleanup_root.iterdir()) == []
            cleanup_root.rmdir()
    finally:
        boundary._require_host_controlled_physical_git_runtime = original_require

    # A missing/untrusted production runtime fails closed before the private
    # injectable collector can fall back to same-user runtime staging.
    original_verifier = boundary._canonical_physical_campaign_evidence_verifier
    original_require = boundary._require_host_controlled_physical_git_runtime
    boundary._canonical_physical_campaign_evidence_verifier = lambda: object()

    def reject_runtime(_value):
        raise boundary.PhysicalHostRuntimeError("synthetic mutable runtime")

    boundary._require_host_controlled_physical_git_runtime = reject_runtime
    try:
        _expect_evidence_error(
            "host-controlled physical campaign evidence state is unavailable",
            lambda: evidence.collect_physical_campaign_evidence(
                trusted_git=None,
                admission=None,
                attestation=None,
            ),
        )
    finally:
        boundary._canonical_physical_campaign_evidence_verifier = original_verifier
        boundary._require_host_controlled_physical_git_runtime = original_require

    # Fixed production locations are caller-independent and live under the same
    # host-admin custody roots as the prior reservation/admission authority.
    evidence_path = boundary._canonical_physical_campaign_evidence_root_path()
    keyring_path = boundary._canonical_physical_campaign_evidence_keyring_path()
    if os.name == "nt":
        assert str(evidence_path).lower().startswith(
            r"c:\program files\modelrig\devcontrol\evidence"
        )
        assert str(keyring_path).lower().startswith(
            r"c:\program files\modelrig\devcontrol\authority"
        )
    elif os.name == "posix":
        assert evidence_path == Path(
            "/var/lib/modelrig/devcontrol/rsi-physical-campaign-evidence-v1"
        )
        assert keyring_path == Path(
            "/etc/modelrig/devcontrol/authority/rsi-physical-campaign-evidence-hmac-keyring-v1.json"
        )

    # Even successful evidence can never collapse the still-missing authority
    # gates.  The snapshot type itself rejects any over-authorizing mutation.
    snapshot = evidence.PhysicalCampaignEvidenceSnapshot(
        admission_sha256="a" * 64,
        campaign_id="campaign-001",
        reservation_sha256="b" * 64,
        request_sha256="c" * 64,
        qualification_packet_sha256="d" * 64,
        snapshot_receipt_sha256="e" * 64,
        task_id="RSI_TASK_001",
        task_sha256="f" * 64,
        repository="Ternedal/ModelRig",
        base_sha="1" * 40,
        requested_main_sha="2" * 40,
        runner_relative_path="tools/run-physical.ps1",
        runner_sha256="3" * 64,
        runner_bytes=4096,
        isolation_attestation_sha256="4" * 64,
        signed_report_sha256="5" * 64,
        physical_report_sha256="6" * 64,
        report_id="report-001",
        rig_id="windows-rig-001",
        rig_fingerprint_sha256="7" * 64,
        toolhost_sha256="8" * 64,
        workspace_root_sha256="9" * 64,
        collector_actor_id="physical.operator",
        approver_actor_id="physical.approver",
        report_started_at_utc="2026-09-13T12:00:00Z",
        report_completed_at_utc="2026-09-13T12:10:00Z",
        post_main_observation_sha256="a" * 64,
        post_main_observed_sha="2" * 40,
        post_main_observed_at_utc="2026-09-13T12:11:00Z",
        repository_root_path_sha256="b" * 64,
        git_runtime_manifest_sha256="c" * 64,
        git_executable_sha256="d" * 64,
    )
    assert snapshot.physical_report_verified is True
    assert snapshot.all_required_probes_passed is True
    assert snapshot.runner_execution_binding_proven is False
    assert snapshot.continuous_main_freeze_proven is False
    assert snapshot.physical_campaign_completed is False
    assert snapshot.dc_l15_complete is False
    assert snapshot.pilot_go_authorized is False
    assert snapshot.activation_authorized is False
    assert snapshot.remote_publication_authorized is False
    assert snapshot.authority == "verified-physical-evidence-only"
    assert snapshot.missing_completion_gates == (
        "exact_runner_execution_binding",
        "continuous_main_freeze_confirmation",
        "dc_l14_independent_human_verdict",
        "human_pilot_go_decision",
    )


if __name__ == "__main__":
    run_contract()
