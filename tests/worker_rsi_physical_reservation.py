"""RSI physical-request reservation tests outside the landed DC-L01–L14 set."""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))

from kaliv_dev_control.asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control.improvement_physical_request import (
    PHYSICAL_REQUEST_ISSUER_SYSTEM_ID,
    PhysicalQualificationRequest,
    build_physical_qualification_request,
)
from kaliv_dev_control.improvement_physical_reservation import (
    LocalMainHeadObservation,
    PhysicalQualificationRequestLedger,
    PhysicalQualificationReservation,
    PhysicalQualificationReservationError,
    _observe_with_reader,
    build_physical_qualification_reservation,
    consume_physical_qualification_request_once,
)
from kaliv_dev_control.improvement_proposal import AGENT3_EVAL_SCHEMA
from kaliv_dev_control.improvement_qualification_packet import (
    MISSING_PHYSICAL_GATES,
    QualificationPacket,
)

passed = failed = 0
MAIN_SHA = "d" * 40


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_reservation_error(fragment: str, fn, message: str) -> None:
    try:
        fn()
    except PhysicalQualificationReservationError as exc:
        check(fragment in str(exc), message)
    else:
        check(False, message)


def qualification_fixture() -> QualificationPacket:
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
            "snapshot_receipt_sha256": "5" * 64,
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


def request_fixture(qualification: QualificationPacket) -> PhysicalQualificationRequest:
    return build_physical_qualification_request(
        qualification=qualification,
        request_id="rsi-dc-l15-request-reservation-001",
        requested_frozen_main_sha=MAIN_SHA,
        collector_actor_id="collector.one",
        approver_actor_id="approver.two",
        requested_at_utc="2026-09-12T19:10:00Z",
        expires_at_utc="2026-09-12T20:10:00Z",
    )


def sign_request(request: PhysicalQualificationRequest):
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
    return signature, Ed25519AuthorityVerifier(
        {key.key_id: key}, minimum_keyring_epoch=1
    )


class FakeGitReader:
    def __init__(self, sha: str) -> None:
        self.sha = sha
        self.calls: list[tuple[tuple[str, ...], Path, int]] = []

    def run(self, args: tuple[str, ...], *, cwd: Path, maximum: int, **_kwargs) -> bytes:
        self.calls.append((args, cwd, maximum))
        return (self.sha + "\n").encode("ascii")


qualification = qualification_fixture()
request = request_fixture(qualification)
signature, verifier = sign_request(request)

