"""Adversarial production-boundary contract for ADR-DC-014 independent verdict."""
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
import kaliv_dev_control._improvement_physical_campaign_independent_verdict_impl as implementation  # noqa: E402
import kaliv_dev_control._improvement_physical_campaign_independent_verdict_production_boundary as boundary  # noqa: E402
import kaliv_dev_control.improvement_physical_campaign_independent_verdict as independent  # noqa: E402
from kaliv_dev_control.improvement_physical_campaign_execution_binding import (  # noqa: E402
    EXECUTION_BINDING_ISSUER_SYSTEM_ID,
    PhysicalCampaignExecutionProof,
)
from kaliv_dev_control.improvement_physical_campaign_main_freeze import PhysicalCampaignMainFreezeProof  # noqa: E402


def _trusted_key(*, actor="physical.reviewer", issuer_system_id=implementation.INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID):
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    key = TrustedEd25519AuthorityKey(
        key_id="rsi-independent-verdict-test-key",
        issuer_actor_id=actor,
        issuer_system_id=issuer_system_id,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-13T00:00:00Z",
        valid_until_utc="2026-09-15T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=asymmetric_authority_key_custody_policy_sha256(),
    )
    return private, key


def _canonical_keyring(key, *, domain=boundary.INDEPENDENT_VERDICT_AUTHORITY_DOMAIN):
    return json.dumps(
        {
            "schema": boundary.INDEPENDENT_VERDICT_KEYRING_SCHEMA,
            "authority_domain": domain,
            "minimum_keyring_epoch": 1,
            "trusted_keys": [key.to_dict()],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _execution_proof():
    return PhysicalCampaignExecutionProof(
        binding_sha256="1" * 64,
        evidence_snapshot_sha256="2" * 64,
        signature_sha256="3" * 64,
        key_id="rsi-execution-binding-test-key",
        issuer_actor_id="physical.operator",
        issuer_system_id=EXECUTION_BINDING_ISSUER_SYSTEM_ID,
        binding_id="execution-binding-001",
        admission_sha256="4" * 64,
        campaign_id="campaign-001",
        task_id="RSI_TASK_001",
        task_sha256="5" * 64,
        repository="Ternedal/ModelRig",
        base_sha="1" * 40,
        requested_main_sha="2" * 40,
        runner_relative_path="tools/run-physical.ps1",
        runner_sha256="6" * 64,
        runner_bytes=4096,
        signed_report_sha256="7" * 64,
        physical_report_sha256="8" * 64,
        report_id="report-001",
        operator_actor_id="physical.operator",
        approver_actor_id="physical.approver",
        execution_started_at_utc="2026-09-13T12:01:00Z",
        execution_completed_at_utc="2026-09-13T12:09:00Z",
        binding_created_at_utc="2026-09-13T12:12:00Z",
        verified_at_utc="2026-09-13T12:13:00Z",
    )


def _freeze_proof(execution):
    return PhysicalCampaignMainFreezeProof(
        admission_sha256=execution.admission_sha256,
        execution_proof_sha256=execution.sha256,
        evidence_snapshot_sha256=execution.evidence_snapshot_sha256,
        campaign_id=execution.campaign_id,
        task_id=execution.task_id,
        task_sha256=execution.task_sha256,
        repository=execution.repository,
        base_sha=execution.base_sha,
        requested_main_sha=execution.requested_main_sha,
        freeze_started_at_utc="2026-09-13T12:00:10Z",
        freeze_finalized_at_utc="2026-09-13T12:14:00Z",
        start_observation_sha256="9" * 64,
        end_observation_sha256="a" * 64,
        start_observed_main_sha=execution.requested_main_sha,
        end_observed_main_sha=execution.requested_main_sha,
        repository_root_path_sha256="b" * 64,
        git_runtime_manifest_sha256="c" * 64,
        git_executable_sha256="d" * 64,
        watch_backend="inotify",
        watch_scope=(".git/config", ".git/packed-refs", ".git/refs/heads/main"),
    )


def _verdict(freeze, execution, *, reviewer="physical.reviewer", decision="approve", findings=(), reviewed_at="2026-09-13T12:20:00Z"):
    return independent.build_physical_campaign_independent_human_verdict(
        main_freeze_proof=freeze,
        execution_proof=execution,
        verdict_id="independent-verdict-001",
        reviewer_actor_id=reviewer,
        decision=decision,
        findings=findings,
        reviewed_at_utc=reviewed_at,
    )


def _sign(verdict, private, key):
    payload = verdict.canonical_json().encode("utf-8")
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
        signed_at_utc=verdict.reviewed_at_utc,
    )


def _expect_verdict_error(fragment, fn):
    try:
        fn()
    except independent.PhysicalCampaignIndependentHumanVerdictError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected verdict error containing {fragment!r}")


def _expect_boundary_error(fragment, fn):
    try:
        fn()
    except boundary.PhysicalCampaignIndependentHumanVerdictProductionBoundaryError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected boundary error containing {fragment!r}")


def _schema_properties(name):
    value = json.loads((ROOT / "devcontrol" / "schemas" / name).read_text(encoding="utf-8"))
    return set(value["properties"])


def run_contract():
    assert implementation._production_independent_verdict_boundary_installed is True

    public = inspect.signature(independent.verify_physical_campaign_independent_human_verdict)
    assert set(public.parameters) == {"main_freeze_proof", "execution_proof", "verdict", "signature", "verifier"}
    assert public.parameters["verifier"].default is None
    private = inspect.signature(independent._verify_physical_campaign_independent_human_verdict)
    assert set(private.parameters) == {"main_freeze_proof", "execution_proof", "verdict", "signature", "verifier", "now_provider"}

    _expect_verdict_error(
        "caller-selected independent-verdict verifier",
        lambda: independent.verify_physical_campaign_independent_human_verdict(
            main_freeze_proof=None,
            execution_proof=None,
            verdict=None,
            signature=None,
            verifier=object(),
        ),
    )

    private_key, key = _trusted_key()
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)

    with tempfile.TemporaryDirectory(prefix="rsi-independent-verdict-keyring-") as directory:
        path = Path(directory).resolve() / "keyring.json"
        payload = _canonical_keyring(key)
        path.write_bytes(payload)
        if os.name == "posix":
            path.chmod(0o600)
        loaded = boundary._load_physical_campaign_independent_verdict_verifier_at(
            path,
            issuer_system_id=implementation.INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID,
            require_host_control=False,
        )
        assert type(loaded) is Ed25519AuthorityVerifier
        assert set(loaded._trusted_keys) == {key.key_id}

        path.write_bytes(_canonical_keyring(key, domain="another-domain"))
        _expect_boundary_error(
            "another authority domain",
            lambda: boundary._load_physical_campaign_independent_verdict_verifier_at(
                path,
                issuer_system_id=implementation.INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )
        _unused_private, foreign_key = _trusted_key(issuer_system_id="other-independent-verdict-authority")
        path.write_bytes(_canonical_keyring(foreign_key))
        _expect_boundary_error(
            "another issuer system",
            lambda: boundary._load_physical_campaign_independent_verdict_verifier_at(
                path,
                issuer_system_id=implementation.INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )
        path.write_bytes(payload + b"\n")
        _expect_boundary_error(
            "not canonical",
            lambda: boundary._load_physical_campaign_independent_verdict_verifier_at(
                path,
                issuer_system_id=implementation.INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )

    execution = _execution_proof()
    freeze = _freeze_proof(execution)
    verdict = _verdict(freeze, execution)
    signature = _sign(verdict, private_key, key)
    proof = independent._verify_physical_campaign_independent_human_verdict(
        main_freeze_proof=freeze,
        execution_proof=execution,
        verdict=verdict,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-13T12:21:00Z",
    )
    assert proof.verdict_sha256 == verdict.sha256
    assert proof.main_freeze_proof_sha256 == freeze.sha256
    assert proof.execution_proof_sha256 == execution.sha256
    assert proof.independent_human_verdict_verified is True
    assert proof.runner_execution_binding_proven is True
    assert proof.continuous_main_freeze_proven is True
    assert proof.physical_campaign_completed is True
    assert proof.dc_l15_complete is True
    assert proof.dc_l14_independent_human_verdict_required is False
    assert proof.human_pilot_go_required is True
    assert proof.pilot_go_authorized is False
    assert proof.activation_authorized is False
    assert proof.remote_publication_authorized is False
    assert proof.remaining_completion_gates == ("human_pilot_go_decision",)
    assert proof.authority == "verified-independent-human-dc-l15-completion-only"

    _expect_verdict_error("differ from operator and approver", lambda: _verdict(freeze, execution, reviewer="physical.operator"))
    _expect_verdict_error("differ from operator and approver", lambda: _verdict(freeze, execution, reviewer="physical.approver"))

    changed = execution.to_dict()
    changed["runner_sha256"] = "e" * 64
    changed_execution = PhysicalCampaignExecutionProof.from_mapping(changed)
    _expect_verdict_error("not exactly bound", lambda: _verdict(freeze, changed_execution))

    request_changes = _verdict(
        freeze,
        execution,
        decision="request_changes",
        findings=("Reviewer requires another physical run.",),
    )
    request_changes_signature = _sign(request_changes, private_key, key)
    _expect_verdict_error(
        "does not approve",
        lambda: independent._verify_physical_campaign_independent_human_verdict(
            main_freeze_proof=freeze,
            execution_proof=execution,
            verdict=request_changes,
            signature=request_changes_signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-13T12:21:00Z",
        ),
    )

    other_private, other_key = _trusted_key(actor="another.reviewer")
    other_verifier = Ed25519AuthorityVerifier({other_key.key_id: other_key}, minimum_keyring_epoch=1)
    other_signature = _sign(verdict, other_private, other_key)
    _expect_verdict_error(
        "signer must be the reviewer",
        lambda: independent._verify_physical_campaign_independent_human_verdict(
            main_freeze_proof=freeze,
            execution_proof=execution,
            verdict=verdict,
            signature=other_signature,
            verifier=other_verifier,
            now_provider=lambda: "2026-09-13T12:21:00Z",
        ),
    )

    _expect_verdict_error("outside the review window", lambda: _verdict(freeze, execution, reviewed_at="2026-09-14T12:14:01Z"))
    _expect_verdict_error(
        "freshness window",
        lambda: independent._verify_physical_campaign_independent_human_verdict(
            main_freeze_proof=freeze,
            execution_proof=execution,
            verdict=verdict,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T12:20:01Z",
        ),
    )

    escalated = proof.to_dict()
    escalated["pilot_go_authorized"] = True
    _expect_verdict_error(
        "authority boundary",
        lambda: independent.PhysicalCampaignIndependentHumanVerdictProof.from_mapping(escalated),
    )

    assert _schema_properties("rsi-physical-campaign-independent-human-verdict-v1.schema.json") == set(verdict.to_dict())
    assert _schema_properties("rsi-physical-campaign-independent-human-verdict-proof-v1.schema.json") == set(proof.to_dict())

    keyring_path = boundary._canonical_physical_campaign_independent_verdict_keyring_path()
    if os.name == "nt":
        assert str(keyring_path).lower().startswith(r"c:\program files\modelrig\devcontrol\authority")
    elif os.name == "posix":
        assert keyring_path == Path("/etc/modelrig/devcontrol/authority/rsi-physical-campaign-independent-verdict-keyring-v1.json")

    production_source = inspect.getsource(boundary)
    assert "Ed25519PrivateKey" not in production_source
    assert "private_key" not in production_source
    package_init = inspect.getsource(sys.modules["kaliv_dev_control"])
    assert "improvement_physical_campaign_independent_verdict" not in package_init


if __name__ == "__main__":
    run_contract()
