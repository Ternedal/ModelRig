"""Adversarial contract for ADR-DC-098 inert product-pilot lineage attestation."""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from source_code import code_of  # noqa: E402

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_execution_admission as execution_admission,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_execution_revalidation_attestation as execution_revalidation,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_start_consumption as start_consumption,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_runtime_build_identity as build_identity,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_product_pilot_lineage_attestation as lineage,
)
from kaliv_dev_control import (  # noqa: E402
    _improvement_pilot_exact_task_product_pilot_lineage_attestation_production_boundary as lineage_boundary,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_production_activation_readiness as production_readiness,
)
import rsi_pilot_exact_task_execution_admission_contract as execution_admission_contract  # noqa: E402
import rsi_pilot_exact_task_staging_runtime_build_identity_contract as build_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_plan_contract as success_plan_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_state_observation_contract as success_state_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_authorization_contract as success_auth_contract  # noqa: E402
import rsi_pilot_exact_task_staging_success_status_transaction_contract as success_tx_contract  # noqa: E402
import rsi_pilot_exact_task_post_staging_success_status_attestation_contract as post_success_contract  # noqa: E402
import rsi_pilot_exact_task_production_activation_readiness_contract as production_ready_contract  # noqa: E402
import rsi_pilot_exact_task_production_activation_authorization_contract as production_auth_contract  # noqa: E402
import rsi_pilot_exact_task_production_activation_transaction_contract as production_tx_contract  # noqa: E402
import rsi_pilot_exact_task_post_production_activation_attestation_contract as post_production_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-lineage-attestation-v1.schema.json"
)
IMPL = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "_improvement_pilot_exact_task_product_pilot_lineage_attestation_impl.py"
)
BOUNDARY = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "_improvement_pilot_exact_task_product_pilot_lineage_attestation_production_boundary.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-098 unexpectedly accepted broken lineage")


def _find_exact(value, cls, seen=None):
    if type(value) is cls:
        return value
    if seen is None:
        seen = set()
    marker = id(value)
    if marker in seen:
        return None
    seen.add(marker)
    if isinstance(value, dict):
        items = value.values()
    elif isinstance(value, (tuple, list)):
        items = value
    else:
        return None
    for item in items:
        found = _find_exact(item, cls, seen)
        if found is not None:
            return found
    return None


def _find_ledger_root(value, filename: str, seen=None):
    if seen is None:
        seen = set()
    marker = id(value)
    if marker in seen:
        return None
    seen.add(marker)
    name = getattr(value, "name", None)
    if isinstance(name, str):
        base = Path(name)
        for root in (base, base / "ledger"):
            if (root / filename).is_file():
                return root
    if isinstance(value, dict):
        items = value.values()
    elif isinstance(value, (tuple, list)):
        items = value
    else:
        return None
    for item in items:
        found = _find_ledger_root(item, filename, seen)
        if found is not None:
            return found
    return None


def _fresh_execution_admission():
    """Build one live ADR-DC-033 receipt from the Stage-B cache when available."""
    source_temp = None
    cache_raw = os.environ.get("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE", "").strip()
    if cache_raw:
        cache_path = Path(cache_raw)
        if (
            not cache_path.is_absolute()
            or cache_path.is_symlink()
            or not cache_path.is_file()
        ):
            raise AssertionError("Stage-B admission proof cache is unsafe")
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if set(payload) != {"proof", "fresh"}:
            raise AssertionError("Stage-B admission proof cache shape is invalid")
        proof = (
            execution_revalidation.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
                payload["proof"]
            )
        )
        fresh = (
            execution_revalidation.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
                payload["fresh"]
            )
        )
    else:
        source_temp, proof, fresh, *_ = execution_admission_contract._proof()

    ledger_temp, ledger = execution_admission_contract._ledger(
        "rsi-lineage-execution-admission-"
    )
    times = iter(("2026-09-14T08:36:20Z", "2026-09-14T08:36:21Z"))
    receipt = execution_admission._admit_verified_exact_task_execution(
        supplied_proof=proof,
        fresh_proof=fresh,
        ledger=ledger,
        now_provider=lambda: next(times),
    )
    assert receipt.transaction_authenticated is True
    return source_temp, ledger_temp, ledger.root, receipt


