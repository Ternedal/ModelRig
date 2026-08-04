"""H5C local-candidate entrypoint for Ed25519 authorization evidence.

The implementation deliberately reuses the already-verified trusted-Git local
materialization engine. The wrapper accepts only H5C v2 preflight evidence and
an Ed25519 verifier compatible with the original narrow runtime interface.

It adds no remote, credential, network, push, pull-request, merge, release or
deployment capability.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import local_candidate_materialization as _materialization
from .local_candidate_materialization import (
    LocalCandidateCommitEvidence,
    LocalCandidateMaterializationError,
    LocalCandidateMaterializationReceipt,
    LocalGitEvidence,
    LocalSourceRepositoryEvidence,
    materialize_local_candidate,
    verify_local_candidate_materialization,
)
from .publisher_authorization_chain_v2 import (
    PublisherAuthorizationVerifierV2,
    PublisherPreflightReceiptV2,
)
from .publisher_dry_run import PublisherRequestVerifier
from .semantic_review import SemanticReviewVerifier
from .contract import DevelopmentTask
from .trusted_git_runtime import TrustedGitRuntime


def materialize_asymmetric_local_candidate(
    *,
    preflight: PublisherPreflightReceiptV2,
    task: DevelopmentTask,
    authorization_verifier: PublisherAuthorizationVerifierV2,
    publisher_verifier: PublisherRequestVerifier,
    semantic_verifier: SemanticReviewVerifier,
    control_plane_root: Path,
    source_repository: Path,
    materialization_root: Path,
    trusted_git: TrustedGitRuntime,
    materialized_at_utc: str,
) -> LocalCandidateMaterializationReceipt:
    """Materialize one local candidate from a verified lease-v2 preflight."""

    if not isinstance(preflight, PublisherPreflightReceiptV2):
        raise LocalCandidateMaterializationError(
            "asymmetric local materialization requires preflight v2"
        )
    if not isinstance(
        authorization_verifier,
        PublisherAuthorizationVerifierV2,
    ):
        raise LocalCandidateMaterializationError(
            "asymmetric local materialization requires the Ed25519 verifier"
        )
    receipt = materialize_local_candidate(
        preflight=preflight,
        task=task,
        authorization_verifier=authorization_verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=Path(control_plane_root),
        source_repository=Path(source_repository),
        materialization_root=Path(materialization_root),
        trusted_git=trusted_git,
        materialized_at_utc=materialized_at_utc,
    )
    if (
        not isinstance(receipt.preflight, PublisherPreflightReceiptV2)
        or receipt.preflight.lease.algorithm != "ed25519"
    ):
        raise LocalCandidateMaterializationError(
            "local materialization receipt lost its asymmetric authority binding"
        )
    return receipt


def _receipt_from_mapping_v2(
    value: Any,
) -> LocalCandidateMaterializationReceipt:
    data = _materialization._legacy._strict(
        value,
        name="asymmetric local candidate materialization receipt",
        fields=_materialization._RECEIPT_FIELDS,
    )
    return LocalCandidateMaterializationReceipt(
        schema=data["schema"],
        preflight=PublisherPreflightReceiptV2.from_mapping(data["preflight"]),
        preflight_sha256=data["preflight_sha256"],
        lease_sha256=data["lease_sha256"],
        replay_entry_sha256=data["replay_entry_sha256"],
        request_sha256=data["request_sha256"],
        readiness_sha256=data["readiness_sha256"],
        task_sha256=data["task_sha256"],
        invocation_nonce=data["invocation_nonce"],
        materialization_policy_sha256=data["materialization_policy_sha256"],
        materialized_at_utc=data["materialized_at_utc"],
        transaction_id=data["transaction_id"],
        repository_relative_path=data["repository_relative_path"],
        receipt_relative_path=data["receipt_relative_path"],
        git=LocalGitEvidence.from_mapping(data["git"]),
        source=LocalSourceRepositoryEvidence.from_mapping(data["source"]),
        candidate=LocalCandidateCommitEvidence.from_mapping(data["candidate"]),
        bare_repository=data["bare_repository"],
        isolated_index=data["isolated_index"],
        local_source_only=data["local_source_only"],
        remote_configured=data["remote_configured"],
        network_write_performed=data["network_write_performed"],
        remote_push_performed=data["remote_push_performed"],
        pull_request_created=data["pull_request_created"],
        ready_for_review=data["ready_for_review"],
        reviewers_requested=data["reviewers_requested"],
        merged=data["merged"],
        released=data["released"],
        deployed=data["deployed"],
        merge_authority=data["merge_authority"],
    )


def load_asymmetric_local_candidate_receipt(
    path: Path,
) -> LocalCandidateMaterializationReceipt:
    """Load a canonical local receipt whose embedded preflight is v2."""

    receipt = _materialization._legacy._load_canonical(
        Path(path),
        _receipt_from_mapping_v2,
        name="asymmetric local candidate materialization receipt",
    )
    if (
        not isinstance(receipt.preflight, PublisherPreflightReceiptV2)
        or receipt.preflight.lease.algorithm != "ed25519"
    ):
        raise LocalCandidateMaterializationError(
            "local receipt is not bound to asymmetric authorization"
        )
    return receipt


def verify_asymmetric_local_candidate(
    *,
    receipt: LocalCandidateMaterializationReceipt,
    task: DevelopmentTask,
    authorization_verifier: PublisherAuthorizationVerifierV2,
    publisher_verifier: PublisherRequestVerifier,
    semantic_verifier: SemanticReviewVerifier,
    control_plane_root: Path,
    source_repository: Path,
    materialization_root: Path,
    trusted_git: TrustedGitRuntime,
) -> None:
    """Verify one local candidate and its embedded lease-v2 chain."""

    if (
        not isinstance(receipt, LocalCandidateMaterializationReceipt)
        or not isinstance(receipt.preflight, PublisherPreflightReceiptV2)
        or receipt.preflight.lease.algorithm != "ed25519"
    ):
        raise LocalCandidateMaterializationError(
            "asymmetric local verification requires a lease-v2 receipt"
        )
    if not isinstance(
        authorization_verifier,
        PublisherAuthorizationVerifierV2,
    ):
        raise LocalCandidateMaterializationError(
            "asymmetric local verification requires the Ed25519 verifier"
        )
    verify_local_candidate_materialization(
        receipt=receipt,
        task=task,
        authorization_verifier=authorization_verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=Path(control_plane_root),
        source_repository=Path(source_repository),
        materialization_root=Path(materialization_root),
        trusted_git=trusted_git,
    )


class AsymmetricLocalCandidateMaterializationGate:
    @staticmethod
    def valid(
        *,
        receipt: LocalCandidateMaterializationReceipt,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifierV2,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        source_repository: Path,
        materialization_root: Path,
        trusted_git: TrustedGitRuntime,
    ) -> bool:
        try:
            verify_asymmetric_local_candidate(
                receipt=receipt,
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
                source_repository=Path(source_repository),
                materialization_root=Path(materialization_root),
                trusted_git=trusted_git,
            )
        except LocalCandidateMaterializationError:
            return False
        return True


__all__ = [
    "AsymmetricLocalCandidateMaterializationGate",
    "load_asymmetric_local_candidate_receipt",
    "materialize_asymmetric_local_candidate",
    "verify_asymmetric_local_candidate",
]
