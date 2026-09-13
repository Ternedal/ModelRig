#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "physical_validation_final_gate.py"
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control.improvement_candidate_snapshot import (  # noqa: E402
    CandidateSnapshotReceipt,
)
from kaliv_dev_control.improvement_physical_request import (  # noqa: E402
    PHYSICAL_REQUEST_ISSUER_SYSTEM_ID,
    PhysicalQualificationRequest,
    build_physical_qualification_request,
)
import kaliv_dev_control.improvement_physical_reservation as reservation_module  # noqa: E402
from kaliv_dev_control.improvement_physical_reservation import (  # noqa: E402
    LocalMainHeadObservation,
    PhysicalQualificationReservation,
    PhysicalQualificationReservationError,
    _PhysicalQualificationRequestLedger,
    _consume_physical_qualification_request_once,
    _observe_with_reader,
    consume_physical_qualification_request_once,
)
from kaliv_dev_control.improvement_proposal import AGENT3_EVAL_SCHEMA  # noqa: E402
from kaliv_dev_control.improvement_qualification_packet import (  # noqa: E402
    MISSING_PHYSICAL_GATES,
    QualificationPacket,
)
from kaliv_dev_control.trusted_git_runtime import (  # noqa: E402
    TrustedGitRuntime,
    capture_trusted_git_runtime_manifest,
    stage_trusted_git_runtime,
)


