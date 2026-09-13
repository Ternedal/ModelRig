"""Live-provenance contract for ADR-DC-010 campaign admissions.

This support module is imported explicitly by an existing workflow test.  It does
not extend the top-level test glob while ADR-DC-010 remains proposed.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

from kaliv_dev_control.improvement_physical_campaign_admission import (
    PhysicalCampaignAdmission,
    _PhysicalCampaignAdmissionLedger,
)
from kaliv_dev_control.physical_isolation import REQUIRED_PROBES


def _admission(*, ledger_root_path_sha256: str = "1" * 64) -> PhysicalCampaignAdmission:
    return PhysicalCampaignAdmission(
        ledger_root_path_sha256=ledger_root_path_sha256,
        host_scope_sha256="2" * 64,
        reservation_sha256="3" * 64,
        request_sha256="4" * 64,
        qualification_packet_sha256="5" * 64,
        snapshot_receipt_sha256="6" * 64,
        runner_authorization_sha256="7" * 64,
        runner_authorization_signature_sha256="8" * 64,
        runner_authorizer_actor_id="runner.authorizer",
        campaign_id="rsi-dc-l15-campaign-001",
        proposal_id="RSI_A3_001",
        task_id="RSI_TASK_001",
        task_sha256="9" * 64,
        repository="Ternedal/ModelRig",
        base_sha="a" * 40,
        requested_main_sha="b" * 40,
        pre_start_observation_sha256="c" * 64,
        pre_start_observed_at_utc="2026-09-13T05:55:00Z",
        admitted_at_utc="2026-09-13T05:55:30Z",
        repository_root_path_sha256="d" * 64,
        git_runtime_manifest_sha256="e" * 64,
        git_executable_sha256="f" * 64,
        runner_relative_path="scripts/dc_l15_runner.py",
        runner_sha256="0" * 64,
        runner_bytes=1,
        required_operator_actor_id="collector.one",
        required_approver_actor_id="approver.two",
        required_probes=tuple(probe.value for probe in REQUIRED_PROBES),
    )


def _live_admission(root: Path):
    ledger_root = root / "ledger"
    ledger_root.mkdir()
    ledger = _PhysicalCampaignAdmissionLedger(ledger_root)
    evidence = _admission(ledger_root_path_sha256=ledger.root_sha256)
    ledger.acquire_lock(evidence.reservation_sha256)
    live = ledger.commit_locked_mapping(
        reservation_sha256=evidence.reservation_sha256,
        mapping=evidence.to_dict(),
    )
    final, pending, lock = ledger._paths(evidence.reservation_sha256)
    assert final.is_file()
    assert not pending.exists()
    assert lock.is_file()
    assert live.transaction_authenticated is True
    return ledger, live, final, lock


def _run_authority_race_contract() -> None:
    path = Path(__file__).with_name(
        "rsi_physical_campaign_admission_authority_races.py"
    )
    spec = importlib.util.spec_from_file_location(
        "rsi_physical_campaign_admission_authority_races",
        path,
    )
    assert spec is not None and spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = contract
    spec.loader.exec_module(contract)
    contract.run_contract()


def run_contract() -> None:
    parsed = _admission()
    assert parsed.transaction_authenticated is False

    with tempfile.TemporaryDirectory(prefix="rsi-admission-provenance-") as directory:
        root = Path(directory).resolve()
        _ledger, live, final, lock = _live_admission(root)
        authenticated_sha = live.sha256

        object.__setattr__(live, "campaign_id", "rsi-dc-l15-campaign-mutated")
        assert live.sha256 != authenticated_sha
        assert live.transaction_authenticated is False

        # A fresh live receipt is authority only while both durable markers remain
        # byte-for-byte equal to the exact create-once transaction payloads.
        marker_root = root / "marker-case"
        marker_root.mkdir()
        _marker_ledger, marker_live, marker_final, marker_lock = _live_admission(marker_root)
        marker_final.write_bytes(marker_final.read_bytes() + b"\n")
        assert marker_live.transaction_authenticated is False

        lock_root = root / "lock-case"
        lock_root.mkdir()
        _lock_ledger, lock_live, _lock_final, lock_marker = _live_admission(lock_root)
        lock_marker.unlink()
        assert lock_live.transaction_authenticated is False

    if hasattr(os, "fork"):
        with tempfile.TemporaryDirectory(prefix="rsi-admission-fork-") as directory:
            root = Path(directory).resolve()
            _ledger, inherited, _final, _lock = _live_admission(root)
            assert inherited.transaction_authenticated is True

            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(read_fd)
                    observed = b"1" if inherited.transaction_authenticated else b"0"
                    os.write(write_fd, observed)
                finally:
                    os.close(write_fd)
                    os._exit(0)

            os.close(write_fd)
            try:
                child_value = os.read(read_fd, 1)
            finally:
                os.close(read_fd)
            waited_pid, status = os.waitpid(pid, 0)
            assert waited_pid == pid
            assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
            assert child_value == b"0", child_value
            assert inherited.transaction_authenticated is True

    _run_authority_race_contract()
