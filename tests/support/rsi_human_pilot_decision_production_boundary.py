"""Adversarial production-boundary contract for ADR-DC-015 pilot decision."""
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
import kaliv_dev_control._improvement_human_pilot_decision_impl as implementation  # noqa: E402
import kaliv_dev_control._improvement_human_pilot_decision_production_boundary as boundary  # noqa: E402
import kaliv_dev_control.improvement_human_pilot_decision as pilot  # noqa: E402
from kaliv_dev_control.improvement_physical_campaign_independent_verdict import (  # noqa: E402
    INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID,
    PhysicalCampaignIndependentHumanVerdictProof,
)


def _trusted_key(*, actor="pilot.owner", issuer_system_id=implementation.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID):
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    key = TrustedEd25519AuthorityKey(
        key_id="rsi-human-pilot-decision-test-key",
        issuer_actor_id=actor,
        issuer_system_id=issuer_system_id,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-13T00:00:00Z",
        valid_until_utc="2026-09-16T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=asymmetric_authority_key_custody_policy_sha256(),
    )
    return private, key


def _canonical_keyring(key, *, domain=boundary.HUMAN_PILOT_DECISION_AUTHORITY_DOMAIN):
    return json.dumps(
        {
            "schema": boundary.HUMAN_PILOT_DECISION_KEYRING_SCHEMA,
            "authority_domain": domain,
            "minimum_keyring_epoch": 1,
            "trusted_keys": [key.to_dict()],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _completion_proof():
    return PhysicalCampaignIndependentHumanVerdictProof(
        verdict_sha256="1" * 64,
        signature_sha256="2" * 64,
        key_id="rsi-independent-verdict-test-key",
        issuer_actor_id="physical.reviewer",
        issuer_system_id=INDEPENDENT_VERDICT_ISSUER_SYSTEM_ID,
        main_freeze_proof_sha256="3" * 64,
        execution_proof_sha256="4" * 64,
        evidence_snapshot_sha256="5" * 64,
        admission_sha256="6" * 64,
        campaign_id="campaign-001",
        task_id="RSI_TASK_001",
        task_sha256="7" * 64,
        repository="Ternedal/ModelRig",
        base_sha="1" * 40,
        requested_main_sha="2" * 40,
        operator_actor_id="physical.operator",
        approver_actor_id="physical.approver",
        reviewer_actor_id="physical.reviewer",
        verdict_id="independent-verdict-001",
        decision="approve",
        findings=(),
        reviewed_at_utc="2026-09-13T12:20:00Z",
        verified_at_utc="2026-09-13T12:21:00Z",
    )


def _decision(completion, *, decision="go", notes=(), actor="pilot.owner", decided_at="2026-09-13T12:30:00Z"):
    return pilot.build_human_pilot_decision(
        completion_proof=completion,
        decision_id="pilot-decision-001",
        decision_maker_actor_id=actor,
        decision=decision,
        operator_surface="desktop_control_center",
        allowed_task_ids=("pilot.task.plan",),
        workspace_root_path_sha256="8" * 64,
        local_commits_allowed=False,
        notes=notes,
        decided_at_utc=decided_at,
    )


def _sign(decision, private, key):
    payload = decision.canonical_json().encode("utf-8")
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
        signed_at_utc=decision.decided_at_utc,
    )


def _expect_pilot_error(fragment, fn):
    try:
        fn()
    except pilot.HumanPilotDecisionError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected pilot decision error containing {fragment!r}")


def _expect_boundary_error(fragment, fn):
    try:
        fn()
    except boundary.HumanPilotDecisionProductionBoundaryError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected production-boundary error containing {fragment!r}")


def _schema_properties(name):
    value = json.loads((ROOT / "devcontrol" / "schemas" / name).read_text(encoding="utf-8"))
    return set(value["properties"])


def run_contract():
    assert implementation._production_human_pilot_decision_boundary_installed is True

    public = inspect.signature(pilot.verify_human_pilot_decision)
    assert set(public.parameters) == {"completion_proof", "decision", "signature", "verifier"}
    assert public.parameters["verifier"].default is None
    private = inspect.signature(pilot._verify_human_pilot_decision)
    assert set(private.parameters) == {"completion_proof", "decision", "signature", "verifier", "now_provider"}

    _expect_pilot_error(
        "caller-selected human pilot decision verifier",
        lambda: pilot.verify_human_pilot_decision(
            completion_proof=None,
            decision=None,
            signature=None,
            verifier=object(),
        ),
    )

    private_key, key = _trusted_key()
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)

    with tempfile.TemporaryDirectory(prefix="rsi-human-pilot-keyring-") as directory:
        path = Path(directory).resolve() / "keyring.json"
        payload = _canonical_keyring(key)
        path.write_bytes(payload)
        if os.name == "posix":
            path.chmod(0o600)
        loaded = boundary._load_human_pilot_decision_verifier_at(
            path,
            issuer_system_id=implementation.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID,
            require_host_control=False,
        )
        assert type(loaded) is Ed25519AuthorityVerifier
        assert set(loaded._trusted_keys) == {key.key_id}

        path.write_bytes(_canonical_keyring(key, domain="another-domain"))
        _expect_boundary_error(
            "another authority domain",
            lambda: boundary._load_human_pilot_decision_verifier_at(
                path,
                issuer_system_id=implementation.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )
        _unused_private, foreign_key = _trusted_key(issuer_system_id="other-human-pilot-authority")
        path.write_bytes(_canonical_keyring(foreign_key))
        _expect_boundary_error(
            "another issuer system",
            lambda: boundary._load_human_pilot_decision_verifier_at(
                path,
                issuer_system_id=implementation.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )
        path.write_bytes(payload + b"\n")
        _expect_boundary_error(
            "not canonical",
            lambda: boundary._load_human_pilot_decision_verifier_at(
                path,
                issuer_system_id=implementation.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID,
                require_host_control=False,
            ),
        )

    completion = _completion_proof()
    go = _decision(completion)
    go_signature = _sign(go, private_key, key)
    go_proof = pilot._verify_human_pilot_decision(
        completion_proof=completion,
        decision=go,
        signature=go_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-13T12:31:00Z",
    )
    assert go_proof.decision_sha256 == go.sha256
    assert go_proof.completion_proof_sha256 == completion.sha256
    assert go_proof.human_pilot_decision_recorded is True
    assert go_proof.pilot_go_authorized is True
    assert go_proof.product_pilot_started is False
    assert go_proof.feature_flag_default_off is True
    assert go_proof.remote_write_authorized is False
    assert go_proof.merge_authorized is False
    assert go_proof.release_authorized is False
    assert go_proof.deploy_authorized is False
    assert go_proof.production_activation_authorized is False
    assert go_proof.authority == "verified-human-dc-l16-pilot-decision-only"

    no_go = _decision(
        completion,
        decision="no_go",
        notes=("Pilot scope needs another review.",),
    )
    no_go_signature = _sign(no_go, private_key, key)
    no_go_proof = pilot._verify_human_pilot_decision(
        completion_proof=completion,
        decision=no_go,
        signature=no_go_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-13T12:31:00Z",
    )
    assert no_go_proof.human_pilot_decision_recorded is True
    assert no_go_proof.pilot_go_authorized is False
    assert no_go_proof.product_pilot_started is False

    conditional = _decision(
        completion,
        decision="go_with_conditions",
        notes=("First pilot remains plan-only.",),
    )
    conditional_signature = _sign(conditional, private_key, key)
    conditional_proof = pilot._verify_human_pilot_decision(
        completion_proof=completion,
        decision=conditional,
        signature=conditional_signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-13T12:31:00Z",
    )
    assert conditional_proof.pilot_go_authorized is True
    assert conditional_proof.notes == ("First pilot remains plan-only.",)

    _expect_pilot_error(
        "require explicit notes",
        lambda: _decision(completion, decision="no_go"),
    )
    _expect_pilot_error(
        "require explicit notes",
        lambda: _decision(completion, decision="go_with_conditions"),
    )
    _expect_pilot_error(
        "predates DC-L15 completion",
        lambda: _decision(completion, decided_at="2026-09-13T12:20:59Z"),
    )

    tampered = pilot.HumanPilotDecision.from_mapping(
        {**go.to_dict(), "operator_surface": "different_surface"}
    )
    _expect_pilot_error(
        "authority verification failed",
        lambda: pilot._verify_human_pilot_decision(
            completion_proof=completion,
            decision=tampered,
            signature=go_signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-13T12:31:00Z",
        ),
    )

    other_private, other_key = _trusted_key(actor="another.owner")
    other_verifier = Ed25519AuthorityVerifier({other_key.key_id: other_key}, minimum_keyring_epoch=1)
    other_signature = _sign(go, other_private, other_key)
    _expect_pilot_error(
        "signer must be the decision maker",
        lambda: pilot._verify_human_pilot_decision(
            completion_proof=completion,
            decision=go,
            signature=other_signature,
            verifier=other_verifier,
            now_provider=lambda: "2026-09-13T12:31:00Z",
        ),
    )

    over = go_proof.to_dict()
    over["product_pilot_started"] = True
    _expect_pilot_error(
        "authority boundary",
        lambda: pilot.HumanPilotDecisionProof.from_mapping(over),
    )
    over = go_proof.to_dict()
    over["production_activation_authorized"] = True
    _expect_pilot_error(
        "authority boundary",
        lambda: pilot.HumanPilotDecisionProof.from_mapping(over),
    )

    assert _schema_properties("rsi-human-pilot-decision-v1.schema.json") == set(go.to_dict())
    assert _schema_properties("rsi-human-pilot-decision-proof-v1.schema.json") == set(go_proof.to_dict())

    keyring_path = boundary._canonical_human_pilot_decision_keyring_path()
    if os.name == "nt":
        assert str(keyring_path).lower().startswith(r"c:\program files\modelrig\devcontrol\authority")
    elif os.name == "posix":
        assert keyring_path == Path("/etc/modelrig/devcontrol/authority/rsi-human-pilot-decision-keyring-v1.json")

    production_source = inspect.getsource(boundary)
    assert "Ed25519PrivateKey" not in production_source
    assert "private_key" not in production_source
    package_init = inspect.getsource(sys.modules["kaliv_dev_control"])
    assert "improvement_human_pilot_decision" not in package_init


if __name__ == "__main__":
    run_contract()
