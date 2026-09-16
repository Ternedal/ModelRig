"""Locked Stage-B wrapper for ADR-DC-067 through ADR-DC-089."""
from __future__ import annotations

from rsi_pilot_exact_task_release_transaction_contract_base import (
    _ledger,
    _live_authority,
    run_contract as run_release_transaction_contract,
)


def run_contract() -> None:
    run_release_transaction_contract()
    from rsi_pilot_exact_task_release_recovery_contract import (
        run_contract as run_release_recovery_contract,
    )

    run_release_recovery_contract()
    from rsi_pilot_exact_task_post_release_attestation_contract import (
        run_contract as run_post_release_attestation_contract,
    )

    run_post_release_attestation_contract()
    from rsi_pilot_exact_task_deploy_readiness_evaluation_contract import (
        run_contract as run_deploy_readiness_evaluation_contract,
    )

    run_deploy_readiness_evaluation_contract()
    from rsi_pilot_exact_task_staging_deployment_plan_contract import (
        run_contract as run_staging_deployment_plan_contract,
    )

    run_staging_deployment_plan_contract()
    from rsi_pilot_exact_task_staging_deployment_state_observation_contract import (
        run_contract as run_staging_deployment_state_observation_contract,
    )

    run_staging_deployment_state_observation_contract()
    from rsi_pilot_exact_task_staging_deployment_authorization_contract import (
        run_contract as run_staging_deployment_authorization_contract,
    )

    run_staging_deployment_authorization_contract()
    from rsi_pilot_exact_task_staging_deployment_transaction_contract import (
        run_contract as run_staging_deployment_transaction_contract,
    )

    run_staging_deployment_transaction_contract()
    from rsi_pilot_exact_task_staging_deployment_recovery_contract import (
        run_contract as run_staging_deployment_recovery_contract,
    )

    run_staging_deployment_recovery_contract()
    from rsi_pilot_exact_task_post_staging_deployment_attestation_contract import (
        run_contract as run_post_staging_deployment_attestation_contract,
    )

    run_post_staging_deployment_attestation_contract()
    from rsi_pilot_exact_task_staging_deployment_status_plan_contract import (
        run_contract as run_staging_deployment_status_plan_contract,
    )

    run_staging_deployment_status_plan_contract()
    from rsi_pilot_exact_task_staging_deployment_status_state_observation_contract import (
        run_contract as run_staging_deployment_status_state_observation_contract,
    )

    run_staging_deployment_status_state_observation_contract()
    from rsi_pilot_exact_task_staging_deployment_status_authorization_contract import (
        run_contract as run_staging_deployment_status_authorization_contract,
    )

    run_staging_deployment_status_authorization_contract()
    from rsi_pilot_exact_task_staging_deployment_status_transaction_contract import (
        run_contract as run_staging_deployment_status_transaction_contract,
    )

    run_staging_deployment_status_transaction_contract()
    from rsi_pilot_exact_task_staging_deployment_status_recovery_contract import (
        run_contract as run_staging_deployment_status_recovery_contract,
    )

    run_staging_deployment_status_recovery_contract()
    from rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract import (
        run_contract as run_post_staging_deployment_status_attestation_contract,
    )

    run_post_staging_deployment_status_attestation_contract()
    from rsi_pilot_exact_task_staging_runtime_verification_contract import (
        run_contract as run_staging_runtime_verification_contract,
    )

    run_staging_runtime_verification_contract()
    from rsi_pilot_exact_task_staging_runtime_build_identity_contract import (
        run_contract as run_staging_runtime_build_identity_contract,
    )

    run_staging_runtime_build_identity_contract()
    from rsi_pilot_exact_task_staging_success_status_plan_contract import (
        run_contract as run_staging_success_status_plan_contract,
    )

    run_staging_success_status_plan_contract()
    from rsi_pilot_exact_task_staging_success_status_state_observation_contract import (
        run_contract as run_staging_success_status_state_observation_contract,
    )

    run_staging_success_status_state_observation_contract()
    from rsi_pilot_exact_task_staging_success_status_authorization_contract import (
        run_contract as run_staging_success_status_authorization_contract,
    )

    run_staging_success_status_authorization_contract()
    from rsi_pilot_exact_task_staging_success_status_transaction_contract import (
        run_contract as run_staging_success_status_transaction_contract,
    )

    run_staging_success_status_transaction_contract()
    from rsi_pilot_exact_task_staging_success_status_recovery_contract import (
        run_contract as run_staging_success_status_recovery_contract,
    )

    run_staging_success_status_recovery_contract()


if __name__ == "__main__":
    run_contract()
