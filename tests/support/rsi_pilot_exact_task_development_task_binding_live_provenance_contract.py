"""Live-provenance contract for ADR-DC-035 host-pinned DevelopmentTask binding."""
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

import kaliv_dev_control.improvement_pilot_exact_task_development_task_binding as binding  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_admission as admission  # noqa: E402
import kaliv_dev_control.improvement_pilot_exact_task_execution_plan_requirements as plan_req  # noqa: E402
import kaliv_dev_control._improvement_pilot_exact_task_development_task_binding_production_boundary as production  # noqa: E402
from rsi_pilot_exact_task_development_task_binding_contract import _registry, _task  # noqa: E402
from rsi_pilot_exact_task_execution_plan_requirements_contract import _live_receipt  # noqa: E402


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-035 unexpectedly recovered live provenance")


def run_contract() -> None:
    production._LIVE_BINDINGS.clear()
    source_temp, ledger_temp, receipt = _live_receipt()
    original_elevated = production._require_elevated_operator
    original_read = production._read_keyring_bytes
    original_path = production._canonical_registry_path
    try:
        requirements = plan_req.build_pilot_exact_task_execution_plan_requirements(receipt)
        task = _task(requirements)
        payload = _registry(requirements, task)

        # The deterministic support seam proves structure only. It must never
        # manufacture live host-registry provenance.
        deterministic = binding._bind_verified_development_task(
            plan_requirements=requirements,
            admission_receipt=receipt,
            registry_payload=payload,
        )
        assert deterministic.transaction_authenticated is False
        assert "transaction_authenticated" not in deterministic.to_dict()

        deterministic_reload = binding.PilotExactTaskDevelopmentTaskBinding.from_mapping(
            deterministic.to_dict()
        )
        assert deterministic_reload == deterministic
        assert deterministic_reload.transaction_authenticated is False

        # ADR-DC-034 is intentionally reloadable. Its nested receipt is inert;
        # production ADR-DC-035 must therefore authenticate the separately supplied
        # exact live ADR-DC-033 receipt rather than demand nested object identity.
        reloaded_requirements = plan_req.PilotExactTaskExecutionPlanRequirements.from_mapping(
            requirements.to_dict()
        )
        assert reloaded_requirements == requirements
        assert reloaded_requirements is not requirements
        assert reloaded_requirements.admission_receipt is not receipt
        assert (
            reloaded_requirements.admission_receipt.transaction_authenticated
            is False
        )

        # Production reads only the canonical host-controlled registry. The exact
        # returned binding object plus the exact separately supplied live receipt
        # receive process-local provenance.
        calls = []
        production._require_elevated_operator = lambda: None
        production._canonical_registry_path = lambda: Path("/fixed/host/registry.json")

        def fake_read(path, *, require_host_control):
            calls.append((path, require_host_control))
            return payload

        production._read_keyring_bytes = fake_read
        live = binding.bind_pilot_exact_task_development_task(
            plan_requirements=reloaded_requirements,
            admission_receipt=receipt,
        )
        assert live == deterministic
        assert live is not deterministic
        assert live.plan_requirements is reloaded_requirements
        assert live.plan_requirements.admission_receipt is not receipt
        assert live.transaction_authenticated is True
        assert (
            binding.require_live_pilot_exact_task_development_task_binding(
                live, receipt
            )
            is live
        )
        assert calls == [(Path("/fixed/host/registry.json"), True)]
        assert "transaction_authenticated" not in live.to_dict()

        # Durable JSON remains historical evidence. Reload cannot recover the
        # process-local host-registry transaction, even with the original live
        # ADR-DC-033 receipt still present in this process.
        reloaded = binding.PilotExactTaskDevelopmentTaskBinding.from_mapping(
            live.to_dict()
        )
        assert reloaded == live
        assert reloaded is not live
        assert reloaded.transaction_authenticated is False
        _reject(
            lambda: binding.require_live_pilot_exact_task_development_task_binding(
                reloaded, receipt
            )
        )

        # A serialized/reloaded ADR-DC-033 receipt is not a substitute for the
        # exact live receipt that production recorded for this binding.
        inert_receipt = admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert inert_receipt.transaction_authenticated is False
        _reject(
            lambda: binding.require_live_pilot_exact_task_development_task_binding(
                live, inert_receipt
            )
        )

        # Revocation/eviction fails closed. This also proves the marker is side
        # state rather than a serializable authority bit.
        production._LIVE_BINDINGS.clear()
        assert live.transaction_authenticated is False
        _reject(
            lambda: binding.require_live_pilot_exact_task_development_task_binding(
                live, receipt
            )
        )
    finally:
        production._require_elevated_operator = original_elevated
        production._read_keyring_bytes = original_read
        production._canonical_registry_path = original_path
        production._LIVE_BINDINGS.clear()
        ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()