def load_module():
    spec = importlib.util.spec_from_file_location("physical_final_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def fixtures(root: Path, now: datetime) -> tuple[dict, Path, Path]:
    generated = now.isoformat().replace("+00:00", "Z")
    candidate = {
        "version": "1.58.125",
        "git_sha": "b" * 40,
        "code_sha256": "c" * 64,
        "branch": "agent/t032",
        "working_tree_clean": True,
        "dirty_entries": 0,
        "version_stamps_consistent": True,
        "version_check_detail": None,
    }
    campaign = {
        "schema": "kaliv-physical-validation-campaign/v1",
        "generated_at": generated,
        "mode": "verify",
        "candidate": candidate,
        "summary": {
            "total": 7,
            "passed": [
                "preflight",
                "agent3",
                "model_eval",
                "voice",
                "rag",
                "lifecycle",
                "scheduler_pilot",
            ],
            "failed": [],
            "missing": [],
            "candidate_errors": [],
        },
        "gate": {
            "passed": True,
            "physical_campaign_complete": True,
            "production_activation": False,
        },
    }
    digest = "a" * 64
    receipt = {
        "schema": "kaliv-browser-peer-public-validation/v1",
        "generated_at": generated,
        "passed": True,
        "candidate": candidate,
        "target": {"host": "example.com", "port": 443, "url_sha256": "d" * 64},
        "dns": {
            "addresses": ["8.8.8.8"],
            "answer_count": 1,
            "dns_sha256": "e" * 64,
            "selected_address": "8.8.8.8",
        },
        "transport": {
            "connected_address": "8.8.8.8",
            "connected_port": 443,
            "bytes_sent": 202,
            "response_status": 200,
            "response_body_bytes": 559,
            "response_body_sha256": digest,
        },
        "citation": {
            "adapter": "deterministic-web-fetch",
            "content_sha256": digest,
            "bytes_read": 559,
            "media_type": "text/html",
        },
        "evidence": {
            "schema": "kaliv-browser-peer-runtime/v1",
            "selected_address": "8.8.8.8",
            "connected_port": 443,
            "bytes_sent": 202,
            "status": 200,
            "response_body_bytes": 559,
            "response_body_sha256": digest,
            "url_sha256": "d" * 64,
            "production_activation": False,
        },
        "limits": {
            "method": "GET",
            "max_outbound_bytes": 4096,
            "max_response_bytes": 262144,
            "timeout_seconds": 15.0,
            "redirects_followed": False,
        },
        "plan": {
            "plan_id": "bpv_" + "f" * 32,
            "consumed_path": "validation/browser-peer-public-validation-plan.consumed-bpv_x.json",
            "consumed_sha256": "1" * 64,
        },
        "public_network_contacted": True,
        "redirects_followed": False,
        "validation_only": True,
        "production_activation": False,
        "error": None,
    }
    campaign_path = root / "validation" / "physical-validation-campaign-latest.json"
    receipt_path = root / "validation" / "browser-peer-public-validation-latest.json"
    attestation_path = root / "validation" / "browser-peer-public-validation-physical-latest.json"
    write_json(campaign_path, campaign)
    receipt_raw = write_json(receipt_path, receipt)
    attestation = {
        "schema": "kaliv-browser-peer-public-validation-physical/v1",
        "generated_at": generated,
        "candidate": candidate,
        "host": {
            "hostname": "MODELRIG",
            "system": "Windows",
            "release": "11",
            "version": "test",
            "machine": "AMD64",
            "platform": "Windows-11",
            "python": "3.12.0",
        },
        "operator": {
            "interactive_terminal": True,
            "typed_confirmation": True,
            "github_actions": False,
            "ci": False,
        },
        "receipt": {
            "path": "validation/browser-peer-public-validation-latest.json",
            "sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "schema": receipt["schema"],
            "generated_at": receipt["generated_at"],
            "target": receipt["target"],
            "dns": {
                "answer_count": 1,
                "dns_sha256": "e" * 64,
                "selected_address": "8.8.8.8",
            },
            "transport": receipt["transport"],
            "citation": receipt["citation"],
            "plan": receipt["plan"],
        },
        "gate": {
            "passed": True,
            "windows_host": True,
            "interactive_operator": True,
            "candidate_bound": True,
            "receipt_integrity": True,
            "public_network_contacted": True,
            "production_activation": False,
        },
    }
    write_json(attestation_path, attestation)
    return candidate, campaign_path.relative_to(root), attestation_path.relative_to(root)


def evaluate(module, root: Path, candidate: dict, campaign: Path, attestation: Path, now: datetime):
    return module.evaluate_final_gate(
        root,
        campaign,
        attestation,
        candidate=candidate,
        now=now,
        max_age_hours=168.0,
    )


def _qualification_fixture(snapshot_receipt_sha256: str = "5" * 64) -> QualificationPacket:
    return QualificationPacket.from_mapping(
        {
            "schema": "kaliv-rsi-qualification-packet/v1",
            "phase": "pre-dc-l15-physical-qualification",
            "proposal_id": "RSI_A3_001",
            "repository": "Ternedal/ModelRig",
            "base_sha": "a" * 40,
            "proposal_sha256": "1" * 64,
            "promotion_receipt_sha256": "2" * 64,
            "task_id": "RSI_TASK_001",
            "task_sha256": "3" * 64,
            "materialization_receipt_sha256": "4" * 64,
            "snapshot_receipt_sha256": snapshot_receipt_sha256,
            "candidate_commit_sha": "b" * 40,
            "candidate_tree_sha": "c" * 40,
            "worker_code_sha256": "6" * 64,
            "baseline_eval_sha256": "7" * 64,
            "candidate_eval_sha256": "8" * 64,
            "regression_proof_sha256": "9" * 64,
            "runtime_provenance_sha256": "a" * 64,
            "required_evals": [AGENT3_EVAL_SCHEMA],
            "software_chain_complete": True,
            "ready_for_human_go": False,
            "activation_authorized": False,
            "automatic_activation": False,
            "remote_publication_authorized": False,
            "fresh_physical_evidence_required": True,
            "independent_collector_approver_required": True,
            "missing_physical_gates": list(MISSING_PHYSICAL_GATES),
            "authority": "evidence-only",
            "merge_authority": "human",
        }
    )


def _request_fixture(qualification: QualificationPacket) -> PhysicalQualificationRequest:
    return build_physical_qualification_request(
        qualification=qualification,
        request_id="rsi-dc-l15-request-reservation-001",
        requested_frozen_main_sha="d" * 40,
        collector_actor_id="collector.one",
        approver_actor_id="approver.two",
        requested_at_utc="2026-09-12T19:10:00Z",
        expires_at_utc="2026-09-12T20:10:00Z",
    )


def _sign_request(request: PhysicalQualificationRequest):
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy_hash = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="rsi-dc-l15-reservation-test-key",
        issuer_actor_id="anders.requester",
        issuer_system_id=PHYSICAL_REQUEST_ISSUER_SYSTEM_ID,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-12T00:00:00Z",
        valid_until_utc="2026-09-13T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=policy_hash,
    )
    payload = request.canonical_json().encode("utf-8")
    message = authority_signing_message(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=key.custody_policy_sha256,
        payload=payload,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=key.custody_policy_sha256,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private.sign(message).hex(),
        signed_at_utc="2026-09-12T19:10:30Z",
    )
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)
    return signature, verifier


