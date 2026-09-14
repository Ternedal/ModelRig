"""Adversarial contract for ADR-DC-027 execution-admission observation packet."""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control  # noqa: E402
from kaliv_dev_control import catalog  # noqa: E402
import kaliv_dev_control.improvement_pilot_execution_admission_requirements as req  # noqa: E402
import kaliv_dev_control.improvement_pilot_execution_admission_observation as obs  # noqa: E402
from rsi_pilot_execution_admission_requirements_contract import _receipt  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-execution-admission-observation-packet-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-027 unexpectedly accepted invalid input")


def _evidence() -> dict[str, str]:
    return {
        name: hashlib.sha256(f"adr-dc-027:{name}".encode("utf-8")).hexdigest()
        for name in obs.EVIDENCE_FIELDS
    }


def run_contract() -> None:
    assert catalog.modelrig_command_catalog().command_ids == ()
    temp, receipt = _receipt()
    try:
        requirements = req.build_pilot_execution_admission_requirements(receipt)
        evidence = _evidence()
        packet = obs.build_pilot_execution_admission_observation_packet(
            admission_requirements=requirements,
            observation_id="execution-admission-observation-027",
            observer_actor_id="execution-admission-observer",
            observed_at_utc="2026-09-14T08:29:00Z",
            evidence_sha256=evidence,
        )

        assert packet.schema == obs.PILOT_EXECUTION_ADMISSION_OBSERVATION_SCHEMA
        assert packet.authority == obs.PILOT_EXECUTION_ADMISSION_OBSERVATION_AUTHORITY
        assert packet.admission_requirements is requirements
        assert packet.admission_requirements_sha256 == requirements.sha256
        assert packet.start_receipt_sha256 == requirements.start_receipt_sha256
        assert packet.observation_set_complete is True
        assert packet.evidence_verified is False
        assert packet.execution_admission_observed is False
        assert packet.task_execution_authorized is False
        assert packet.integration_ready is False
        assert packet.product_pilot_started is False
        assert packet.local_commit_authorized is False
        assert packet.remote_write_authorized is False
        assert packet.push_authorized is False
        assert packet.pr_mutation_authorized is False
        assert packet.merge_authorized is False
        assert packet.release_authorized is False
        assert packet.deploy_authorized is False
        assert packet.production_activation_authorized is False
        for name in obs.EVIDENCE_FIELDS:
            assert getattr(packet, name) == evidence[name]

        replayed = obs.PilotExecutionAdmissionObservationPacket.from_mapping(
            packet.to_dict()
        )
        assert replayed == packet
        assert replayed.sha256 == packet.sha256
        assert replayed.admission_requirements == requirements
        # Durable requirements may contain a reloaded ADR-025 receipt. The packet is
        # still only an evidence-reference envelope and cannot recover live authority.
        assert replayed.admission_requirements.start_receipt.transaction_authenticated is False

        missing = dict(evidence)
        missing.pop(obs.EVIDENCE_FIELDS[-1])
        _reject(
            lambda: obs.build_pilot_execution_admission_observation_packet(
                admission_requirements=requirements,
                observation_id="execution-admission-missing-evidence",
                observer_actor_id="execution-admission-observer",
                observed_at_utc="2026-09-14T08:29:00Z",
                evidence_sha256=missing,
            )
        )
        extra = {**evidence, "unexpected_evidence_sha256": "f" * 64}
        _reject(
            lambda: obs.build_pilot_execution_admission_observation_packet(
                admission_requirements=requirements,
                observation_id="execution-admission-extra-evidence",
                observer_actor_id="execution-admission-observer",
                observed_at_utc="2026-09-14T08:29:00Z",
                evidence_sha256=extra,
            )
        )
        bad_digest = dict(evidence)
        bad_digest[obs.EVIDENCE_FIELDS[0]] = "not-a-sha"
        _reject(
            lambda: obs.build_pilot_execution_admission_observation_packet(
                admission_requirements=requirements,
                observation_id="execution-admission-bad-digest",
                observer_actor_id="execution-admission-observer",
                observed_at_utc="2026-09-14T08:29:00Z",
                evidence_sha256=bad_digest,
            )
        )
        _reject(
            lambda: obs.build_pilot_execution_admission_observation_packet(
                admission_requirements=requirements,
                observation_id="execution-admission-before-consume",
                observer_actor_id="execution-admission-observer",
                observed_at_utc="2026-09-14T08:27:59Z",
                evidence_sha256=evidence,
            )
        )
        _reject(
            lambda: obs.PilotExecutionAdmissionObservationPacket.from_mapping(
                {**packet.to_dict(), "admission_requirements_sha256": "0" * 64}
            )
        )
        _reject(
            lambda: obs.PilotExecutionAdmissionObservationPacket.from_mapping(
                {**packet.to_dict(), "start_receipt_sha256": "0" * 64}
            )
        )

        for field in (
            "evidence_verified",
            "execution_admission_observed",
            "task_execution_authorized",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            _reject(
                lambda field=field: obs.PilotExecutionAdmissionObservationPacket.from_mapping(
                    {**packet.to_dict(), field: True}
                )
            )
        _reject(
            lambda: obs.PilotExecutionAdmissionObservationPacket.from_mapping(
                {**packet.to_dict(), "observation_set_complete": False}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        assert set(props) == set(packet.to_dict())
        assert schema["additionalProperties"] is False
        assert (
            props["admission_requirements"]["$ref"]
            == "rsi-pilot-execution-admission-requirements-v1.schema.json"
        )
        assert props["schema"]["const"] == obs.PILOT_EXECUTION_ADMISSION_OBSERVATION_SCHEMA
        assert props["authority"]["const"] == obs.PILOT_EXECUTION_ADMISSION_OBSERVATION_AUTHORITY
        assert props["observation_set_complete"]["const"] is True
        for field in (
            "evidence_verified",
            "execution_admission_observed",
            "task_execution_authorized",
            "integration_ready",
            "product_pilot_started",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert props[field]["const"] is False

        root_source = inspect.getsource(kaliv_dev_control)
        assert "improvement_pilot_execution_admission_observation" not in root_source
        source = inspect.getsource(obs).lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "create_pull_request",
            "open(",
            "read_text",
            "read_bytes",
            "write_text",
            "write_bytes",
        ):
            assert forbidden not in source, forbidden
    finally:
        temp.cleanup()

    # Keep ADR-028 transitively wired through ADR-027 and the same Stage-B
    # support entrypoint instead of expanding the locked top-level inventory.
    from rsi_pilot_execution_admission_attestation_contract import (
        run_contract as run_attestation_contract,
    )

    run_attestation_contract()


if __name__ == "__main__":
    run_contract()
