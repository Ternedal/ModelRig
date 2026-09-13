"""Adversarial production-boundary contract for ADR-DC-013 main freeze."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control._improvement_physical_campaign_main_freeze_impl as implementation  # noqa: E402
import kaliv_dev_control._improvement_physical_campaign_main_freeze_watcher as watcher_module  # noqa: E402
import kaliv_dev_control.improvement_physical_campaign_main_freeze as main_freeze  # noqa: E402
from kaliv_dev_control.improvement_physical_campaign_admission import (  # noqa: E402
    PhysicalCampaignAdmission,
)
from kaliv_dev_control.improvement_physical_campaign_execution_binding import (  # noqa: E402
    EXECUTION_BINDING_ISSUER_SYSTEM_ID,
    PhysicalCampaignExecutionProof,
)
from kaliv_dev_control.improvement_physical_reservation import (  # noqa: E402
    LocalMainHeadObservation,
)
from kaliv_dev_control.physical_isolation import REQUIRED_PROBES  # noqa: E402


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.fspath(path.resolve()))).hexdigest()


def _admission(repository_root: Path) -> PhysicalCampaignAdmission:
    return PhysicalCampaignAdmission(
        ledger_root_path_sha256="0" * 64,
        host_scope_sha256="1" * 64,
        reservation_sha256="2" * 64,
        request_sha256="3" * 64,
        qualification_packet_sha256="4" * 64,
        snapshot_receipt_sha256="5" * 64,
        runner_authorization_sha256="6" * 64,
        runner_authorization_signature_sha256="7" * 64,
        runner_authorizer_actor_id="physical.runner.authorizer",
        campaign_id="campaign-001",
        proposal_id="proposal-001",
        task_id="RSI_TASK_001",
        task_sha256="8" * 64,
        repository="Ternedal/ModelRig",
        base_sha="1" * 40,
        requested_main_sha="2" * 40,
        pre_start_observation_sha256="9" * 64,
        pre_start_observed_at_utc="2026-09-13T12:00:00Z",
        admitted_at_utc="2026-09-13T12:00:05Z",
        repository_root_path_sha256=_path_sha256(repository_root),
        git_runtime_manifest_sha256="a" * 64,
        git_executable_sha256="b" * 64,
        runner_relative_path="tools/run-physical.ps1",
        runner_sha256="c" * 64,
        runner_bytes=4096,
        required_operator_actor_id="physical.operator",
        required_approver_actor_id="physical.approver",
        required_probes=tuple(probe.value for probe in REQUIRED_PROBES),
    )


def _execution_proof(admission: PhysicalCampaignAdmission) -> PhysicalCampaignExecutionProof:
    return PhysicalCampaignExecutionProof(
        binding_sha256="d" * 64,
        evidence_snapshot_sha256="e" * 64,
        signature_sha256="f" * 64,
        key_id="rsi-execution-binding-test-key",
        issuer_actor_id="physical.operator",
        issuer_system_id=EXECUTION_BINDING_ISSUER_SYSTEM_ID,
        binding_id="execution-binding-001",
        admission_sha256=admission.sha256,
        campaign_id=admission.campaign_id,
        task_id=admission.task_id,
        task_sha256=admission.task_sha256,
        repository=admission.repository,
        base_sha=admission.base_sha,
        requested_main_sha=admission.requested_main_sha,
        runner_relative_path=admission.runner_relative_path,
        runner_sha256=admission.runner_sha256,
        runner_bytes=admission.runner_bytes,
        signed_report_sha256="0" * 64,
        physical_report_sha256="1" * 64,
        report_id="report-001",
        operator_actor_id="physical.operator",
        approver_actor_id="physical.approver",
        execution_started_at_utc="2026-09-13T12:01:00Z",
        execution_completed_at_utc="2026-09-13T12:09:00Z",
        binding_created_at_utc="2026-09-13T12:12:00Z",
        verified_at_utc="2026-09-13T12:13:00Z",
    )


class _FakeWatcher:
    def __init__(self, _root: Path, sequence: tuple[bool, ...] = ()) -> None:
        self.backend = "inotify"
        self.scope = (
            ".git/config",
            ".git/packed-refs",
            ".git/packed-refs.lock",
            ".git/refs",
            ".git/refs/heads/main",
            ".git/refs/heads/main.lock",
        )
        self._sequence = list(sequence)
        self.armed = False
        self.closed = False

    def arm(self) -> None:
        assert not self.armed and not self.closed
        self.armed = True

    def clean(self) -> bool:
        if not self.armed or self.closed:
            return False
        if self._sequence:
            return self._sequence.pop(0)
        return True

    def close(self) -> None:
        self.closed = True


def _observer(admission: PhysicalCampaignAdmission, repository_root: Path):
    def observe(at_utc: str) -> LocalMainHeadObservation:
        return LocalMainHeadObservation(
            repository=admission.repository,
            repository_root_path_sha256=_path_sha256(repository_root),
            observed_sha=admission.requested_main_sha,
            observed_at_utc=at_utc,
            git_runtime_manifest_sha256=admission.git_runtime_manifest_sha256,
            git_executable_sha256=admission.git_executable_sha256,
        )

    return observe


def _begin(
    admission: PhysicalCampaignAdmission,
    repository_root: Path,
    *,
    watcher_factory=_FakeWatcher,
    now: str = "2026-09-13T12:00:10Z",
):
    return main_freeze._begin_physical_campaign_main_freeze(
        admission=admission,
        admission_authenticated=True,
        repository_root=repository_root,
        git_runtime_manifest_sha256=admission.git_runtime_manifest_sha256,
        git_executable_sha256=admission.git_executable_sha256,
        watcher_factory=watcher_factory,
        observe_main=_observer(admission, repository_root),
        now_provider=lambda: now,
    )


def _expect_freeze_error(fragment: str, fn) -> None:
    try:
        fn()
    except main_freeze.PhysicalCampaignMainFreezeError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalCampaignMainFreezeError containing {fragment!r}"
        )


def _expect_watcher_error(fragment: str, fn) -> None:
    try:
        fn()
    except watcher_module.GitMainFreezeWatcherError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected GitMainFreezeWatcherError containing {fragment!r}"
        )


def _schema_properties(name: str) -> set[str]:
    value = json.loads(
        (ROOT / "devcontrol" / "schemas" / name).read_text(encoding="utf-8")
    )
    return set(value["properties"])


def _prepare_repository(root: Path, main_sha: str) -> None:
    git_dir = root / ".git"
    heads = git_dir / "refs" / "heads"
    heads.mkdir(parents=True)
    (git_dir / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n",
        encoding="utf-8",
    )
    (heads / "main").write_text(main_sha + "\n", encoding="ascii")
    (git_dir / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n",
        encoding="ascii",
    )


def run_contract() -> None:
    assert implementation._production_main_freeze_boundary_installed is True

    public_begin = inspect.signature(main_freeze.begin_physical_campaign_main_freeze)
    assert set(public_begin.parameters) == {"trusted_git", "admission"}
    public_finalize = inspect.signature(main_freeze.finalize_physical_campaign_main_freeze)
    assert set(public_finalize.parameters) == {
        "trusted_git",
        "lease",
        "execution_proof",
    }
    private_begin = inspect.signature(main_freeze._begin_physical_campaign_main_freeze)
    assert {
        "admission",
        "admission_authenticated",
        "repository_root",
        "git_runtime_manifest_sha256",
        "git_executable_sha256",
        "watcher_factory",
        "observe_main",
        "now_provider",
    } == set(private_begin.parameters)

    with tempfile.TemporaryDirectory(prefix="rsi-main-freeze-") as directory:
        root = Path(directory).resolve()
        _prepare_repository(root, "2" * 40)
        admission = _admission(root)
        execution = _execution_proof(admission)

        _expect_freeze_error(
            "live authenticated admission",
            lambda: main_freeze._begin_physical_campaign_main_freeze(
                admission=admission,
                admission_authenticated=False,
                repository_root=root,
                git_runtime_manifest_sha256=admission.git_runtime_manifest_sha256,
                git_executable_sha256=admission.git_executable_sha256,
                watcher_factory=_FakeWatcher,
                observe_main=_observer(admission, root),
                now_provider=lambda: "2026-09-13T12:00:10Z",
            ),
        )

        lease = _begin(admission, root)
        assert lease.transaction_authenticated is True
        assert lease.start_observed_main_sha == admission.requested_main_sha
        assert lease.watch_backend == "inotify"

        forged = implementation.PhysicalCampaignMainFreezeLease(
            admission_sha256=lease.admission_sha256,
            campaign_id=lease.campaign_id,
            task_id=lease.task_id,
            task_sha256=lease.task_sha256,
            repository=lease.repository,
            base_sha=lease.base_sha,
            requested_main_sha=lease.requested_main_sha,
            freeze_started_at_utc=lease.freeze_started_at_utc,
            start_observation_sha256=lease.start_observation_sha256,
            start_observed_main_sha=lease.start_observed_main_sha,
            repository_root_path_sha256=lease.repository_root_path_sha256,
            git_runtime_manifest_sha256=lease.git_runtime_manifest_sha256,
            git_executable_sha256=lease.git_executable_sha256,
            watch_backend=lease.watch_backend,
            watch_scope=lease.watch_scope,
            _watcher=_FakeWatcher(root),
        )
        assert forged.transaction_authenticated is False

        proof = main_freeze._finalize_physical_campaign_main_freeze(
            lease=lease,
            execution_proof=execution,
            observe_main=_observer(admission, root),
            now_provider=lambda: "2026-09-13T12:14:00Z",
        )
        assert lease.transaction_authenticated is False
        assert lease._watcher.closed is True
        assert proof.admission_sha256 == admission.sha256
        assert proof.execution_proof_sha256 == execution.sha256
        assert proof.evidence_snapshot_sha256 == execution.evidence_snapshot_sha256
        assert proof.runner_execution_binding_proven is True
        assert proof.continuous_main_freeze_proven is True
        assert proof.physical_campaign_completed is False
        assert proof.dc_l15_complete is False
        assert proof.pilot_go_authorized is False
        assert proof.activation_authorized is False
        assert proof.remote_publication_authorized is False
        assert proof.remaining_completion_gates == (
            "dc_l14_independent_human_verdict",
            "human_pilot_go_decision",
        )
        assert proof.authority == "verified-continuous-main-freeze-only"

        def mutating_factory(path: Path):
            return _FakeWatcher(path, (True, True, False))

        mutated = _begin(admission, root, watcher_factory=mutating_factory)
        _expect_freeze_error(
            "observed a Git ref mutation",
            lambda: main_freeze._finalize_physical_campaign_main_freeze(
                lease=mutated,
                execution_proof=execution,
                observe_main=_observer(admission, root),
                now_provider=lambda: "2026-09-13T12:14:00Z",
            ),
        )
        assert mutated.transaction_authenticated is False
        assert mutated._watcher.closed is True

        late_execution = PhysicalCampaignExecutionProof.from_mapping(
            {
                **execution.to_dict(),
                "execution_started_at_utc": "2026-09-13T11:59:00Z",
            }
        )
        before = _begin(admission, root)
        _expect_freeze_error(
            "not enclosed",
            lambda: main_freeze._finalize_physical_campaign_main_freeze(
                lease=before,
                execution_proof=late_execution,
                observe_main=_observer(admission, root),
                now_provider=lambda: "2026-09-13T12:14:00Z",
            ),
        )
        assert before.transaction_authenticated is False

        plan = watcher_module._build_watch_plan(root)
        scope = {item.scope_label for item in plan}
        for required in (
            ".git/config",
            ".git/packed-refs",
            ".git/packed-refs.lock",
            ".git/refs",
            ".git/refs/heads",
            ".git/refs/heads/main",
            ".git/refs/heads/main.lock",
        ):
            assert required in scope, required
        assert any(item.startswith("<repo-") for item in scope)

        (root / ".git" / "reftable").mkdir()
        _expect_watcher_error(
            "reftable",
            lambda: watcher_module._build_watch_plan(root),
        )
        (root / ".git" / "reftable").rmdir()

        (root / ".git" / "refs" / "heads" / "main").write_text(
            "ref: refs/heads/other\n",
            encoding="ascii",
        )
        _expect_watcher_error(
            "symbolic main",
            lambda: watcher_module._build_watch_plan(root),
        )

        assert _schema_properties(
            "rsi-physical-campaign-main-freeze-proof-v1.schema.json"
        ) == set(proof.to_dict())

    source = inspect.getsource(watcher_module)
    for required in (
        "inotify",
        "ReadDirectoryChangesW",
        "_IN_Q_OVERFLOW",
        "packed-refs.lock",
        "main.lock",
        "commondir",
        "reftable",
    ):
        assert required in source, required

    package_init = inspect.getsource(sys.modules["kaliv_dev_control"])
    assert "improvement_physical_campaign_main_freeze" not in package_init


if __name__ == "__main__":
    run_contract()
