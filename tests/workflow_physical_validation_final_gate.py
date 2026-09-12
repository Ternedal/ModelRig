#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
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
from kaliv_dev_control.improvement_physical_request import (  # noqa: E402
    PHYSICAL_REQUEST_ISSUER_SYSTEM_ID,
    PhysicalQualificationRequest,
    build_physical_qualification_request,
)
from kaliv_dev_control.improvement_physical_reservation import (  # noqa: E402
    LocalMainHeadObservation,
    PhysicalQualificationRequestLedger,
    PhysicalQualificationReservation,
    PhysicalQualificationReservationError,
    _observe_with_reader,
    build_physical_qualification_reservation,
    consume_physical_qualification_request_once,
)
from kaliv_dev_control.improvement_proposal import AGENT3_EVAL_SCHEMA  # noqa: E402
from kaliv_dev_control.improvement_qualification_packet import (  # noqa: E402
    MISSING_PHYSICAL_GATES,
    QualificationPacket,
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


def _qualification_fixture() -> QualificationPacket:
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
        raise AssertionError(f"expected PhysicalQualificationReservationError containing {fragment!r}")


def reservation_contract() -> None:
    qualification = _qualification_fixture()
    request = _request_fixture(qualification)
    signature, verifier = _sign_request(request)
    main_sha = request.requested_frozen_main_sha

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
        assert observation.network_performed is False
        assert observation.repository_mutated is False
        assert LocalMainHeadObservation.from_mapping(
            observation.to_dict()
        ).canonical_json() == observation.canonical_json()

        reservation = build_physical_qualification_reservation(
            request=request,
            qualification=qualification,
            signature=signature,
            verifier=verifier,
            observation=observation,
            ledger_id="rsi-dc-l15-ledger-v1",
            consumed_at_utc="2026-09-12T19:12:00Z",
        )
        assert reservation.main_head_match_confirmed is True
        assert reservation.request_consumed is True
        assert reservation.replay_safe is True
        assert reservation.requester_actor_id == "anders.requester"
        assert reservation.requested_main_sha == main_sha
        assert reservation.observed_main_sha == main_sha
        assert reservation.frozen_main_confirmed is False
        assert reservation.physical_campaign_completed is False
        assert reservation.campaign_start_authorized is False
        assert reservation.pilot_go_authorized is False
        assert reservation.activation_authorized is False
        assert reservation.remote_publication_authorized is False
        assert PhysicalQualificationReservation.from_mapping(
            reservation.to_dict()
        ).canonical_json() == reservation.canonical_json()

        wrong_main = LocalMainHeadObservation.from_mapping(
            {**observation.to_dict(), "observed_sha": "e" * 40}
        )
        _expect_reservation_error(
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
        )

        stale = LocalMainHeadObservation.from_mapping(
            {**observation.to_dict(), "observed_at_utc": "2026-09-12T19:06:59Z"}
        )
        _expect_reservation_error(
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
        )

        fresh_but_expired = LocalMainHeadObservation.from_mapping(
            {**observation.to_dict(), "observed_at_utc": "2026-09-12T20:09:59Z"}
        )
        _expect_reservation_error(
            "request re-verification failed",
            lambda: build_physical_qualification_reservation(
                request=request,
                qualification=qualification,
                signature=signature,
                verifier=verifier,
                observation=fresh_but_expired,
                ledger_id="rsi-dc-l15-ledger-v1",
                consumed_at_utc="2026-09-12T20:10:01Z",
            ),
        )

        elevated = reservation.to_dict()
        elevated["campaign_start_authorized"] = True
        _expect_reservation_error(
            "may not claim freeze, campaign, pilot, publication or activation authority",
            lambda: PhysicalQualificationReservation.from_mapping(elevated),
        )

        with tempfile.TemporaryDirectory() as ledger_directory:
            ledger = PhysicalQualificationRequestLedger(
                root=Path(ledger_directory), ledger_id="rsi-dc-l15-ledger-v1"
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
            assert loaded.canonical_json() == consumed.canonical_json()
            _expect_reservation_error(
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
            )

        with tempfile.TemporaryDirectory() as crash_directory:
            crash_root = Path(crash_directory)
            crash_ledger = PhysicalQualificationRequestLedger(
                root=crash_root, ledger_id="rsi-dc-l15-crash-ledger-v1"
            )
            crash_lock = crash_root / f".{request.sha256}.lock"
            crash_lock.write_text("simulated durable reservation", encoding="utf-8")
            _expect_reservation_error(
                "consumed but reservation requires recovery",
                lambda: crash_ledger.load(request.sha256),
            )
            _expect_reservation_error(
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
            )

        with tempfile.TemporaryDirectory() as tamper_directory:
            tamper_root = Path(tamper_directory)
            tamper_ledger = PhysicalQualificationRequestLedger(
                root=tamper_root, ledger_id="rsi-dc-l15-tamper-ledger-v1"
            )
            consumed = consume_physical_qualification_request_once(
                ledger=tamper_ledger,
                request=request,
                qualification=qualification,
                signature=signature,
                verifier=verifier,
                observation=observation,
                consumed_at_utc="2026-09-12T19:12:03Z",
            )
            final_path = tamper_root / f"{request.sha256}.json"
            final_path.write_bytes(consumed.canonical_json().encode("utf-8") + b"\n")
            _expect_reservation_error(
                "not canonical",
                lambda: tamper_ledger.load(request.sha256),
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
    print("physical validation final eight-proof gate + RSI request reservation: PASS")


if __name__ == "__main__":
    main()