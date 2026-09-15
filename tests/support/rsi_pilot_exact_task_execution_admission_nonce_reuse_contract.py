"""Focused replay contract: one ADR-DC-030 execution nonce gets one host slot."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control.improvement_pilot_exact_task_execution_admission as admission  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_authorization as auth  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_attestation as verify  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_revalidation_observation as obs  # noqa: E402
from rsi_pilot_exact_task_execution_admission_contract import _ledger, _proof  # noqa: E402
from rsi_pilot_exact_task_execution_revalidation_attestation_contract import (  # noqa: E402
    _host_authority,
)
from rsi_pilot_exact_task_execution_revalidation_observation_contract import (  # noqa: E402
    _evidence,
    _human_authority,
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-033 reused execution nonce unexpectedly admitted twice")


def run_contract() -> None:
    source_temp, proof, fresh, *_ = _proof()
    ledger_temp, ledger = _ledger("rsi-exact-task-admission-nonce-reuse-")
    try:
        source_authorization = (
            proof.attestation.packet.execution_authorization_proof.authorization
        )
        requirements = source_authorization.execution_requirements

        # Issue a distinct, correctly signed ADR-DC-030 authorization that
        # deliberately reuses the already signed one-shot execution nonce.
        # ADR-DC-030 validates structure/signature, while ADR-DC-033 owns the
        # host-local create-once replay guard for that nonce.
        second_authorization = auth.build_pilot_exact_task_execution_authorization(
            execution_requirements=requirements,
            authorization_id="exact-task-execution-authorization-033-reused-nonce",
            execution_authorizer_actor_id=(
                source_authorization.execution_authorizer_actor_id
            ),
            authorized_at_utc="2026-09-14T08:32:10Z",
            expires_at_utc="2026-09-14T08:42:00Z",
            execution_nonce_sha256=source_authorization.execution_nonce_sha256,
            notes=("deliberate nonce-reuse adversarial case",),
        )
        second_human_verifier, second_human_signature = _human_authority(
            second_authorization
        )
        second_authorization_proof = (
            auth._verify_pilot_exact_task_execution_authorization(
                execution_requirements=requirements,
                authorization=second_authorization,
                signature=second_human_signature,
                verifier=second_human_verifier,
                now_provider=lambda: "2026-09-14T08:33:10Z",
            )
        )
        assert (
            second_authorization_proof.sha256
            != proof.execution_authorization_proof_sha256
        )
        assert (
            second_authorization_proof.execution_nonce_sha256
            == proof.execution_nonce_sha256
        )

        second_packet = obs.build_pilot_exact_task_execution_revalidation_observation_packet(
            execution_authorization_proof=second_authorization_proof,
            observation_id="exact-task-revalidation-observation-033-reused-nonce",
            observer_actor_id=proof.attestation.packet.observer_actor_id,
            observed_at_utc="2026-09-14T08:34:10Z",
            evidence_sha256=_evidence(second_authorization_proof),
        )
        second_claim = verify.build_pilot_exact_task_execution_revalidation_attestation(
            packet=second_packet,
            attestation_id="exact-task-revalidation-attestation-033-reused-nonce",
            observer_host_id="modelrig-authority-host-033-reused-nonce",
            attested_at_utc="2026-09-14T08:35:10Z",
            results={name: True for name in verify.RESULT_FIELDS},
        )
        second_host_verifier, second_host_signature = _host_authority(second_claim)
        second_proof = verify._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=second_claim,
            signature=second_host_signature,
            verifier=second_host_verifier,
            now_provider=lambda: "2026-09-14T08:36:00Z",
        )
        second_fresh = verify._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=second_claim,
            signature=second_host_signature,
            verifier=second_host_verifier,
            now_provider=lambda: "2026-09-14T08:36:15Z",
        )

        assert second_proof.execution_authorization_proof_sha256 != (
            proof.execution_authorization_proof_sha256
        )
        assert second_proof.execution_nonce_sha256 == proof.execution_nonce_sha256
        assert admission._admission_key(proof) == proof.execution_nonce_sha256
        assert admission._admission_key(second_proof) == proof.execution_nonce_sha256

        first_times = iter(("2026-09-14T08:36:20Z", "2026-09-14T08:36:21Z"))
        first_receipt = admission._admit_verified_exact_task_execution(
            supplied_proof=proof,
            fresh_proof=fresh,
            ledger=ledger,
            now_provider=lambda: next(first_times),
        )
        assert first_receipt.admission_key_sha256 == proof.execution_nonce_sha256

        # The second authorization has a different proof identity, but because
        # it reuses the same signed nonce it must collide with the permanent
        # create-once marker and fail closed.
        second_times = iter(("2026-09-14T08:36:22Z", "2026-09-14T08:36:23Z"))
        _reject(
            lambda: admission._admit_verified_exact_task_execution(
                supplied_proof=second_proof,
                fresh_proof=second_fresh,
                ledger=ledger,
                now_provider=lambda: next(second_times),
            )
        )
    finally:
        ledger_temp.cleanup()
        source_temp.cleanup()

    # ADR-DC-034 follows admission but remains inert and runs through the same
    # locked Stage-B support chain rather than expanding top-level test inventory.
    from rsi_pilot_exact_task_execution_plan_requirements_contract import (
        run_contract as run_execution_plan_requirements_contract,
    )
    # ADR-DC-035 resolves only the host-pinned exact DevelopmentTask and remains
    # non-executing on the same locked Stage-B support chain.
    from rsi_pilot_exact_task_development_task_binding_contract import (
        run_contract as run_development_task_binding_contract,
    )
    # Live ADR-DC-035 provenance is separate process-local authority and must not
    # reappear after serialization/reload. Keep that regression on Stage-B too.
    from rsi_pilot_exact_task_development_task_binding_live_provenance_contract import (
        run_contract as run_development_task_binding_live_provenance_contract,
    )
    # ADR-DC-036 remains capability-only. The legacy broad contract is imported
    # only as a helper by the focused contracts below and is not executed because
    # it predates the workspace-snapshot hardening of execution-plan authority.
    from rsi_pilot_exact_task_executor_capability_live_guard_contract import (
        run_contract as run_executor_capability_live_guard_contract,
    )
    from rsi_pilot_exact_task_executor_secret_custody_contract import (
        run_contract as run_executor_secret_custody_contract,
    )
    from rsi_pilot_exact_task_executor_capability_semantics_contract import (
        run_contract as run_executor_capability_semantics_contract,
    )
    # ADR-DC-037 is the first layer allowed to claim a materialized execution
    # plan. It freezes one exact read-only GitWorkspaceSnapshot and exact fixed
    # command plan, but still does not reserve the nonce or launch the task.
    from rsi_pilot_exact_task_execution_plan_contract import (
        run_contract as run_execution_plan_contract,
    )
    # ADR-DC-038 creates a permanent host-local pre-launch reservation only
    # after two fresh exact workspace checks. It still cannot launch the task.
    from rsi_pilot_exact_task_prelaunch_reservation_contract import (
        run_contract as run_prelaunch_reservation_contract,
    )
    # ADR-DC-039 permanently consumes the exact reservation before invoking the
    # sole existing hardened Tier-A receipt path. No publication authority follows.
    from rsi_pilot_exact_task_execution_transaction_contract import (
        run_contract as run_execution_transaction_contract,
    )
    # ADR-DC-040 fresh-rechecks the successful frozen candidate and performs
    # read-only mechanical scope/test evaluation. It grants no commit authority.
    from rsi_pilot_exact_task_post_execution_evaluation_contract import (
        run_contract as run_post_execution_evaluation_contract,
    )
    # ADR-DC-041 freezes deterministic local-commit intent around the exact
    # evaluated staged candidate. It writes no Git objects and grants no commit authority.
    from rsi_pilot_exact_task_local_commit_plan_contract import (
        run_contract as run_local_commit_plan_contract,
    )
    # ADR-DC-042 reconstructs the exact tree/commit object identities using only
    # read-only TrustedGit evidence. It still grants no Git object/ref authority.
    from rsi_pilot_exact_task_local_commit_object_identity_contract import (
        run_contract as run_local_commit_object_identity_contract,
    )
    # ADR-DC-043 freezes the human/host requirements for one exact local write.
    # It performs no Git mutation and keeps all local/remote write authority false.
    from rsi_pilot_exact_task_local_commit_write_requirements_contract import (
        run_contract as run_local_commit_write_requirements_contract,
    )
    # ADR-DC-044 verifies one human-signed exact local-write intent but still
    # grants no object/ref/commit or remote publication authority.
    from rsi_pilot_exact_task_local_commit_authorization_contract import (
        run_contract as run_local_commit_authorization_contract,
    )
    # ADR-DC-045 fresh-reverifies the exact human signature and live object
    # identity, then durably reserves the one-shot local-write nonce only.
    from rsi_pilot_exact_task_local_commit_write_reservation_contract import (
        run_contract as run_local_commit_write_reservation_contract,
    )
    # ADR-DC-046 consumes the live reservation into exact local Git objects plus
    # one create-only host-pinned custom ref. Remote publication remains false.
    from rsi_pilot_exact_task_local_commit_write_transaction_contract import (
        run_contract as run_local_commit_write_transaction_contract,
    )
    # ADR-DC-047 read-only verifies the completed local object/ref graph and
    # freezes requirements for any later separately authorized remote publication.
    from rsi_pilot_exact_task_local_commit_publication_requirements_contract import (
        run_contract as run_local_commit_publication_requirements_contract,
    )
    # ADR-DC-048 verifies fresh human intent over exactly the live ADR-DC-047
    # manifest but still selects no remote target and grants no mutation authority.
    from rsi_pilot_exact_task_remote_publication_authorization_contract import (
        run_contract as run_remote_publication_authorization_contract,
    )
    # ADR-DC-049 host-pins the exact remote repository and derives one destination
    # ref from the signed publication nonce. It performs no network read or write.
    from rsi_pilot_exact_task_remote_publication_target_attestation_contract import (
        run_contract as run_remote_publication_target_attestation_contract,
    )
    # ADR-DC-050 performs one bounded read-only observation of the exact pinned
    # destination and only accepts an absent ref. It grants no remote-write authority.
    from rsi_pilot_exact_task_remote_publication_state_observation_contract import (
        run_contract as run_remote_publication_state_observation_contract,
    )
    # ADR-DC-051 freshly re-observes the absent destination then durably burns the
    # signed publication nonce. The reserved slot still grants no push authority.
    from rsi_pilot_exact_task_remote_publication_write_reservation_contract import (
        run_contract as run_remote_publication_write_reservation_contract,
    )
    # ADR-DC-052 host-pins a verified credential broker without loading a secret
    # or granting push authority. The exact remote transaction remains later.
    from rsi_pilot_exact_task_remote_publication_credential_capability_contract import (
        run_contract as run_remote_publication_credential_capability_contract,
    )

    run_execution_plan_requirements_contract()
    run_development_task_binding_contract()
    run_development_task_binding_live_provenance_contract()
    run_executor_capability_live_guard_contract()
    run_executor_secret_custody_contract()
    run_executor_capability_semantics_contract()
    run_execution_plan_contract()
    run_prelaunch_reservation_contract()
    run_execution_transaction_contract()
    run_post_execution_evaluation_contract()
    run_local_commit_plan_contract()
    run_local_commit_object_identity_contract()
    run_local_commit_write_requirements_contract()
    run_local_commit_authorization_contract()
    run_local_commit_write_reservation_contract()
    run_local_commit_write_transaction_contract()
    run_local_commit_publication_requirements_contract()
    run_remote_publication_authorization_contract()
    run_remote_publication_target_attestation_contract()
    run_remote_publication_state_observation_contract()
    run_remote_publication_write_reservation_contract()
    run_remote_publication_credential_capability_contract()


if __name__ == "__main__":
    run_contract()
