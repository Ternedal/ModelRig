"""Adversarial production-boundary contract for ADR-DC-012 execution binding."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
import kaliv_dev_control._improvement_physical_campaign_execution_binding_impl as implementation  # noqa: E402
import kaliv_dev_control._improvement_physical_campaign_execution_binding_production_boundary as boundary  # noqa: E402
import kaliv_dev_control.improvement_physical_campaign_execution_binding as execution  # noqa: E402
from kaliv_dev_control.improvement_physical_campaign_evidence import PhysicalCampaignEvidenceSnapshot  # noqa: E402


def _trusted_key(
    *,
    actor: str = "physical.operator",
    issuer_system_id: str = implementation.EXECUTION_BINDING_ISSUER_SYSTEM_ID,
):
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    key = TrustedEd25519AuthorityKey(
        key_id="rsi-execution-binding-test-key",
        issuer_actor_id=actor,
        issuer_system_id=issuer_system_id,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-13T00:00:00Z",
        valid_until_utc="2026-09-14T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=asymmetric_authority_key_custody_policy_sha256(),
    )
    return private, key


def _canonical_keyring(
    key: TrustedEd25519AuthorityKey,
    *,
    domain: str = boundary.EXECUTION_BINDING_AUTHORITY_DOMAIN,
) -> bytes:
    return json.dumps(
        {
            "schema": boundary.EXECUTION_BINDING_KEYRING_SCHEMA,
            "authority_domain": domain,
            "minimum_keyring_epoch": 1,
            "trusted_keys": [key.to_dict()],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sign(
    binding: execution.PhysicalCampaignExecutionBinding,
    private: Ed25519PrivateKey,
    key: TrustedEd25519AuthorityKey,
) -> DetachedEd25519AuthoritySignature:
    payload = binding.canonical_json().encode("utf-8")
    message = authority_signing_message(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=key.custody_policy_sha256,
        payload=payload,
    )
    return DetachedEd25519AuthoritySignature(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=key.custody_policy_sha256,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private.sign(message).hex(),
        signed_at_utc=binding.binding_created_at_utc,
    )


def _evidence() -> PhysicalCampaignEvidenceSnapshot:
    return PhysicalCampaignEvidenceSnapshot(
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


def _binding(
    evidence: PhysicalCampaignEvidenceSnapshot,
    *,
    created_at: str = "2026-09-13T12:12:00Z",
) -> execution.PhysicalCampaignExecutionBinding:
    return execution.build_physical_campaign_execution_binding(
        evidence=evidence,
        binding_id="execution-binding-001",
        operator_actor_id="physical.operator",
        execution_started_at_utc="2026-09-13T12:01:00Z",
        execution_completed_at_utc="2026-09-13T12:09:00Z",
        binding_created_at_utc=created_at,
    )


def _expect_execution_error(fragment: str, fn) -> None:
    try:
        fn()
    except execution.PhysicalCampaignExecutionBindingError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalCampaignExecutionBindingError containing {fragment!r}"
        )


def _expect_boundary_error(fragment: str, fn) -> None:
    try:
        fn()
    except boundary.PhysicalCampaignExecutionBindingProductionBoundaryError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            "expected PhysicalCampaignExecutionBindingProductionBoundaryError "
            f"containing {fragment!r}"
        )


def _schema_properties(name: str) -> set[str]:
    value = json.loads((ROOT / "devcontrol" / "schemas" / name).read_text(encoding="utf-8"))
    return set(value["properties"])


def run_contract() -> None:
    assert implementation._production_execution_binding_boundary_installed is True

    public = inspect.signature(execution.verify_physical_campaign_execution_binding)
    assert set(public.parameters) == {"evidence", "binding", "signature", "verifier"}
    assert public.parameters["verifier"].default is None
    private = inspect.signature(execution._verify_physical_campaign_execution_binding)
    assert {"evidence", "binding", "signature", "verifier", "now_provider"} <= set(private.parameters)

    _expect_execution_error(
        "caller-selected execution-binding verifier",
        lambda: execution.verify_physical_campaign_execution_binding(
            evidence=None,
            binding=None,
            signature=None,
            verifier=object(),
        ),
    )

    private_key, key = _trusted_key()
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)

    with tempfile.TemporaryDirectory(prefix="rsi-execution-binding-keyring-") as directory:
        root = Path(directory).resolve()
        path = root / "keyring.json"
        payload = _canonical_keyring(key)
        path.write_bytes(payload)
        if os.name == "posix":
            path.chmod(0o600)

        loaded = boundary._load_physical_campaign_execution_binding_verifier_at(
            path,
            issuer_system_id=implementation.EXECUTION_BINDING_ISSUER_SYSTEM_ID,
            require_host_control=False,
        )
        assert type(loaded) is Ed25519AuthorityVerifier
        assert set(loaded._trusted_keys) == {key.key_id}

        path.write_bytes(_canonical_keyring(key, domain="another-domain"))
        _expect_boundary_error(
            "another authority domain",
            lambda: boundary._load_physical_campaign_execution_binding_verifier_at(
                path,
                issuer_system_id=implementation.EXECUTION_BINDING_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )

        _foreign_private, foreign_key = _trusted_key(
            issuer_system_id="some-other-execution-authority"
        )
        path.write_bytes(_canonical_keyring(foreign_key))
        _expect_boundary_error(
            "another issuer system",
            lambda: boundary._load_physical_campaign_execution_binding_verifier_at(
                path,
                issuer_system_id=implementation.EXECUTION_BINDING_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )

        path.write_bytes(payload + b"\n")
        _expect_boundary_error(
            "not canonical",
            lambda: boundary._load_physical_campaign_execution_binding_verifier_at(
                path,
                issuer_system_id=implementation.EXECUTION_BINDING_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )

    evidence = _evidence()
    binding = _binding(evidence)
    signature = _sign(binding, private_key, key)
    proof = execution._verify_physical_campaign_execution_binding(
        evidence=evidence,
        binding=binding,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-13T12:13:00Z",
    )
    assert proof.evidence_snapshot_sha256 == evidence.sha256
    assert proof.binding_sha256 == binding.sha256
    assert proof.signature_sha256 == signature.sha256
    assert proof.runner_sha256 == evidence.runner_sha256
    assert proof.runner_bytes == evidence.runner_bytes
    assert proof.report_id == evidence.report_id
    assert proof.runner_execution_binding_proven is True
    assert proof.continuous_main_freeze_proven is False
    assert proof.physical_campaign_completed is False
    assert proof.dc_l15_complete is False
    assert proof.pilot_go_authorized is False
    assert proof.activation_authorized is False
    assert proof.remote_publication_authorized is False
    assert proof.remaining_completion_gates == (
        "continuous_main_freeze_confirmation",
        "dc_l14_independent_human_verdict",
        "human_pilot_go_decision",
    )
    assert proof.authority == "verified-human-exact-runner-execution-binding-only"

    changed = binding.to_dict()
    changed["physical_report_sha256"] = "0" * 64
    changed_binding = execution.PhysicalCampaignExecutionBinding.from_mapping(changed)
    changed_signature = _sign(changed_binding, private_key, key)
    _expect_execution_error(
        "not exactly bound",
        lambda: execution._verify_physical_campaign_execution_binding(
            evidence=evidence,
            binding=changed_binding,
            signature=changed_signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-13T12:13:00Z",
        ),
    )

    other_private, other_key = _trusted_key(actor="another.operator")
    other_verifier = Ed25519AuthorityVerifier({other_key.key_id: other_key}, minimum_keyring_epoch=1)
    other_signature = _sign(binding, other_private, other_key)
    _expect_execution_error(
        "signer must be the physical operator",
        lambda: execution._verify_physical_campaign_execution_binding(
            evidence=evidence,
            binding=binding,
            signature=other_signature,
            verifier=other_verifier,
            now_provider=lambda: "2026-09-13T12:13:00Z",
        ),
    )

    foreign_private, foreign_key = _trusted_key(
        issuer_system_id="some-other-execution-authority"
    )
    foreign_verifier = Ed25519AuthorityVerifier({foreign_key.key_id: foreign_key}, minimum_keyring_epoch=1)
    foreign_signature = _sign(binding, foreign_private, foreign_key)
    _expect_execution_error(
        "another issuer system",
        lambda: execution._verify_physical_campaign_execution_binding(
            evidence=evidence,
            binding=binding,
            signature=foreign_signature,
            verifier=foreign_verifier,
            now_provider=lambda: "2026-09-13T12:13:00Z",
        ),
    )

    _expect_execution_error(
        "signed too late",
        lambda: _binding(evidence, created_at="2026-09-13T12:42:00Z"),
    )

    escalated = binding.to_dict()
    escalated["continuous_main_freeze_confirmed"] = True
    _expect_execution_error(
        "authority boundary",
        lambda: execution.PhysicalCampaignExecutionBinding.from_mapping(escalated),
    )

    assert _schema_properties("rsi-physical-campaign-execution-binding-v1.schema.json") == set(binding.to_dict())
    assert _schema_properties("rsi-physical-campaign-execution-proof-v1.schema.json") == set(proof.to_dict())

    path = boundary._canonical_physical_campaign_execution_binding_keyring_path()
    if os.name == "nt":
        assert str(path).lower().startswith(r"c:\program files\modelrig\devcontrol\authority")
    elif os.name == "posix":
        assert path == Path(
            "/etc/modelrig/devcontrol/authority/rsi-physical-campaign-execution-binding-keyring-v1.json"
        )


if __name__ == "__main__":
    run_contract()