class _FakeMainReader:
    def __init__(self, sha: str) -> None:
        self.sha = sha
        self.calls: list[tuple[tuple[str, ...], Path, int]] = []

    def run(self, args: tuple[str, ...], *, cwd: Path, maximum: int, **_kwargs) -> bytes:
        self.calls.append((args, cwd, maximum))
        return (self.sha + "\n").encode("ascii")


def _expect_reservation_error(fragment: str, fn) -> None:
    try:
        fn()
    except PhysicalQualificationReservationError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalQualificationReservationError containing {fragment!r}"
        )


_TRUSTED_GIT_SCRIPT = b'''#!/bin/sh
while [ "$#" -ge 2 ] && [ "$1" = "-c" ]; do
    shift 2
done
case "$1" in
    --version)
        printf 'git version modelrig-rsi-test-1\n'
        ;;
    rev-parse)
        if [ "$2" = "--verify" ]; then
            IFS= read -r main_sha < .modelrig-main-sha || exit 7
            printf '%s\n' "$main_sha"
        else
            exit 8
        fi
        ;;
    *)
        exit 9
        ;;
esac
'''

_TRUSTED_GIT_HELPER = b'''#!/bin/sh
exit 0
'''


def _trusted_git_fixture(root: Path, main_sha: str, *, runtime_marker: bytes = b"rsi-test-runtime"):
    if os.name == "nt":
        return None
    source = root / "trusted-git-source"
    (source / "bin").mkdir(parents=True)
    (source / "libexec" / "git-core").mkdir(parents=True)
    (source / "lib").mkdir(parents=True)
    executable = source / "bin" / "git"
    helper = source / "libexec" / "git-core" / "git-helper"
    executable.write_bytes(_TRUSTED_GIT_SCRIPT)
    helper.write_bytes(_TRUSTED_GIT_HELPER)
    (source / "lib" / "runtime.so").write_bytes(runtime_marker)
    executable.chmod(0o755)
    helper.chmod(0o755)
    manifest = capture_trusted_git_runtime_manifest(
        source.resolve(),
        executable_relative_path="bin/git",
        exec_path_relative_path="libexec/git-core",
        path_relative_directories=("bin", "libexec/git-core", "lib"),
    )
    staging = root / "trusted-git-staging"
    staging.mkdir()
    transaction = stage_trusted_git_runtime(
        manifest,
        source_root=source.resolve(),
        staging_root=staging.resolve(),
    )
    operation = root / "trusted-git-operation"
    operation.mkdir()
    repository = root / "repository"
    repository.mkdir()
    (repository / ".modelrig-main-sha").write_text(main_sha + "\n", encoding="ascii")
    return TrustedGitRuntime(transaction.resolve()), operation.resolve(), repository.resolve()


def _snapshot_receipt_fixture(trusted_git: TrustedGitRuntime) -> CandidateSnapshotReceipt:
    manifest = trusted_git.receipt.manifest
    executable = next(
        item
        for item in manifest.files
        if item.relative_path == manifest.executable_relative_path
    )
    return CandidateSnapshotReceipt(
        materialization_receipt_sha256="4" * 64,
        task_sha256="3" * 64,
        candidate_commit_sha="b" * 40,
        candidate_tree_sha="c" * 40,
        file_count=1,
        total_bytes=1,
        manifest_sha256="f" * 64,
        git_runtime_manifest_sha256=manifest.sha256,
        git_executable_sha256=executable.sha256,
    )


class _SequenceClock:
    def __init__(self, values: list[str], *, mutate=None) -> None:
        self.values = list(values)
        self.calls = 0
        self.mutate = mutate

    def __call__(self) -> str:
        if self.calls >= len(self.values):
            raise AssertionError("test clock exhausted")
        self.calls += 1
        if self.mutate is not None:
            self.mutate(self.calls)
        return self.values[self.calls - 1]


