"""Adversarial contract for ADR-DC-093 production activation transaction."""
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
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_production_activation_transaction as tx  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_production_activation_authorization as activation_auth  # noqa: E402
import rsi_pilot_exact_task_production_activation_authorization_contract as auth_contract  # noqa: E402
import rsi_pilot_exact_task_production_activation_readiness_contract as readiness_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-production-activation-transaction-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_production_activation_transaction.py"

PROMOTION = "c" * 40
MAIN = "d" * 40
WORKER = "e" * 64
PACKAGE = "f" * 64
BODY_ID = "body-adr-dc-093"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-093 unexpectedly accepted unsafe production activation transaction")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ready(recovered: bool):
    if not recovered:
        upstream, ready = auth_contract._ready_from_normal()
        return ("normal", upstream), ready
    upstream = readiness_contract._recovered_source()
    source = upstream[-1]
    ready = readiness_contract._evaluate(source, readiness_contract._policy(source))
    assert ready.evaluation_authenticated is True
    assert ready.production_activation_ready is True
    return ("recovered", upstream), ready


def _cleanup_ready(value) -> None:
    kind, upstream = value
    if kind == "normal":
        readiness_contract._cleanup_normal(upstream)
    else:
        readiness_contract._cleanup_recovered(upstream)


class _FakeExecutor:
    def __init__(self, authorization, config, *, states=None, mode="success"):
        self.authorization = authorization
        self.config = config
        self.mode = mode
        self.observe_calls = 0
        self.run_calls = 0
        self._states = list(states or [])
        self._default_state = {
            "local_head_sha": PROMOTION,
            "remote_candidate_sha": authorization.merge_commit_sha,
            "remote_promotion_sha": PROMOTION,
            "changed_paths": sorted(
                [
                    "PRODUCTION_ACTIVATION.md",
                    activation_auth.PROMOTION_GATE_PATH,
                    activation_auth.PROMOTION_CONTROLLER_PATH,
                ]
            ),
            "working_tree_clean": True,
            "candidate_is_ancestor": True,
        }

    def observe(self, authorization, config):
        assert authorization is self.authorization
        assert config is self.config
        self.observe_calls += 1
        if self._states:
            return self._states.pop(0)
        return dict(self._default_state)

    def run(self, authorization, config, bodyrig_evidence_dir, output_dir):
        assert authorization is self.authorization
        assert config is self.config
        self.run_calls += 1
        if self.mode == "fail":
            return {
                "returncode": 1,
                "stdout_sha256": hashlib.sha256(b"failed").hexdigest(),
                "stderr_sha256": hashlib.sha256(b"controller failed").hexdigest(),
            }
        if self.mode == "missing":
            return {
                "returncode": 0,
                "stdout_sha256": hashlib.sha256(b"pass-ish").hexdigest(),
                "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            }

        output_dir.mkdir(parents=False, exist_ok=False)
        env_path = Path(config.appliance_dir) / "modelrig.env"
        env_before = hashlib.sha256(env_path.read_bytes()).hexdigest()
        body_sha = hashlib.sha256(
            (Path(bodyrig_evidence_dir) / "live-automatic-final-receipt.json").read_bytes()
        ).hexdigest()
        agent_sha = hashlib.sha256(Path(config.agent3_report_path).read_bytes()).hexdigest()
        changed = list(self._default_state["changed_paths"])

        preflight = {
            "schema": tx.MACHINE_PREFLIGHT_SCHEMA,
            "created_at": "2026-09-15T09:52:13+00:00",
            "production_activation": False,
            "candidate_git_sha": authorization.merge_commit_sha,
            "promotion_git_sha": PROMOTION,
            "origin_main_sha": MAIN,
            "version": "2.0.13",
            "worker_code_sha256": WORKER,
            "promotion_changed_paths": changed,
            "bodyrig": {
                "final_receipt_sha256": body_sha,
                "body_id": BODY_ID,
                "package_sha256": PACKAGE,
                "machine_live_proof": True,
                "machine_quality": True,
                "product_exercise": True,
            },
            "agent3": {
                "report_sha256": agent_sha,
                "write_pilot_eligible": True,
                "write_decision": "approve",
            },
            "environment": {"before_sha256": env_before},
        }
        preflight_path = output_dir / "production-activation-preflight.json"
        preflight_path.write_text(
            json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        preflight_sha = _sha(preflight_path)

        env_path.write_text(
            "MODELRIG_HOST=0.0.0.0\n"
            "KALIV_AGENT3_ENABLED=1\n"
            "KALIV_TOOLS_ENABLED=1\n"
            "KALIV_SCHEDULER=1\n"
            "KALIV_SCHEDULER_API=1\n"
            f"KALIV_AGENT3_VALIDATION_REPORT={Path(config.agent3_report_path).resolve()}\n"
            "KALIV_SCHEDULER_APPROVAL_SECRET=" + ("S" * 32) + "\n",
            encoding="utf-8",
        )
        env_after = _sha(env_path)
        final = {
            "schema": tx.MACHINE_FINAL_SCHEMA,
            "created_at": "2026-09-15T09:52:14+00:00",
            "production_activation": True,
            "scope": ["agent3", "tools", "scheduler", "scheduler_api"],
            "candidate_git_sha": authorization.merge_commit_sha,
            "promotion_git_sha": PROMOTION,
            "origin_main_sha": MAIN,
            "version": "2.0.13",
            "worker_code_sha256": WORKER,
            "bindings": {
                "preflight_sha256": preflight_sha,
                "bodyrig_final_receipt_sha256": body_sha,
                "agent3_report_sha256": agent_sha,
                "environment_before_sha256": env_before,
                "environment_after_sha256": env_after,
            },
            "bodyrig": {
                "body_id": BODY_ID,
                "package_sha256": PACKAGE,
                "machine_live_proof": True,
                "machine_quality": True,
                "product_exercise": True,
            },
            "agent3": {"write_pilot_eligible": True, "report_bound_live": True},
            "runtime": {name: True for name in tx._RUNTIME_TRUE_FIELDS},
            "switches": dict(activation_auth.REQUIRED_SWITCHES),
            "scheduler_approval_secret_present": True,
            "human_acceptance_required": False,
        }
        if self.mode == "wrong-candidate":
            final["candidate_git_sha"] = "1" * 40
        elif self.mode == "runtime-false":
            final["runtime"]["scheduler_running"] = False
        elif self.mode == "wrong-switch":
            final["switches"]["KALIV_SCHEDULER"] = "0"
        elif self.mode == "wrong-env-binding":
            final["bindings"]["environment_after_sha256"] = "9" * 64
        (output_dir / "production-activation.json").write_text(
            json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "returncode": 0,
            "stdout_sha256": hashlib.sha256(b"controller pass").hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        }


def _fixture(*, recovered=False):
    upstream, ready = _ready(recovered)
    temp = tempfile.TemporaryDirectory(prefix="rsi-production-activation-tx-")
    root = Path(temp.name)
    promotion = root / "promotion"
    scripts = promotion / "scripts"
    scripts.mkdir(parents=True)
    gate = scripts / "production_activation_gate.py"
    controller = scripts / "production_activation_promote.ps1"
    gate.write_text("# gate fixture\n", encoding="utf-8")
    controller.write_text("# controller fixture\n", encoding="utf-8")
    powershell = root / "powershell.exe"
    powershell.write_bytes(b"fixture-powershell")

    auth_config = auth_contract._config(
        ready,
        promotion_gate_sha256=_sha(gate),
        promotion_controller_sha256=_sha(controller),
    )
    auth_payload = auth_contract._payload(ready, auth_config)
    verifier, op_sig, review_sig = auth_contract._dual(auth_payload)
    auth_temp, auth_ledger = auth_contract._ledger("rsi-production-activation-tx-auth-")
    authorization = auth_contract._authorize(
        ready,
        auth_config,
        auth_payload,
        verifier,
        op_sig,
        review_sig,
        auth_ledger,
    )
    assert authorization.authorization_authenticated is True

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
                "schema": tx.BODYRIG_FINAL_SCHEMA,
                "production_activation": False,
                "candidate_git_sha": authorization.merge_commit_sha,
                "body_id": BODY_ID,
                "package_sha256": PACKAGE,
                "machine_live_proof": True,
                "machine_quality": True,
                "product_exercise": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    config = tx.PilotExactTaskProductionActivationTransactionConfig(
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        promotion_repo_root=str(promotion.resolve()),
        appliance_dir=str(appliance.resolve()),
        agent3_report_path=str(agent.resolve()),
        output_root=str(output_root.resolve()),
        powershell_path=str(powershell.resolve()),
        powershell_sha256=_sha(powershell),
    )
    ledger_root = root / "ledger"
    ledger_root.mkdir()
    ledger = tx._PilotExactTaskProductionActivationTransactionLedger(ledger_root)
    executor = _FakeExecutor(authorization, config)
    return {
        "upstream": upstream,
        "temp": temp,
        "auth_temp": auth_temp,
        "authorization": authorization,
        "ready": ready,
        "config": config,
        "ledger": ledger,
        "executor": executor,
        "bodyrig": bodyrig,
        "root": root,
    }


def _cleanup(value):
    value["auth_temp"].cleanup()
    value["temp"].cleanup()
    _cleanup_ready(value["upstream"])


def _execute(value, *, executor=None, moments=None):
    if executor is None:
        executor = value["executor"]
    if moments is None:
        moments = iter(
            (
                "2026-09-15T09:52:11Z",
                "2026-09-15T09:52:12Z",
                "2026-09-15T09:52:13Z",
                "2026-09-15T09:52:15Z",
            )
        )
    return tx._execute_verified_pilot_exact_task_production_activation(
        production_activation_authorization=value["authorization"],
        transaction_config=value["config"],
        transaction_ledger=value["ledger"],
        bodyrig_evidence_dir=value["bodyrig"],
        executor=executor,
        now_provider=lambda: next(moments),
    )


def _assert_consumed(receipt):
    assert receipt.transaction_authenticated is True
    assert receipt.production_activation is True
    assert receipt.production_activation_completed is True
    assert receipt.production_activation_authority_consumed is True
    assert receipt.controller_executed_once is True
    assert receipt.controller_exit_success is True
    assert receipt.production_machine_receipt_verified is True
    assert receipt.production_env_mutation_performed is True
    assert receipt.appliance_restart_performed is True
    assert receipt.production_receipt_write_performed is True
    assert receipt.recovery_required is False
    assert receipt.production_activation_authorized is False
    assert receipt.promotion_gate_execution_authorized is False
    assert receipt.production_env_mutation_authorized is False
    assert receipt.appliance_restart_authorized is False
    assert receipt.production_receipt_write_authorized is False
    assert receipt.remote_write_authorized is False
    assert receipt.deploy_authorized is False
    assert receipt.release_authorized is False
    assert receipt.merge_authorized is False
    assert receipt.product_pilot_started is False
    assert receipt.nonce_reusable is False


def run_contract() -> None:
    if os.name == "nt":
        return

    fixture = _fixture()
    try:
        receipt = _execute(fixture)
        _assert_consumed(receipt)
        executor = fixture["executor"]
        assert executor.observe_calls == 2
        assert executor.run_calls == 1
        assert receipt.production_activation_authorization_sha256 == fixture["authorization"].sha256
        assert receipt.production_activation_candidate_sha256 == fixture["authorization"].production_activation_candidate_sha256
        assert receipt.merge_commit_sha == fixture["authorization"].merge_commit_sha
        assert receipt.promotion_git_sha == PROMOTION
        assert receipt.origin_main_sha == MAIN
        assert receipt.worker_code_sha256 == WORKER
        assert receipt.bodyrig_body_id == BODY_ID
        assert receipt.bodyrig_package_sha256 == PACKAGE
        assert receipt.pre_lock_checkout_state_sha256 == receipt.post_lock_checkout_state_sha256
        assert receipt.environment_before_sha256 != receipt.environment_after_sha256

        serialized = tx.PilotExactTaskProductionActivationTransactionReceipt.from_mapping(receipt.to_dict())
        assert serialized == receipt
        assert serialized.transaction_authenticated is False

        for field, value in (
            ("production_activation", False),
            ("production_activation_completed", False),
            ("production_activation_authorized", True),
            ("remote_write_authorized", True),
            ("deploy_authorized", True),
            ("controller_returncode", 1),
            ("post_lock_checkout_state_sha256", "8" * 64),
            ("environment_after_sha256", receipt.environment_before_sha256),
        ):
            raw = receipt.to_dict()
            raw[field] = value
            _reject(lambda raw=raw: tx.PilotExactTaskProductionActivationTransactionReceipt.from_mapping(raw))
    finally:
        _cleanup(fixture)

    stale = _fixture()
    try:
        authorization = activation_auth.PilotExactTaskProductionActivationAuthorizationReceipt.from_mapping(
            stale["authorization"].to_dict()
        )
        assert authorization.authorization_authenticated is False
        executor = stale["executor"]
        _reject(
            lambda: tx._execute_verified_pilot_exact_task_production_activation(
                production_activation_authorization=authorization,
                transaction_config=stale["config"],
                transaction_ledger=stale["ledger"],
                bodyrig_evidence_dir=stale["bodyrig"],
                executor=executor,
                now_provider=lambda: "2026-09-15T09:52:11Z",
            )
        )
        assert executor.observe_calls == 0
        assert executor.run_calls == 0
    finally:
        _cleanup(stale)

    cross = _fixture()
    try:
        bad = dict(cross["executor"]._default_state)
        bad["remote_candidate_sha"] = "1" * 40
        executor = _FakeExecutor(cross["authorization"], cross["config"], states=[bad])
        _reject(lambda: _execute(cross, executor=executor))
        assert executor.run_calls == 0
        final, lock = cross["ledger"]._paths(cross["authorization"].production_activation_candidate_sha256)
        assert not lock.exists()
        assert not final.exists()
    finally:
        _cleanup(cross)

    tool = _fixture()
    try:
        gate = Path(tool["config"].promotion_repo_root) / tool["authorization"].promotion_gate_path
        gate.write_text("# tampered gate\n", encoding="utf-8")
        _reject(lambda: _execute(tool))
        assert tool["executor"].run_calls == 0
    finally:
        _cleanup(tool)

    already = _fixture()
    try:
        env = Path(already["config"].appliance_dir) / "modelrig.env"
        env.write_text(
            "KALIV_AGENT3_ENABLED=1\n"
            "KALIV_TOOLS_ENABLED=1\n"
            "KALIV_SCHEDULER=1\n"
            "KALIV_SCHEDULER_API=1\n",
            encoding="utf-8",
        )
        _reject(lambda: _execute(already))
        assert already["executor"].run_calls == 0
    finally:
        _cleanup(already)

    race = _fixture()
    try:
        good = dict(race["executor"]._default_state)
        bad = dict(good)
        bad["remote_candidate_sha"] = "2" * 40
        executor = _FakeExecutor(race["authorization"], race["config"], states=[good, bad])
        _reject(lambda: _execute(race, executor=executor))
        final, lock = race["ledger"]._paths(race["authorization"].production_activation_candidate_sha256)
        assert lock.exists()
        assert not final.exists()
        assert executor.run_calls == 0
    finally:
        _cleanup(race)

    expired = _fixture()
    try:
        moments = iter(
            (
                "2026-09-15T09:52:11Z",
                "2026-09-15T09:52:12Z",
                "2026-09-15T09:57:02Z",
            )
        )
        _reject(lambda: _execute(expired, moments=moments))
        final, lock = expired["ledger"]._paths(expired["authorization"].production_activation_candidate_sha256)
        assert lock.exists()
        assert not final.exists()
        assert expired["executor"].run_calls == 0
    finally:
        _cleanup(expired)

    failed = _fixture()
    try:
        executor = _FakeExecutor(failed["authorization"], failed["config"], mode="fail")
        _reject(lambda: _execute(failed, executor=executor))
        final, lock = failed["ledger"]._paths(failed["authorization"].production_activation_candidate_sha256)
        assert lock.exists()
        assert not final.exists()
        assert executor.run_calls == 1
    finally:
        _cleanup(failed)

    for mode in ("missing", "wrong-candidate", "runtime-false", "wrong-switch", "wrong-env-binding"):
        broken = _fixture()
        try:
            executor = _FakeExecutor(broken["authorization"], broken["config"], mode=mode)
            _reject(lambda: _execute(broken, executor=executor))
            final, lock = broken["ledger"]._paths(
                broken["authorization"].production_activation_candidate_sha256
            )
            assert lock.exists()
            assert not final.exists()
            assert executor.run_calls == 1
        finally:
            _cleanup(broken)

    recovered = _fixture(recovered=True)
    try:
        receipt = _execute(recovered)
        _assert_consumed(receipt)
        assert receipt.success_status_completion_source == "recovery"
        assert receipt.success_status_source_action == "finalize_existing_state"
    finally:
        _cleanup(recovered)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(tx.PilotExactTaskProductionActivationTransactionReceipt.__dataclass_fields__)
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 94

    signature = inspect.signature(tx.execute_pilot_exact_task_production_activation)
    assert list(signature.parameters) == [
        "production_activation_authorization",
        "bodyrig_evidence_dir",
    ]

    source_text = code_of(SOURCE)
    assert "subprocess.run" in source_text
    assert "shell=False" in source_text
    for forbidden in (
        "shell=True",
        "urllib.",
        "requests.",
        "httpx.",
        'method="POST"',
        "method='POST'",
        'method="PUT"',
        "method='PUT'",
        'method="PATCH"',
        "method='PATCH'",
        'method="DELETE"',
        "method='DELETE'",
        '"push"',
        "create_deployment",
        "create_deployment_status",
    ):
        assert forbidden not in source_text
    assert '"ls-remote"' in source_text
    assert '"-TokenEnv"' in source_text
    assert "production_activation_authorized: bool = False" in source_text
    assert "production_activation: bool = True" in source_text


if __name__ == "__main__":
    run_contract()