with tempfile.TemporaryDirectory() as repo_tmp:
    repo_root = Path(repo_tmp).resolve()
    reader = FakeGitReader(MAIN_SHA)
    observation = _observe_with_reader(
        reader=reader,
        repository_root=repo_root,
        repository="Ternedal/ModelRig",
        observed_at_utc="2026-09-12T19:11:30Z",
        git_runtime_manifest_sha256="e" * 64,
        git_executable_sha256="f" * 64,
    )
    expected_path_hash = hashlib.sha256(
        os.fsencode(os.fspath(repo_root))
    ).hexdigest()
    check(
        reader.calls == [
            (("rev-parse", "--verify", "refs/heads/main^{commit}"), repo_root, 4096)
        ]
        and observation.repository_root_path_sha256 == expected_path_hash
        and observation.observed_sha == MAIN_SHA
        and observation.network_performed is False
        and observation.repository_mutated is False,
        "main-observation binder exact ref, lokal repo-path og read-only evidence",
    )

    roundtrip = LocalMainHeadObservation.from_mapping(observation.to_dict())
    check(
        roundtrip.canonical_json() == observation.canonical_json(),
        "main-observation roundtripper canonicalt",
    )

    reservation = build_physical_qualification_reservation(
        request=request,
        qualification=qualification,
        signature=signature,
        verifier=verifier,
        observation=observation,
        ledger_id="rsi-dc-l15-ledger-v1",
        consumed_at_utc="2026-09-12T19:12:00Z",
    )
    check(
        reservation.main_head_match_confirmed is True
        and reservation.request_consumed is True
        and reservation.replay_safe is True
        and reservation.requested_main_sha == MAIN_SHA
        and reservation.observed_main_sha == MAIN_SHA
        and reservation.requester_actor_id == "anders.requester",
        "reservation binder human request til frisk exact-main observation",
    )
    check(
        reservation.frozen_main_confirmed is False
        and reservation.physical_campaign_completed is False
        and reservation.campaign_start_authorized is False
        and reservation.pilot_go_authorized is False
        and reservation.activation_authorized is False
        and reservation.remote_publication_authorized is False,
        "one-time consume giver ingen freeze/campaign/pilot/publication/activation authority",
    )
    check(
        PhysicalQualificationReservation.from_mapping(
            reservation.to_dict()
        ).canonical_json()
        == reservation.canonical_json(),
        "reservation receipt roundtripper canonicalt",
    )

    wrong_main = LocalMainHeadObservation.from_mapping(
        {**observation.to_dict(), "observed_sha": "e" * 40}
    )
    expect_reservation_error(
        "does not match the human-requested main SHA",
        lambda: build_physical_qualification_reservation(
            request=request,
            qualification=qualification,
            signature=signature,
            verifier=verifier,
            observation=wrong_main,
            ledger_id="rsi-dc-l15-ledger-v1",
            consumed_at_utc="2026-09-12T19:12:00Z",
        ),
        "reservation afviser lokal main som ikke matcher human-requested SHA",
    )

    stale = LocalMainHeadObservation.from_mapping(
        {**observation.to_dict(), "observed_at_utc": "2026-09-12T19:06:59Z"}
    )
    expect_reservation_error(
        "stale at consumption",
        lambda: build_physical_qualification_reservation(
            request=request,
            qualification=qualification,
            signature=signature,
            verifier=verifier,
            observation=stale,
            ledger_id="rsi-dc-l15-ledger-v1",
            consumed_at_utc="2026-09-12T19:12:00Z",
        ),
        "main-observation ældre end fem minutter fejler lukket",
    )

    elevated = reservation.to_dict()
    elevated["campaign_start_authorized"] = True
    expect_reservation_error(
        "may not claim freeze, campaign, pilot, publication or activation authority",
        lambda: PhysicalQualificationReservation.from_mapping(elevated),
        "reservation receipt kan ikke eskalere til campaign-start",
    )

    with tempfile.TemporaryDirectory() as ledger_tmp:
        ledger = PhysicalQualificationRequestLedger(
            root=Path(ledger_tmp), ledger_id="rsi-dc-l15-ledger-v1"
        )
        consumed = consume_physical_qualification_request_once(
            ledger=ledger,
            request=request,
            qualification=qualification,
            signature=signature,
            verifier=verifier,
            observation=observation,
            consumed_at_utc="2026-09-12T19:12:00Z",
        )
        loaded = ledger.load(request.sha256)
        check(
            loaded.canonical_json() == consumed.canonical_json()
            and loaded.request_sha256 == request.sha256,
            "create-once ledger persisterer og read-back-verificerer reservationen",
        )
        expect_reservation_error(
            "already been consumed or requires recovery",
            lambda: consume_physical_qualification_request_once(
                ledger=ledger,
                request=request,
                qualification=qualification,
                signature=signature,
                verifier=verifier,
                observation=observation,
                consumed_at_utc="2026-09-12T19:12:01Z",
            ),
            "samme human request kan ikke replayes efter successful consume",
        )

    with tempfile.TemporaryDirectory() as crash_tmp:
        crash_root = Path(crash_tmp)
        crash_ledger = PhysicalQualificationRequestLedger(
            root=crash_root, ledger_id="rsi-dc-l15-crash-ledger-v1"
        )
        crash_lock = crash_root / f".{request.sha256}.lock"
        crash_lock.write_text("simulated durable reservation", encoding="utf-8")
        expect_reservation_error(
            "consumed but reservation requires recovery",
            lambda: crash_ledger.load(request.sha256),
            "crash-left lock behandles som consumed/recovery-required, aldrig reusable",
        )
        expect_reservation_error(
            "already been consumed or requires recovery",
            lambda: consume_physical_qualification_request_once(
                ledger=crash_ledger,
                request=request,
                qualification=qualification,
                signature=signature,
                verifier=verifier,
                observation=observation,
                consumed_at_utc="2026-09-12T19:12:02Z",
            ),
            "crash-left lock blokerer replay fail-closed",
        )

print(f"\n===== RSI PHYSICAL RESERVATION: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