def reservation_contract() -> None:
    main_sha = "d" * 40

    # The serializable observation model is still useful as evidence, but class
    # membership is explicitly not provenance for the authority-bearing consume API.
    with tempfile.TemporaryDirectory() as directory:
        repo_root = Path(directory).resolve()
        reader = _FakeMainReader(main_sha)
        observation = _observe_with_reader(
            reader=reader,
            repository_root=repo_root,
            repository="Ternedal/ModelRig",
            observed_at_utc="2026-09-12T19:11:30Z",
            git_runtime_manifest_sha256="e" * 64,
            git_executable_sha256="f" * 64,
        )
        expected_path_hash = hashlib.sha256(os.fsencode(os.fspath(repo_root))).hexdigest()
        assert reader.calls == [
            (("rev-parse", "--verify", "refs/heads/main^{commit}"), repo_root, 4096)
        ]
        assert observation.repository_root_path_sha256 == expected_path_hash
        assert LocalMainHeadObservation.from_mapping(
            observation.to_dict()
        ).canonical_json() == observation.canonical_json()

    public_parameters = set(inspect.signature(consume_physical_qualification_request_once).parameters)
    assert "observation" not in public_parameters
    assert "consumed_at_utc" not in public_parameters
    assert "ledger" not in public_parameters
    assert "ledger_root" not in public_parameters
    assert "repository_root" not in public_parameters
    assert "operation_root" not in public_parameters
    assert "snapshot_receipt" in public_parameters
    assert not hasattr(reservation_module, "build_physical_qualification_reservation")
    assert not hasattr(reservation_module, "PhysicalQualificationRequestLedger")

    # Synthetic TrustedGitRuntime is POSIX-only. Exact-head Linux CI exercises
    # the transaction; portable assertions above still run on Windows jobs.
    if os.name == "nt":
        return

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        fixture = _trusted_git_fixture(root, main_sha)
        assert fixture is not None
        trusted_git, operation_root, repository_root = fixture
        snapshot_receipt = _snapshot_receipt_fixture(trusted_git)
        qualification = _qualification_fixture(snapshot_receipt.sha256)
        request = _request_fixture(qualification)
        signature, verifier = _sign_request(request)
        ledger_root = root / "ledger"
        ledger_root.mkdir()
        consumed = _consume_physical_qualification_request_once(
            ledger_root=ledger_root,
            trusted_git=trusted_git,
            repository_root=repository_root,
            operation_root=operation_root,
            request=request,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            signature=signature,
            verifier=verifier,
            now_provider=_SequenceClock(
                [
                    "2026-09-12T19:11:00Z",
                    "2026-09-12T19:11:01Z",
                    "2026-09-12T19:11:02Z",
                ]
            ),
        )
        assert consumed.main_head_match_confirmed is True
        assert consumed.request_consumed is True
        assert consumed.host_replay_guard_committed is True
        assert consumed.global_replay_safe is False
        assert consumed.snapshot_receipt_sha256 == snapshot_receipt.sha256
        assert consumed.git_runtime_manifest_sha256 == snapshot_receipt.git_runtime_manifest_sha256
        assert consumed.git_executable_sha256 == snapshot_receipt.git_executable_sha256
        assert consumed.requester_actor_id == "anders.requester"
        assert consumed.requested_main_sha == main_sha
        assert consumed.observed_main_sha == main_sha
        assert consumed.frozen_main_confirmed is False
        assert consumed.physical_campaign_completed is False
        assert consumed.campaign_start_authorized is False
        assert consumed.pilot_go_authorized is False
        assert consumed.activation_authorized is False
        assert consumed.remote_publication_authorized is False
        assert PhysicalQualificationReservation.from_mapping(
            consumed.to_dict()
        ).canonical_json() == consumed.canonical_json()

        ledger = _PhysicalQualificationRequestLedger(ledger_root)
        loaded = ledger.load(request.sha256)
        assert loaded.canonical_json() == consumed.canonical_json()

        _expect_reservation_error(
            "already been host-locally consumed",
            lambda: _consume_physical_qualification_request_once(
                ledger_root=ledger_root,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=operation_root,
                request=request,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                signature=signature,
                verifier=verifier,
                now_provider=_SequenceClock(
                    [
                        "2026-09-12T19:12:00Z",
                        "2026-09-12T19:12:01Z",
                        "2026-09-12T19:12:02Z",
                    ]
                ),
            ),
        )

        elevated = consumed.to_dict()
        elevated["campaign_start_authorized"] = True
        _expect_reservation_error(
            "may not claim freeze, campaign, pilot, publication or activation authority",
            lambda: PhysicalQualificationReservation.from_mapping(elevated),
        )
        global_claim = consumed.to_dict()
        global_claim["global_replay_safe"] = True
        _expect_reservation_error(
            "replay scope/consume evidence is invalid",
            lambda: PhysicalQualificationReservation.from_mapping(global_claim),
        )

    # A different staged Git package is integrity-valid, but not authority-valid:
    # its runtime identity is not the one bound by the signed snapshot receipt.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        fixture = _trusted_git_fixture(root, main_sha, runtime_marker=b"different-runtime")
        assert fixture is not None
        other_git, operation_root, repository_root = fixture
        ledger_root = root / "ledger"
        ledger_root.mkdir()
        _expect_reservation_error(
            "does not match the signed snapshot runtime identity",
            lambda: _consume_physical_qualification_request_once(
                ledger_root=ledger_root,
                trusted_git=other_git,
                repository_root=repository_root,
                operation_root=operation_root,
                request=request,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                signature=signature,
                verifier=verifier,
                now_provider=_SequenceClock(["2026-09-12T19:12:30Z"]),
            ),
        )
        _expect_reservation_error(
            "reservation is missing",
            lambda: _PhysicalQualificationRequestLedger(ledger_root).load(request.sha256),
        )

    # Main moving after preflight but before the post-lock trusted read burns the
    # local request and leaves an explicit recovery-required lock.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        fixture = _trusted_git_fixture(root, main_sha)
        assert fixture is not None
        trusted_git, operation_root, repository_root = fixture
        ledger_root = root / "ledger"
        ledger_root.mkdir()

        def move_main(call: int) -> None:
            if call == 2:
                (repository_root / ".modelrig-main-sha").write_text(
                    "e" * 40 + "\n", encoding="ascii"
                )

        moving_clock = _SequenceClock(
            ["2026-09-12T19:13:00Z", "2026-09-12T19:13:01Z"],
            mutate=move_main,
        )
        _expect_reservation_error(
            "does not match the human-requested main SHA",
            lambda: _consume_physical_qualification_request_once(
                ledger_root=ledger_root,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=operation_root,
                request=request,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                signature=signature,
                verifier=verifier,
                now_provider=moving_clock,
            ),
        )
        _expect_reservation_error(
            "host-locally consumed but reservation requires recovery",
            lambda: _PhysicalQualificationRequestLedger(ledger_root).load(request.sha256),
        )

    # Caller backdating is impossible on the public API; crossing expiry after
    # lock is re-verified against the injected trusted test clock and stays consumed.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        fixture = _trusted_git_fixture(root, main_sha)
        assert fixture is not None
        trusted_git, operation_root, repository_root = fixture
        ledger_root = root / "ledger"
        ledger_root.mkdir()
        expiry_clock = _SequenceClock(
            [
                "2026-09-12T20:09:59Z",
                "2026-09-12T20:10:00Z",
                "2026-09-12T20:10:01Z",
            ]
        )
        _expect_reservation_error(
            "request re-verification failed",
            lambda: _consume_physical_qualification_request_once(
                ledger_root=ledger_root,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=operation_root,
                request=request,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                signature=signature,
                verifier=verifier,
                now_provider=expiry_clock,
            ),
        )
        _expect_reservation_error(
            "host-locally consumed but reservation requires recovery",
            lambda: _PhysicalQualificationRequestLedger(ledger_root).load(request.sha256),
        )

    # Two independent private roots can each reserve the request, which is exactly
    # why the final receipt MUST NOT claim distributed/global replay safety.
    receipts = []
    for index in (1, 2):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = _trusted_git_fixture(root, main_sha)
            assert fixture is not None
            trusted_git, operation_root, repository_root = fixture
            ledger_root = root / "ledger"
            ledger_root.mkdir()
            receipts.append(
                _consume_physical_qualification_request_once(
                    ledger_root=ledger_root,
                    trusted_git=trusted_git,
                    repository_root=repository_root,
                    operation_root=operation_root,
                    request=request,
                    qualification=qualification,
                    snapshot_receipt=snapshot_receipt,
                    signature=signature,
                    verifier=verifier,
                    now_provider=_SequenceClock(
                        [
                            f"2026-09-12T19:2{index}:00Z",
                            f"2026-09-12T19:2{index}:01Z",
                            f"2026-09-12T19:2{index}:02Z",
                        ]
                    ),
                )
            )
    assert all(receipt.global_replay_safe is False for receipt in receipts)
    assert receipts[0].ledger_root_path_sha256 != receipts[1].ledger_root_path_sha256

    # A crash-left lock is never interpreted as a reusable request.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        ledger = _PhysicalQualificationRequestLedger(root)
        ledger.acquire_lock(request.sha256)
        _expect_reservation_error(
            "host-locally consumed but reservation requires recovery",
            lambda: ledger.load(request.sha256),
        )

    # Canonical final receipts are fail-closed against byte-level tampering.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        fixture = _trusted_git_fixture(root, main_sha)
        assert fixture is not None
        trusted_git, operation_root, repository_root = fixture
        ledger_root = root / "ledger"
        ledger_root.mkdir()
        consumed = _consume_physical_qualification_request_once(
            ledger_root=ledger_root,
            trusted_git=trusted_git,
            repository_root=repository_root,
            operation_root=operation_root,
            request=request,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            signature=signature,
            verifier=verifier,
            now_provider=_SequenceClock(
                [
                    "2026-09-12T19:30:00Z",
                    "2026-09-12T19:30:01Z",
                    "2026-09-12T19:30:02Z",
                ]
            ),
        )
        final_path = ledger_root / f"{request.sha256}.json"
        final_path.write_bytes(consumed.canonical_json().encode("utf-8") + b"\n")
        _expect_reservation_error(
            "not canonical",
            lambda: _PhysicalQualificationRequestLedger(ledger_root).load(request.sha256),
        )


