"""Adversarial contract for ADR-DC-059 exact one-shot merge authorization."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_merge_authorization as merge_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_merge_readiness_evaluation as readiness,
)
from rsi_pilot_exact_task_merge_readiness_evaluation_contract import (  # noqa: E402
    _evaluate,
    _policy,
    _ready_review_transport,
)
from rsi_pilot_exact_task_pr_lifecycle_recovery_contract import _cleanup_bundle  # noqa: E402
from rsi_pilot_exact_task_review_state_attestation_contract import (  # noqa: E402
    _Transport,
    _attest,
    _live_post_lifecycle_source,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-merge-authorization-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-059 unexpectedly accepted unsafe merge authority")


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, merge_auth._PilotExactTaskMergeAuthorizationLedger(root)


def _live_ready_evaluation():
    bundle, tx_temp, recovery_temp, tx_ledger, source, _authorization = (
        _live_post_lifecycle_source()
    )
    ready_review = _attest(source, tx_ledger, _ready_review_transport(source))
    policy = _policy(source)
    evaluation = _evaluate(ready_review, policy)
    assert evaluation.evaluation_authenticated is True
    assert evaluation.merge_ready is True
    return bundle, tx_temp, recovery_temp, tx_ledger, source, ready_review, policy, evaluation


def _config(evaluation, *, repository=None, repository_id=None, base_branch=None, merge_method="squash"):
    return merge_auth.PilotExactTaskMergeConfig(
        repository=evaluation.repository if repository is None else repository,
        repository_id=evaluation.repository_id if repository_id is None else repository_id,
        base_branch=evaluation.base_branch if base_branch is None else base_branch,
        merge_method=merge_method,
    )


def _payload(evaluation, config):
    return merge_auth._build_authorization_payload(
        merge_readiness_evaluation=evaluation,
        merge_config=config,
        requested_at_utc="2026-09-15T09:34:10Z",
        expires_at_utc="2026-09-15T09:39:10Z",
        operator_actor_id="merge.operator",
        operator_system_id="offline-merge-operator",
        operator_key_id="merge-op-1",
        reviewer_actor_id="merge.reviewer",
        reviewer_system_id="offline-merge-reviewer",
        reviewer_key_id="merge-review-1",
    )


def _dual_authority(payload: bytes, *, signed_at="2026-09-15T09:34:20Z"):
    custody = asymmetric_authority_key_custody_policy_sha256()
    definitions = (
        (bytes(range(1, 33)), "merge-op-1", "merge.operator", "offline-merge-operator"),
        (bytes(range(33, 65)), "merge-review-1", "merge.reviewer", "offline-merge-reviewer"),
    )
    keys = {}
    signatures = []
    for raw_private, key_id, actor_id, system_id in definitions:
        private = Ed25519PrivateKey.from_private_bytes(raw_private)
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        trusted = TrustedEd25519AuthorityKey(
            key_id=key_id,
            issuer_actor_id=actor_id,
            issuer_system_id=system_id,
            public_key_hex=public.hex(),
            valid_from_utc="2026-01-01T00:00:00Z",
            valid_until_utc="2027-01-01T00:00:00Z",
            keyring_epoch=1,
            custody_policy_sha256=custody,
        )
        keys[key_id] = trusted
        message = authority_signing_message(
            key_id=trusted.key_id,
            issuer_actor_id=trusted.issuer_actor_id,
            issuer_system_id=trusted.issuer_system_id,
            keyring_epoch=trusted.keyring_epoch,
            custody_policy_sha256=custody,
            payload=payload,
        )
        signatures.append(
            DetachedEd25519AuthoritySignature(
                key_id=trusted.key_id,
                issuer_actor_id=trusted.issuer_actor_id,
                issuer_system_id=trusted.issuer_system_id,
                keyring_epoch=trusted.keyring_epoch,
                custody_policy_sha256=custody,
                payload_sha256=hashlib.sha256(payload).hexdigest(),
                signature_hex=private.sign(message).hex(),
                signed_at_utc=signed_at,
            )
        )
    return Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=1), signatures[0], signatures[1]


def _authorize(evaluation, config, payload, verifier, op_sig, review_sig, ledger, *, now="2026-09-15T09:34:30Z"):
    return merge_auth._authorize_verified_pilot_exact_task_merge(
        merge_readiness_evaluation=evaluation,
        merge_config=config,
        authorization_payload=payload,
        operator_signature=op_sig,
        reviewer_signature=review_sig,
        verifier=verifier,
        ledger=ledger,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        bundle,
        tx_temp,
        recovery_temp,
        _tx_ledger,
        source,
        _ready_review,
        _policy_value,
        evaluation,
    ) = _live_ready_evaluation()
    ledger_temp, ledger = _ledger("rsi-exact-task-merge-auth-")
    try:
        config = _config(evaluation)
        payload = _payload(evaluation, config)
        verifier, op_sig, review_sig = _dual_authority(payload)
        receipt = _authorize(
            evaluation, config, payload, verifier, op_sig, review_sig, ledger
        )

        assert receipt.authorization_authenticated is True
        assert receipt.merge_key_sha256 == evaluation.execution_nonce_sha256
        assert receipt.execution_nonce_sha256 == evaluation.execution_nonce_sha256
        assert receipt.merge_readiness_evaluation_sha256 == evaluation.sha256
        assert receipt.review_state_attestation_sha256 == evaluation.review_state_attestation_sha256
        assert receipt.merge_readiness_policy_sha256 == evaluation.merge_readiness_policy_sha256
        assert receipt.merge_config_sha256 == config.sha256
        assert receipt.repository == evaluation.repository
        assert receipt.repository_id == evaluation.repository_id
        assert receipt.base_branch == evaluation.base_branch
        assert receipt.base_sha == evaluation.exact_task_base_sha
        assert receipt.head_branch == evaluation.head_branch
        assert receipt.head_sha == evaluation.predicted_commit_sha
        assert receipt.pull_request_number == evaluation.pull_request_number
        assert receipt.pull_request_node_id_sha256 == evaluation.pull_request_node_id_sha256
        assert receipt.merge_method == "squash"
        assert receipt.host_merge_guard_committed is True
        assert receipt.merge_readiness_evaluation_authenticated is True
        assert receipt.merge_ready is True
        assert receipt.merge_config_host_pinned is True
        assert receipt.dual_external_ed25519_authorized is True
        assert receipt.merge_authorized is True
        assert receipt.remote_write_authorized is True
        assert receipt.review_submission_authorized is False
        assert receipt.review_thread_mutation_authorized is False
        assert receipt.ready_for_review_authorized is False
        assert receipt.reviewer_request_authorized is False
        assert receipt.push_authorized is False
        assert receipt.pr_mutation_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.product_pilot_started is False
        assert receipt.nonce_reusable is False

        reloaded = merge_auth.PilotExactTaskMergeAuthorizationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.authorization_authenticated is False

        _reject(
            lambda: _authorize(
                evaluation, config, payload, verifier, op_sig, review_sig, ledger
            )
        )

        reloaded_eval = readiness.PilotExactTaskMergeReadinessEvaluationReceipt.from_mapping(
            evaluation.to_dict()
        )
        assert reloaded_eval.evaluation_authenticated is False
        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-merge-auth-reloaded-")
        try:
            _reject(
                lambda: _authorize(
                    reloaded_eval, config, payload, verifier, op_sig, review_sig, fresh_ledger
                )
            )
        finally:
            fresh_temp.cleanup()

        blocked_review = _attest(source, _tx_ledger, _Transport(source))
        blocked = _evaluate(blocked_review, _policy(source))
        assert blocked.evaluation_authenticated is True
        assert blocked.merge_ready is False
        _reject(lambda: merge_auth._build_authorization_payload(
            merge_readiness_evaluation=blocked,
            merge_config=_config(blocked),
            requested_at_utc="2026-09-15T09:34:10Z",
            expires_at_utc="2026-09-15T09:39:10Z",
            operator_actor_id="merge.operator",
            operator_system_id="offline-merge-operator",
            operator_key_id="merge-op-1",
            reviewer_actor_id="merge.reviewer",
            reviewer_system_id="offline-merge-reviewer",
            reviewer_key_id="merge-review-1",
        ))

        for bad_config in (
            _config(evaluation, repository="other/repo"),
            _config(evaluation, repository_id="999"),
            _config(evaluation, base_branch="other"),
        ):
            _reject(lambda bad_config=bad_config: merge_auth._build_authorization_payload(
                merge_readiness_evaluation=evaluation,
                merge_config=bad_config,
                requested_at_utc="2026-09-15T09:34:10Z",
                expires_at_utc="2026-09-15T09:39:10Z",
                operator_actor_id="merge.operator",
                operator_system_id="offline-merge-operator",
                operator_key_id="merge-op-1",
                reviewer_actor_id="merge.reviewer",
                reviewer_system_id="offline-merge-reviewer",
                reviewer_key_id="merge-review-1",
            ))
        _reject(lambda: _config(evaluation, merge_method="merge"))

        parsed = json.loads(payload.decode("utf-8"))
        parsed["head_sha"] = "f" * 40
        bad_payload = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        bad_verifier, bad_op, bad_review = _dual_authority(bad_payload)
        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-merge-auth-bad-payload-")
        try:
            _reject(lambda: _authorize(
                evaluation, config, bad_payload, bad_verifier, bad_op, bad_review, fresh_ledger
            ))
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-merge-auth-same-signer-")
        try:
            _reject(lambda: _authorize(
                evaluation, config, payload, verifier, op_sig, op_sig, fresh_ledger
            ))
        finally:
            fresh_temp.cleanup()

        stale_verifier, stale_op, stale_review = _dual_authority(
            payload, signed_at="2026-09-15T09:34:00Z"
        )
        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-merge-auth-stale-signature-")
        try:
            _reject(lambda: _authorize(
                evaluation, config, payload, stale_verifier, stale_op, stale_review, fresh_ledger
            ))
        finally:
            fresh_temp.cleanup()
        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-merge-auth-expired-")
        try:
            _reject(lambda: _authorize(
                evaluation, config, payload, verifier, op_sig, review_sig, fresh_ledger,
                now="2026-09-15T09:39:10Z",
            ))
        finally:
            fresh_temp.cleanup()

        for field, value in (
            ("host_merge_guard_committed", False),
            ("merge_readiness_evaluation_authenticated", False),
            ("merge_ready", False),
            ("merge_config_host_pinned", False),
            ("dual_external_ed25519_authorized", False),
            ("merge_authorized", False),
            ("remote_write_authorized", False),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(lambda field=field, value=value: (
                merge_auth.PilotExactTaskMergeAuthorizationReceipt.from_mapping(
                    {**receipt.to_dict(), field: value}
                )
            ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(merge_auth.PilotExactTaskMergeAuthorizationReceipt.__dataclass_fields__)
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["merge_authorized"]["const"] is True
        assert schema["properties"]["remote_write_authorized"]["const"] is True
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert schema["properties"]["release_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert schema["properties"]["nonce_reusable"]["const"] is False

        build_public = inspect.signature(
            merge_auth.build_pilot_exact_task_merge_authorization_payload
        ).parameters
        assert tuple(build_public) == (
            "merge_readiness_evaluation",
            "requested_at_utc",
            "expires_at_utc",
            "operator_actor_id",
            "operator_system_id",
            "operator_key_id",
            "reviewer_actor_id",
            "reviewer_system_id",
            "reviewer_key_id",
        )
        authorize_public = inspect.signature(
            merge_auth.authorize_pilot_exact_task_merge
        ).parameters
        assert tuple(authorize_public) == (
            "merge_readiness_evaluation",
            "authorization_payload",
            "operator_signature",
            "reviewer_signature",
        )
        source_text = inspect.getsource(merge_auth)
        assert "urllib" not in source_text
        assert "subprocess" not in source_text
        assert "merge_pull_request" not in source_text
        assert "enable_auto_merge" not in source_text
        assert "Ed25519PrivateKey" not in source_text
        assert "merge_authorized: bool = True" in source_text
        assert "remote_write_authorized: bool = True" in source_text
        assert "push_authorized: bool = False" in source_text
        assert "pr_mutation_authorized: bool = False" in source_text
        assert "production_activation_authorized: bool = False" in source_text
    finally:
        ledger_temp.cleanup()
        recovery_temp.cleanup()
        tx_temp.cleanup()
        _cleanup_bundle(bundle)


if __name__ == "__main__":
    run_contract()