def _build_fixture():
    bundle, _runtime_config, _credential, _path, runtime_verification = (
        build_contract._runtime_receipt()
    )
    runtime = build_contract._verify(
        runtime_verification,
        build_contract._BuildProbe(runtime_verification),
    )
    assert runtime.verification_authenticated is True

    (
        execution_source_temp,
        execution_ledger_temp,
        execution_root,
        execution,
    ) = _fresh_execution_admission()
    assert execution.execution_nonce_sha256 == runtime.execution_nonce_sha256
    historical = lineage._historical_chain(execution)
    start_receipt = historical["start_receipt"]
    assert start_receipt.sha256 == execution.start_receipt_sha256

    start_filename = f"{start_receipt.start_nonce_sha256}.json"
    start_root = _find_ledger_root(bundle, start_filename)
    if start_root is None and execution_source_temp is not None:
        start_root = _find_ledger_root(execution_source_temp, start_filename)
    if start_root is None:
        shared_start_root = os.environ.get("MODELRIG_STAGE_B_START_LEDGER_ROOT")
        if shared_start_root:
            candidate = Path(shared_start_root)
            if (
                candidate.is_absolute()
                and candidate.is_dir()
                and not candidate.is_symlink()
                and (candidate / start_filename).is_file()
            ):
                start_root = candidate.resolve()
    assert execution_root is not None
    assert start_root is not None
    with (
        patch.object(
            lineage_boundary,
            "_canonical_execution_ledger_root",
            return_value=execution_root,
        ),
        patch.object(
            lineage_boundary,
            "_canonical_start_ledger_root",
            return_value=start_root,
        ),
    ):
        durable_execution = lineage_boundary._load_execution_receipt(
            historical["revalidation"]
        )
        assert durable_execution == execution
        durable_start = lineage_boundary._load_start_receipt(
            lineage_boundary._nested_start_receipt(durable_execution)
        )
        assert durable_start == start_receipt

    success_plan = success_plan_contract._plan(runtime)
    success_observation = success_state_contract._observe(
        success_plan,
        success_state_contract._Transport(success_plan),
    )

    success_auth_temp, success_auth_ledger = success_auth_contract._ledger(
        "rsi-lineage-success-auth-"
    )
    success_config = success_auth_contract._config(success_observation)
    success_payload = success_auth_contract._payload(
        success_observation, success_config
    )
    success_verifier, success_op, success_review = (
        success_auth_contract._dual_authority(success_payload)
    )
    success_authorization = success_auth_contract._authorize(
        success_observation,
        success_config,
        success_payload,
        success_verifier,
        success_op,
        success_review,
        success_auth_ledger,
        success_state_contract._Transport(success_plan),
    )

    success_tx_temp, success_tx_ledger = success_tx_contract._ledger(
        "rsi-lineage-success-tx-"
    )
    status_id = success_authorization.current_deployment_status_id + 1
    success_transaction = success_tx_contract._execute(
        success_authorization,
        success_tx_ledger,
        success_tx_contract._observer(success_plan, status_id=status_id),
        success_tx_contract._Writer(
            success_authorization, status_id=status_id
        ),
    )
    assert success_transaction.transaction_authenticated is True

    post_success_recovery_temp, post_success_recovery_root = (
        post_success_contract._empty_recovery_ledger(
            "rsi-lineage-post-success-recovery-"
        )
    )
    post_success = post_success_contract._attest(
        success_authorization,
        tx_root=success_tx_ledger.root,
        recovery_root=post_success_recovery_root,
        auth_root=Path(success_auth_temp.name) / "ledger",
        transport=post_success_contract.recovery_contract._Transport(
            success_authorization,
            states=[post_success_contract._normal_state(success_authorization)],
        ),
    )
    assert post_success.attestation_authenticated is True

    production_ready = production_ready_contract._evaluate(
        post_success,
        production_ready_contract._policy(post_success),
    )
    assert production_ready.evaluation_authenticated is True
    assert production_ready.staging_runtime_build_identity_sha256 == runtime.sha256

    production_temp = tempfile.TemporaryDirectory(prefix="rsi-lineage-production-")
    root = Path(production_temp.name)
    promotion = root / "promotion"
    scripts = promotion / "scripts"
    scripts.mkdir(parents=True)
    gate = scripts / "production_activation_gate.py"
    controller = scripts / "production_activation_promote.ps1"
    gate.write_text("# gate fixture\n", encoding="utf-8")
    controller.write_text("# controller fixture\n", encoding="utf-8")
    powershell = root / "powershell.exe"
    powershell.write_bytes(b"fixture-powershell")

    production_config = production_auth_contract._config(
        production_ready,
        promotion_gate_sha256=production_tx_contract._sha(gate),
        promotion_controller_sha256=production_tx_contract._sha(controller),
    )
    production_payload = production_auth_contract._payload(
        production_ready, production_config
    )
    production_verifier, production_op, production_review = (
        production_auth_contract._dual(production_payload)
    )
    production_auth_temp, production_auth_ledger = production_auth_contract._ledger(
        "rsi-lineage-production-auth-"
    )
    production_authorization = production_auth_contract._authorize(
        production_ready,
        production_config,
        production_payload,
        production_verifier,
        production_op,
        production_review,
        production_auth_ledger,
    )
    assert production_authorization.authorization_authenticated is True

    appliance = root / "appliance"
    appliance.mkdir()
    (appliance / "modelrig.env").write_text(
        "MODELRIG_HOST=0.0.0.0\n"
        "KALIV_AGENT3_ENABLED=0\n"
        "KALIV_TOOLS_ENABLED=0\n"
        "KALIV_SCHEDULER=0\n"
        "KALIV_SCHEDULER_API=0\n",
        encoding="utf-8",
    )
    agent = root / "agent3.json"
    agent.write_text("{}\n", encoding="utf-8")
    output_root = root / "output"
    output_root.mkdir()
    bodyrig = root / "bodyrig"
    bodyrig.mkdir()
    (bodyrig / "live-automatic-final-receipt.json").write_text(
        json.dumps(
            {
                "schema": production_tx_contract.tx.BODYRIG_FINAL_SCHEMA,
                "production_activation": False,
                "candidate_git_sha": production_authorization.merge_commit_sha,
                "body_id": production_tx_contract.BODY_ID,
                "package_sha256": production_tx_contract.PACKAGE,
                "machine_live_proof": True,
                "machine_quality": True,
                "product_exercise": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    transaction_config = (
        production_tx_contract.tx.PilotExactTaskProductionActivationTransactionConfig(
            repository=production_authorization.repository,
            repository_id=production_authorization.repository_id,
            promotion_repo_root=str(promotion.resolve()),
            appliance_dir=str(appliance.resolve()),
            agent3_report_path=str(agent.resolve()),
            output_root=str(output_root.resolve()),
            powershell_path=str(powershell.resolve()),
            powershell_sha256=production_tx_contract._sha(powershell),
        )
    )
    production_ledger_root = root / "production-ledger"
    production_ledger_root.mkdir()
    production_ledger = (
        production_tx_contract.tx._PilotExactTaskProductionActivationTransactionLedger(
            production_ledger_root
        )
    )
    production_fixture = {
        "authorization": production_authorization,
        "config": transaction_config,
        "ledger": production_ledger,
        "executor": production_tx_contract._FakeExecutor(
            production_authorization, transaction_config
        ),
        "bodyrig": bodyrig,
        "root": root,
    }
    production_transaction = production_tx_contract._execute(production_fixture)
    production_tx_contract._assert_consumed(production_transaction)
    production_recovery_ledger = (
        post_production_contract._empty_recovery_ledger(production_fixture)
    )
    post_production = post_production_contract._attest(
        production_fixture, production_recovery_ledger
    )
    assert post_production.attestation_authenticated is True
    assert (
        post_production.production_activation_candidate_sha256
        == production_ready.production_activation_candidate_sha256
    )

    return {
        "bundle": bundle,
        "runtime_verification": runtime_verification,
        "runtime": runtime,
        "execution": execution,
        "execution_source_temp": execution_source_temp,
        "execution_ledger_temp": execution_ledger_temp,
        "historical": historical,
        "start_receipt": start_receipt,
        "success_auth_temp": success_auth_temp,
        "success_tx_temp": success_tx_temp,
        "post_success_recovery_temp": post_success_recovery_temp,
        "production_auth_temp": production_auth_temp,
        "production_temp": production_temp,
        "production_ready": production_ready,
        "post_production": post_production,
    }


def _cleanup(value) -> None:
    value["production_auth_temp"].cleanup()
    value["production_temp"].cleanup()
    value["post_success_recovery_temp"].cleanup()
    value["success_tx_temp"].cleanup()
    value["success_auth_temp"].cleanup()
    value["execution_ledger_temp"].cleanup()
    if value["execution_source_temp"] is not None:
        value["execution_source_temp"].cleanup()
    build_contract.runtime_contract._cleanup(value["bundle"])


def _attest(value, **overrides):
    historical = value["historical"]
    candidate = historical["candidate"]
    inputs = {
        "verified_human_decision_proof_sha256": candidate.decision_proof_sha256,
        "verified_human_selection_proof_sha256": historical["selection"].sha256,
        "verified_preflight_proof_sha256": historical["preflight"].sha256,
        "durable_start_receipt": start_consumption.PilotStartConsumptionReceipt.from_mapping(
            value["start_receipt"].to_dict()
        ),
        "verified_execution_revalidation_proof_sha256": historical[
            "revalidation"
        ].sha256,
        "durable_execution_admission_receipt": (
            execution_admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
                value["execution"].to_dict()
            )
        ),
        "staging_runtime_build_identity": value["runtime"],
        "production_activation_readiness": value["production_ready"],
        "post_production_activation_attestation": value["post_production"],
        "now_provider": lambda: "2026-09-15T09:54:02Z",
    }
    inputs.update(overrides)
    return lineage._attest_verified_pilot_exact_task_product_pilot_lineage(
        **inputs
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = _build_fixture() if owns_fixture else shared_fixture
    try:
        historical = fixture["historical"]
        candidate = historical["candidate"]
        receipt = _attest(fixture)
        assert receipt.attestation_authenticated is True
        live_inputs = lineage._get_live_product_pilot_lineage_inputs(receipt)
        assert live_inputs is not None
        assert live_inputs["candidate"] is candidate
        assert live_inputs["preflight"] is historical["preflight"]

        assert (
            receipt.schema
            == lineage.PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCHEMA
        )
        assert (
            receipt.authority
            == lineage.PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_AUTHORITY
        )
        assert (
            receipt.attestation_scope
            == lineage.PILOT_EXACT_TASK_PRODUCT_PILOT_LINEAGE_ATTESTATION_SCOPE
        )
        assert receipt.human_decision_proof_sha256 == candidate.decision_proof_sha256
        assert receipt.human_selection_proof_sha256 == historical["selection"].sha256
        assert receipt.preflight_proof_sha256 == historical["preflight"].sha256
        assert receipt.start_receipt_sha256 == fixture["start_receipt"].sha256
        assert (
            receipt.execution_revalidation_proof_sha256
            == historical["revalidation"].sha256
        )
        assert receipt.execution_admission_receipt_sha256 == fixture["execution"].sha256
        assert receipt.execution_nonce_sha256 == fixture["runtime"].execution_nonce_sha256
        assert (
            receipt.staging_runtime_build_identity_sha256
            == fixture["runtime"].sha256
        )
        assert (
            receipt.production_activation_readiness_sha256
            == fixture["production_ready"].sha256
        )
        assert (
            receipt.production_activation_candidate_sha256
            == fixture["production_ready"].production_activation_candidate_sha256
        )
        assert (
            receipt.post_production_activation_attestation_sha256
            == fixture["post_production"].sha256
        )
        assert receipt.repository == candidate.repository
        assert receipt.operator_surface == candidate.operator_surface
        assert receipt.selected_pilot_task_id == candidate.selected_pilot_task_id
        assert receipt.workspace_root_path_sha256 == candidate.workspace_root_path_sha256
        assert receipt.feature_flag_name == candidate.feature_flag_name
        assert receipt.product_route == candidate.product_route
        assert receipt.historical_human_go_verified is True
        assert receipt.historical_human_selection_verified is True
        assert receipt.historical_preflight_verified is True
        assert receipt.durable_start_consumption_verified is True
        assert receipt.historical_execution_revalidation_verified is True
        assert receipt.durable_execution_admission_verified is True
        assert receipt.execution_nonce_runtime_binding_verified is True
        assert receipt.runtime_production_candidate_binding_verified is True
        assert receipt.live_post_production_activation_verified is True

        for field in (
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
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
            assert getattr(receipt, field) is False
            raw = receipt.to_dict()
            raw[field] = True
            _reject(
                lambda raw=raw: (
                    lineage.PilotExactTaskProductPilotLineageAttestationReceipt.from_mapping(
                        raw
                    )
                )
            )

        serialized = (
            lineage.PilotExactTaskProductPilotLineageAttestationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.sha256 == receipt.sha256
        assert serialized.attestation_authenticated is False
        assert lineage._get_live_product_pilot_lineage_inputs(serialized) is None

        wrong = "f" * 64
        if wrong == candidate.decision_proof_sha256:
            wrong = "e" * 64
        _reject(
            lambda: _attest(
                fixture,
                verified_human_decision_proof_sha256=wrong,
            )
        )
        wrong_revalidation = "f" * 64
        if wrong_revalidation == historical["revalidation"].sha256:
            wrong_revalidation = "e" * 64
        _reject(
            lambda: _attest(
                fixture,
                verified_execution_revalidation_proof_sha256=wrong_revalidation,
            )
        )

        stale_runtime = (
            build_identity.PilotExactTaskStagingRuntimeBuildIdentityReceipt.from_mapping(
                fixture["runtime"].to_dict()
            )
        )
        assert stale_runtime.verification_authenticated is False
        _reject(
            lambda: _attest(
                fixture,
                staging_runtime_build_identity=stale_runtime,
            )
        )

        stale_ready = (
            production_readiness.PilotExactTaskProductionActivationReadinessReceipt.from_mapping(
                fixture["production_ready"].to_dict()
            )
        )
        assert stale_ready.evaluation_authenticated is False
        _reject(
            lambda: _attest(
                fixture,
                production_activation_readiness=stale_ready,
            )
        )

        stale_post = (
            post_production_contract.attestation.PilotExactTaskPostProductionActivationAttestationReceipt.from_mapping(
                fixture["post_production"].to_dict()
            )
        )
        assert stale_post.attestation_authenticated is False
        _reject(
            lambda: _attest(
                fixture,
                post_production_activation_attestation=stale_post,
            )
        )

        _reject(
            lambda: _attest(
                fixture,
                now_provider=lambda: "2026-09-15T09:53:59Z",
            )
        )
    finally:
        if owns_fixture:
            _cleanup(fixture)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(
        lineage.PilotExactTaskProductPilotLineageAttestationReceipt.__dataclass_fields__
    )
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields
    assert schema["additionalProperties"] is False

    public = inspect.signature(
        lineage.attest_pilot_exact_task_product_pilot_lineage
    )
    assert tuple(public.parameters) == (
        "human_decision_proof",
        "completion_proof",
        "human_decision_signature",
        "human_selection_signature",
        "preflight_signature",
        "start_authorization_signature",
        "admission_attestation_signature",
        "execution_authorization_signature",
        "execution_revalidation_proof",
        "revalidation_attestation_signature",
        "staging_runtime_build_identity",
        "production_activation_readiness",
        "post_production_activation_attestation",
    )

    impl_source = code_of(IMPL)
    boundary_source = code_of(BOUNDARY)
    for source in (impl_source, boundary_source):
        for forbidden in (
            "subprocess.",
            "urllib.",
            "requests.",
            "http.client",
            "create_once_file",
            ".write_text(",
            ".write_bytes(",
            ".unlink(",
            ".rename(",
        ):
            assert forbidden not in source
    assert "product_pilot_start_ready: bool = False" in impl_source
    assert "product_pilot_start_authorized: bool = False" in impl_source
    assert "product_pilot_started: bool = False" in impl_source
    assert "_canonical_execution_ledger_root" in boundary_source
    assert "_canonical_start_ledger_root" in boundary_source


if __name__ == "__main__":
    run_contract()
