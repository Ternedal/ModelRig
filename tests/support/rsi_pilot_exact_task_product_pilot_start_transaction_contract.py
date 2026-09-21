"""Adversarial contract for ADR-DC-102 one-shot product-pilot start."""
from __future__ import annotations

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

from source_code import code_of  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_authorization as start_auth  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_start_transaction as start_tx  # noqa: E402
import rsi_pilot_exact_task_product_pilot_start_authorization_contract as auth_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-start-transaction-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_start_transaction.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-102 unexpectedly accepted unsafe product-pilot start")


def _authorization(fixture):
    _fixture, ready, _owns = auth_contract._ready(fixture)
    config = auth_contract._config(ready)
    payload = auth_contract._payload(ready, config)
    verifier, op_sig, review_sig = auth_contract._dual(payload)
    temp, ledger = auth_contract._ledger("rsi-product-start-tx-auth-")
    receipt = auth_contract._authorize(
        ready,
        config,
        payload,
        verifier,
        op_sig,
        review_sig,
        ledger,
    )
    assert receipt.authorization_authenticated is True
    return temp, receipt, ready


def _ledger(prefix):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, start_tx._PilotExactTaskProductPilotStartTransactionLedger(root)


def _execute(authorization, ledger, moments=None):
    if moments is None:
        moments = iter(("2026-09-15T09:54:50Z", "2026-09-15T09:54:51Z"))
    return start_tx._execute_verified_pilot_exact_task_product_pilot_start(
        authorization_receipt=authorization,
        ledger=ledger,
        now_provider=moments.__next__,
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    auth_temp = None
    try:
        auth_temp, authorization, ready = _authorization(fixture)

        temp, ledger = _ledger("rsi-product-start-tx-")
        try:
            receipt = _execute(authorization, ledger)
            assert receipt.transaction_authenticated is True
            assert receipt.product_pilot_start_authorization_sha256 == authorization.sha256
            assert receipt.product_pilot_start_readiness_sha256 == ready.sha256
            assert (
                receipt.product_pilot_start_requirements_sha256
                == ready.product_pilot_start_requirements_sha256
            )
            assert (
                receipt.product_pilot_lineage_attestation_sha256
                == ready.product_pilot_lineage_attestation_sha256
            )
            assert (
                receipt.product_pilot_task_registry_receipt_sha256
                == ready.product_pilot_task_registry_receipt_sha256
            )
            assert (
                receipt.product_pilot_runtime_preflight_receipt_sha256
                == ready.product_pilot_runtime_preflight_receipt_sha256
            )
            assert receipt.fresh_human_decision_proof_sha256 == ready.fresh_human_decision_proof_sha256
            assert receipt.development_task_sha256 == ready.development_task_sha256
            assert receipt.fixed_command_id == ready.fixed_command_id
            assert receipt.host_start_transaction_guard_committed is True
            assert receipt.product_pilot_start_authorization_authenticated is True
            assert receipt.readiness_v2_authenticated is True
            assert receipt.task_registry_ready is True
            assert receipt.runtime_preflight_satisfied is True
            assert receipt.one_shot_start_consumed is True
            assert receipt.start_receipt_issued is True
            assert receipt.product_pilot_start_authorized is True
            assert receipt.product_pilot_started is True
            assert receipt.task_execution_authorized is False
            assert receipt.local_commit_authorized is False
            assert receipt.remote_write_authorized is False
            assert receipt.push_authorized is False
            assert receipt.pr_mutation_authorized is False
            assert receipt.merge_authorized is False
            assert receipt.release_authorized is False
            assert receipt.deploy_authorized is False
            assert receipt.production_activation_authorized is False
            assert receipt.nonce_reusable is False
            assert receipt.next_boundary_execution_authorization_required is True

            serialized = start_tx.PilotExactTaskProductPilotStartTransactionReceipt.from_mapping(
                receipt.to_dict()
            )
            assert serialized == receipt
            assert serialized.transaction_authenticated is False

            _reject(lambda: _execute(authorization, ledger))
        finally:
            temp.cleanup()

        replayed_auth = (
            start_auth.PilotExactTaskProductPilotStartAuthorizationReceipt.from_mapping(
                authorization.to_dict()
            )
        )
        assert replayed_auth.authorization_authenticated is False
        replay_temp, replay_ledger = _ledger("rsi-product-start-tx-replay-")
        try:
            _reject(lambda: _execute(replayed_auth, replay_ledger))
            assert tuple(replay_ledger.root.iterdir()) == ()
        finally:
            replay_temp.cleanup()

        stale_temp, stale_ledger = _ledger("rsi-product-start-tx-stale-")
        try:
            _reject(
                lambda: _execute(
                    authorization,
                    stale_ledger,
                    iter(("2026-09-15T09:58:42Z",)),
                )
            )
            assert tuple(stale_ledger.root.iterdir()) == ()
        finally:
            stale_temp.cleanup()

        race_temp, race_ledger = _ledger("rsi-product-start-tx-race-")
        try:
            moments = iter(("2026-09-15T09:58:40Z", "2026-09-15T09:58:42Z"))
            _reject(lambda: _execute(authorization, race_ledger, moments))
            key = start_tx._transaction_key(authorization)
            final_path, lock_path = race_ledger._paths(key)
            assert lock_path.exists()
            assert not final_path.exists()
        finally:
            race_temp.cleanup()

        field_temp, field_ledger = _ledger("rsi-product-start-tx-fields-")
        try:
            receipt = _execute(authorization, field_ledger)
            for field in (
                "task_execution_authorized",
                "local_commit_authorized",
                "remote_write_authorized",
                "push_authorized",
                "pr_mutation_authorized",
                "merge_authorized",
                "release_authorized",
                "deploy_authorized",
                "production_activation_authorized",
                "nonce_reusable",
            ):
                raw = receipt.to_dict()
                raw[field] = True
                _reject(
                    lambda raw=raw: start_tx.PilotExactTaskProductPilotStartTransactionReceipt.from_mapping(
                        raw
                    )
                )
            for field in (
                "host_start_transaction_guard_committed",
                "product_pilot_start_authorization_authenticated",
                "readiness_v2_authenticated",
                "task_registry_ready",
                "runtime_preflight_satisfied",
                "one_shot_start_consumed",
                "start_receipt_issued",
                "product_pilot_start_authorized",
                "product_pilot_started",
                "next_boundary_execution_authorization_required",
            ):
                raw = receipt.to_dict()
                raw[field] = False
                _reject(
                    lambda raw=raw: start_tx.PilotExactTaskProductPilotStartTransactionReceipt.from_mapping(
                        raw
                    )
                )
        finally:
            field_temp.cleanup()
    finally:
        if auth_temp is not None:
            auth_temp.cleanup()
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        start_tx.PilotExactTaskProductPilotStartTransactionReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        start_tx.execute_pilot_exact_task_product_pilot_start
    )
    assert tuple(public.parameters) == ("authorization_receipt",)

    source = code_of(SOURCE).lower()
    for forbidden in (
        "subprocess.",
        "urllib.",
        "requests.",
        "http.client",
        "socket.",
        "git push",
        "merge_pull_request",
        "production_activation_promote",
    ):
        assert forbidden not in source


if __name__ == "__main__":
    run_contract()
