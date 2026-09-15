"""Adversarial contract for ADR-DC-049 host-pinned remote target attestation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_remote_publication_target_attestation_impl as target_impl,
)
from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_remote_publication_target_attestation_production_boundary as target_production,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_authorization as auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_target_attestation as target,
)
from rsi_pilot_exact_task_remote_publication_authorization_contract import (  # noqa: E402
    _claim,
    _human_authority,
    _material,
)

POLICY_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-target-policy-v1.schema.json"
)
ATTESTATION_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-target-attestation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        target.PilotExactTaskRemotePublicationTargetAttestationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-049 unexpectedly accepted invalid target authority")


def _proofs(requirements):
    claim = _claim(requirements)
    verifier, signature = _human_authority(claim)
    supplied = auth._verify_pilot_exact_task_remote_publication_authorization(
        local_commit_publication_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:17:00Z",
    )
    fresh = auth._verify_pilot_exact_task_remote_publication_authorization(
        local_commit_publication_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:18:00Z",
    )
    return claim, signature, supplied, fresh


def run_contract() -> None:
    if os.name == "nt":
        return

    material = _material()
    requirements = material[-1]
    try:
        claim, signature, proof, fresh = _proofs(requirements)
        target.require_fresh_remote_publication_authorization_proof_identity(
            proof,
            fresh,
        )

        policy = target.PilotExactTaskRemotePublicationTargetPolicy(policy_epoch=1)
        assert policy.provider == "github"
        assert policy.remote_host == "github.com"
        assert policy.remote_repository == "Ternedal/ModelRig"
        assert policy.canonical_remote_url == "https://github.com/Ternedal/ModelRig.git"
        assert policy.remote_state_observation_required is True
        assert policy.remote_write_reservation_required is True
        assert policy.remote_branch_compare_and_swap_required is True
        assert policy.expected_old_remote_sha_required is True
        assert policy.no_force_push_required is True
        assert policy.separate_pr_mutation_authorization_required is True

        attestation = target._attest_verified_pilot_exact_task_remote_publication_target(
            authorization_proof=proof,
            fresh_authorization_proof=fresh,
            target_policy=policy,
            now_provider=lambda: "2026-09-15T06:19:00Z",
        )
        expected_ref = (
            "refs/heads/agent/rsi/remote-candidate/"
            + claim.remote_publication_nonce_sha256
        )
        assert attestation.authorization_proof_sha256 == fresh.sha256
        assert attestation.authorization_sha256 == claim.sha256
        assert attestation.authorization_signature_sha256 == signature.sha256
        assert (
            attestation.local_commit_publication_requirements_sha256
            == requirements.sha256
        )
        assert (
            attestation.local_commit_write_transaction_sha256
            == requirements.local_commit_write_transaction_sha256
        )
        assert (
            attestation.local_commit_object_identity_sha256
            == requirements.local_commit_object_identity_sha256
        )
        assert attestation.execution_nonce_sha256 == requirements.execution_nonce_sha256
        assert attestation.local_write_nonce_sha256 == requirements.local_write_nonce_sha256
        assert (
            attestation.remote_publication_nonce_sha256
            == claim.remote_publication_nonce_sha256
        )
        assert attestation.predicted_commit_sha == requirements.predicted_commit_sha
        assert attestation.repository == "Ternedal/ModelRig"
        assert attestation.target_policy_sha256 == policy.sha256
        assert attestation.target_policy_epoch == 1
        assert attestation.target_provider == "github"
        assert attestation.target_host == "github.com"
        assert attestation.target_repository == "Ternedal/ModelRig"
        assert attestation.canonical_remote_url == "https://github.com/Ternedal/ModelRig.git"
        assert attestation.destination_ref == expected_ref
        assert attestation.attested_at_utc == "2026-09-15T06:19:00Z"
        assert attestation.target_attestation_authenticated is True

        for field in (
            "human_remote_publication_authorization_verified",
            "remote_target_host_pinned",
            "destination_ref_derived_from_signed_nonce",
            "remote_state_observation_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "expected_old_remote_sha_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            assert getattr(attestation, field) is True
        for field in (
            "remote_publication_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(attestation, field) is False

        reloaded = target.PilotExactTaskRemotePublicationTargetAttestation.from_mapping(
            attestation.to_dict()
        )
        assert reloaded == attestation
        assert reloaded.sha256 == attestation.sha256
        assert reloaded.target_attestation_authenticated is False

        reloaded_proof = auth.PilotExactTaskRemotePublicationAuthorizationProof.from_mapping(
            proof.to_dict()
        )
        assert (
            reloaded_proof.authorization.local_commit_publication_requirements.verification_authenticated
            is False
        )
        _reject(lambda: target._require_live_proof(reloaded_proof))

        # Exact target identity and destination namespace are not caller choices.
        for field, value in (
            ("provider", "gitlab"),
            ("remote_host", "example.com"),
            ("remote_repository", "Ternedal/Other"),
            ("canonical_remote_url", "https://example.com/Ternedal/ModelRig.git"),
            ("destination_ref_namespace", "refs/heads/main/"),
        ):
            changed = policy.to_dict()
            changed[field] = value
            _reject(
                lambda changed=changed: target.PilotExactTaskRemotePublicationTargetPolicy.from_mapping(
                    changed
                )
            )

        for field in (
            "remote_state_observation_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "expected_old_remote_sha_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            changed = policy.to_dict()
            changed[field] = False
            _reject(
                lambda changed=changed: target.PilotExactTaskRemotePublicationTargetPolicy.from_mapping(
                    changed
                )
            )

        changed_ref = attestation.to_dict()
        changed_ref["destination_ref"] = "refs/heads/main"
        _reject(
            lambda: target.PilotExactTaskRemotePublicationTargetAttestation.from_mapping(
                changed_ref
            )
        )
        changed_repo = attestation.to_dict()
        changed_repo["target_repository"] = "Ternedal/Other"
        _reject(
            lambda: target.PilotExactTaskRemotePublicationTargetAttestation.from_mapping(
                changed_repo
            )
        )
        for field in (
            "human_remote_publication_authorization_verified",
            "remote_target_host_pinned",
            "destination_ref_derived_from_signed_nonce",
            "remote_state_observation_required",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "expected_old_remote_sha_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            changed = attestation.to_dict()
            changed[field] = False
            _reject(
                lambda changed=changed: target.PilotExactTaskRemotePublicationTargetAttestation.from_mapping(
                    changed
                )
            )
        for field in (
            "remote_publication_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            changed = attestation.to_dict()
            changed[field] = True
            _reject(
                lambda changed=changed: target.PilotExactTaskRemotePublicationTargetAttestation.from_mapping(
                    changed
                )
            )

        # Attestation must remain inside the signed human authorization window.
        _reject(
            lambda: target._attest_verified_pilot_exact_task_remote_publication_target(
                authorization_proof=proof,
                fresh_authorization_proof=fresh,
                target_policy=policy,
                now_provider=lambda: "2026-09-15T06:26:01Z",
            )
        )

        # Host policy loader accepts only byte-for-byte canonical policy JSON.
        policy_temp = TemporaryDirectory(prefix="rsi-remote-target-policy-049-")
        try:
            policy_path = Path(policy_temp.name) / "policy.json"
            policy_path.write_bytes(policy.canonical_json().encode("utf-8"))
            loaded = target_production._load_target_policy_at(
                target_impl,
                policy_path,
                require_host_control=False,
            )
            assert loaded == policy
            policy_path.write_text(
                json.dumps(policy.to_dict(), indent=2),
                encoding="utf-8",
            )
            _reject(
                lambda: target_production._load_target_policy_at(
                    target_impl,
                    policy_path,
                    require_host_control=False,
                )
            )
        finally:
            policy_temp.cleanup()

        policy_schema = json.loads(POLICY_SCHEMA.read_text(encoding="utf-8"))
        attestation_schema = json.loads(
            ATTESTATION_SCHEMA.read_text(encoding="utf-8")
        )
        assert set(policy_schema["properties"]) == set(policy.to_dict())
        assert set(policy_schema["required"]) == set(policy.to_dict())
        assert set(attestation_schema["properties"]) == set(attestation.to_dict())
        assert set(attestation_schema["required"]) == set(attestation.to_dict())
        assert policy_schema["properties"]["no_force_push_required"]["const"] is True
        assert attestation_schema["properties"]["remote_write_authorized"]["const"] is False
        assert attestation_schema["properties"]["push_authorized"]["const"] is False
        assert (
            attestation_schema["properties"]["production_activation_authorized"]["const"]
            is False
        )

        public_parameters = inspect.signature(
            target.attest_pilot_exact_task_remote_publication_target
        ).parameters
        assert tuple(public_parameters) == (
            "authorization_proof",
            "authorization_signature",
        )
        _reject(
            lambda: target.attest_pilot_exact_task_remote_publication_target(
                authorization_proof=proof,
                authorization_signature=signature,
            )
        )

        implementation_source = inspect.getsource(target_impl)
        production_source = inspect.getsource(target_production)
        for forbidden in (
            "subprocess",
            "shell=True",
            '"ls-remote"',
            "('ls-remote',",
            '("push",',
            '("fetch",',
            '("update-ref",',
            "create_pull_request",
            "merge_pull_request",
        ):
            assert forbidden not in implementation_source
            assert forbidden not in production_source
    finally:
        material[6].cleanup()
        material[5].cleanup()
        material[4].cleanup()
        material[3].cleanup()
        material[2].cleanup()
        material[1].cleanup()
        material[0].cleanup()


if __name__ == "__main__":
    run_contract()