def main() -> None:
    module = load_module()
    doc = " ".join((module.__doc__ or "").split())
    assert "seven-proof physical campaign" in doc
    assert "eighth-proof final receipt" in doc
    now = datetime(2026, 7, 20, 18, 30, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, campaign, attestation = fixtures(root, now)
        report, code = evaluate(module, root, candidate, campaign, attestation, now)
        assert code == 0
        assert report["gate"]["all_physical_evidence_complete"] is True
        assert report["summary"]["total"] == 8
        assert "scheduler_pilot" in report["summary"]["passed"]
        assert report["summary"]["passed"][-1] == "browser_peer_physical"
        assert report["gate"]["production_activation"] is False

        attestation_file = root / attestation
        value = json.loads(attestation_file.read_text(encoding="utf-8"))
        value["host"]["system"] = "Linux"
        write_json(attestation_file, value)
        report, code = evaluate(module, root, candidate, campaign, attestation, now)
        assert code == 1 and report["gate"]["passed"] is False

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, campaign, attestation = fixtures(root, now)
        attestation_file = root / attestation
        value = json.loads(attestation_file.read_text(encoding="utf-8"))
        value["operator"]["github_actions"] = True
        write_json(attestation_file, value)
        report, code = evaluate(module, root, candidate, campaign, attestation, now)
        assert code == 1

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, campaign, attestation = fixtures(root, now)
        receipt_file = root / "validation" / "browser-peer-public-validation-latest.json"
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
        receipt["transport"]["connected_address"] = "1.1.1.1"
        write_json(receipt_file, receipt)
        report, code = evaluate(module, root, candidate, campaign, attestation, now)
        assert code == 1
        assert any("hash" in error or "peer" in error for error in report["summary"]["errors"])

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        candidate, campaign, attestation = fixtures(root, now)
        hosted_candidate = copy.deepcopy(candidate)
        hosted_candidate["git_sha"] = "9" * 40
        report, code = evaluate(module, root, hosted_candidate, campaign, attestation, now)
        assert code == 1
        assert any("candidate.git_sha" in error for error in report["summary"]["errors"])

    reservation_contract()
    print("physical validation final eight-proof gate + RSI host-local reservation: PASS")


if __name__ == "__main__":
    main()
