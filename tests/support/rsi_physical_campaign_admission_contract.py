"""Adversarial contract for ADR-DC-010 physical campaign admission.

Imported explicitly by an existing workflow test so repository test discovery and
CURRENT_STATE.md do not gain a new glob entry while the ADR remains proposed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
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
from kaliv_dev_control.improvement_physical_campaign_admission import (  # noqa: E402
    RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID,
    PhysicalCampaignAdmission,
    PhysicalCampaignAdmissionError,
    PhysicalCampaignRunnerAuthorization,
    _PhysicalCampaignAdmissionLedger,
    _issue_physical_campaign_admission_once,
    build_physical_campaign_runner_authorization,
    issue_physical_campaign_admission_once,
    reservation_host_scope_sha256,
)
from kaliv_dev_control.improvement_physical_reservation import (  # noqa: E402
    PhysicalQualificationReservation,
    _PhysicalQualificationRequestLedger,
)
from kaliv_dev_control.physical_isolation import REQUIRED_PROBES  # noqa: E402


def _load_parent_test_module():
    path = ROOT / "tests" / "workflow_physical_validation_final_gate.py"
    spec = importlib.util.spec_from_file_location("rsi_parent_reservation_test_support", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _expect(fragment: str, fn) -> None:
    try:
        fn()
    except PhysicalCampaignAdmissionError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected PhysicalCampaignAdmissionError containing {fragment!r}")


def _sign_runner_authorization(
    authorization: PhysicalCampaignRunnerAuthorization,
    *,
    issuer_system_id: str = RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID,
    signed_at_utc: str = "2026-09-12T19:11:06Z",
):
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy_hash = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="rsi-dc-l15-runner-test-key",
        issuer_actor_id="anders.runner-authorizer",
        issuer_system_id=issuer_system_id,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-12T00:00:00Z",
        valid_until_utc="2026-09-13T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=policy_hash,
    )
    payload = authorization.canonical_json().encode("utf-8")
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
        signed_at_utc=signed_at_utc,
    )
    return signature, Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)


def _fresh_dir(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    return path.resolve()


def _schema_properties(name: str) -> set[str]:
    value = json.loads((ROOT / "devcontrol" / "schemas" / name).read_text(encoding="utf-8"))
    return set(value["properties"])


def run_contract() -> None:
    public_parameters = set(inspect.signature(issue_physical_campaign_admission_once).parameters)
    assert public_parameters == {
        "trusted_git",
        "reservation",
        "qualification",
        "snapshot_receipt",
        "runner_authorization",
        "runner_signature",
        "verifier",
    }
    for forbidden in (
        "observation",
        "admitted_at_utc",
        "ledger_root",
        "repository_root",
        "operation_root",
        "campaign_id",
        "operator_actor_id",
        "runner_relative_path",
        "runner_sha256",
        "runner_bytes",
    ):
        assert forbidden not in public_parameters

    # The synthetic staged Trusted-Git fixture is POSIX-only. Windows CI still
    # exercises import/signature shape/schema invariants; exact-head Linux runs
    # the complete authority transaction below.
    if os.name == "nt":
        return

    parent = _load_parent_test_module()
    main_sha = "d" * 40
    with tempfile.TemporaryDirectory(prefix="rsi-campaign-admission-") as directory:
        root = Path(directory).resolve()
        fixture = parent._trusted_git_fixture(root, main_sha)
        assert fixture is not None
        trusted_git, reservation_operation_root, repository_root = fixture
        snapshot_receipt = parent._snapshot_receipt_fixture(trusted_git)
        qualification = parent._qualification_fixture(snapshot_receipt.sha256)
        request = parent._request_fixture(qualification)
        request_signature, request_verifier = parent._sign_request(request)
        reservation_ledger_root = _fresh_dir(root, "reservation-ledger")
        reservation = parent._consume_physical_qualification_request_once(
            ledger_root=reservation_ledger_root,
            trusted_git=trusted_git,
            repository_root=repository_root,
            operation_root=reservation_operation_root,
            request=request,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            signature=request_signature,
            verifier=request_verifier,
            now_provider=parent._SequenceClock(
                [
                    "2026-09-12T19:11:00Z",
                    "2026-09-12T19:11:01Z",
                    "2026-09-12T19:11:02Z",
                ]
            ),
        )
        assert reservation.transaction_authenticated is True
        parsed_reservation = PhysicalQualificationReservation.from_mapping(reservation.to_dict())
        assert parsed_reservation.transaction_authenticated is False
        loaded_reservation = _PhysicalQualificationRequestLedger(
            reservation_ledger_root
        ).load(request.sha256)
        assert loaded_reservation.transaction_authenticated is False
        assert reservation_host_scope_sha256(reservation) == reservation_host_scope_sha256(
            parsed_reservation
        )

        runner_rel = "scripts/rsi-dc-l15-runner-fixture.py"
        runner_path = repository_root / "scripts" / "rsi-dc-l15-runner-fixture.py"
        runner_path.parent.mkdir()
        runner_bytes = b"print('dc-l15 physical runner fixture')\n"
        runner_path.write_bytes(runner_bytes)
        runner_sha = hashlib.sha256(runner_bytes).hexdigest()
        runner_authorization = build_physical_campaign_runner_authorization(
            reservation=reservation,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            authorization_id="rsi-runner-auth-001",
            campaign_id="rsi-dc-l15-campaign-001",
            runner_relative_path=runner_rel,
            runner_sha256=runner_sha,
            runner_bytes=len(runner_bytes),
            authorized_at_utc="2026-09-12T19:11:05Z",
            expires_at_utc="2026-09-12T19:14:59Z",
        )
        assert runner_authorization.required_probes == tuple(
            probe.value for probe in REQUIRED_PROBES
        )
        assert runner_authorization.required_operator_actor_id == reservation.collector_actor_id
        assert runner_authorization.required_approver_actor_id == reservation.approver_actor_id
        runner_signature, runner_verifier = _sign_runner_authorization(runner_authorization)

        # Unsigned/serialized payloads alone never grant campaign authority.
        assert PhysicalCampaignRunnerAuthorization.from_mapping(
            runner_authorization.to_dict()
        ).canonical_json() == runner_authorization.canonical_json()
        _expect(
            "transaction-authenticated reservation object",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=_fresh_dir(root, "parsed-reservation-admission-ledger"),
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "parsed-reservation-admission-operation"),
                reservation=parsed_reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=runner_signature,
                verifier=runner_verifier,
                now_provider=parent._SequenceClock(["2026-09-12T19:11:10Z"]),
            ),
        )

        admission_ledger_root = _fresh_dir(root, "admission-ledger")
        admission = _issue_physical_campaign_admission_once(
            ledger_root=admission_ledger_root,
            trusted_git=trusted_git,
            repository_root=repository_root,
            operation_root=_fresh_dir(root, "admission-operation"),
            reservation=reservation,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            runner_authorization=runner_authorization,
            runner_signature=runner_signature,
            verifier=runner_verifier,
            now_provider=parent._SequenceClock(
                [
                    "2026-09-12T19:11:10Z",
                    "2026-09-12T19:11:11Z",
                    "2026-09-12T19:11:12Z",
                ]
            ),
        )
        assert admission.transaction_authenticated is True
        assert admission.campaign_start_authorized is True
        assert admission.human_runner_pin_verified is True
        assert admission.host_admission_guard_committed is True
        assert admission.manual_operator_required is True
        assert admission.single_campaign_only is True
        assert admission.automatic_start is False
        assert admission.physical_campaign_completed is False
        assert admission.post_campaign_main_observation_required is True
        assert admission.frozen_main_confirmed is False
        assert admission.global_replay_safe is False
        assert admission.pilot_go_authorized is False
        assert admission.activation_authorized is False
        assert admission.remote_publication_authorized is False
        assert admission.required_probes == tuple(probe.value for probe in REQUIRED_PROBES)
        assert admission.runner_sha256 == runner_sha
        assert admission.runner_bytes == len(runner_bytes)
        assert admission.task_sha256 == qualification.task_sha256
        assert admission.base_sha == qualification.base_sha
        parsed_admission = PhysicalCampaignAdmission.from_mapping(admission.to_dict())
        assert parsed_admission.transaction_authenticated is False
        loaded_admission = _PhysicalCampaignAdmissionLedger(admission_ledger_root).load(
            reservation.sha256
        )
        assert loaded_admission.transaction_authenticated is False
        assert loaded_admission.canonical_json() == admission.canonical_json()

        # Schema properties stay exact with canonical runtime artifacts.
        assert _schema_properties("rsi-physical-campaign-runner-authorization-v1.schema.json") == set(
            runner_authorization.to_dict()
        )
        assert _schema_properties("rsi-physical-campaign-admission-v1.schema.json") == set(
            admission.to_dict()
        )

        # Same host-local reservation cannot mint a second admission in the same
        # canonical ledger scope.
        _expect(
            "already has a host-local campaign admission",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=admission_ledger_root,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "duplicate-admission-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=runner_signature,
                verifier=runner_verifier,
                now_provider=parent._SequenceClock(
                    [
                        "2026-09-12T19:11:20Z",
                        "2026-09-12T19:11:21Z",
                        "2026-09-12T19:11:22Z",
                    ]
                ),
            ),
        )

        # Correct crypto under the wrong authority system is still unauthorized.
        foreign_signature, foreign_verifier = _sign_runner_authorization(
            runner_authorization, issuer_system_id="some-other-runner-authority"
        )
        _expect(
            "another authority system",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=_fresh_dir(root, "foreign-authority-ledger"),
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "foreign-authority-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=foreign_signature,
                verifier=foreign_verifier,
                now_provider=parent._SequenceClock(["2026-09-12T19:11:30Z"]),
            ),
        )

        # A signed authorization for another host scope cannot attach to this
        # authenticated reservation even when the signature itself is valid.
        wrong_scope_map = runner_authorization.to_dict()
        wrong_scope_map["host_scope_sha256"] = "0" * 64
        wrong_scope = PhysicalCampaignRunnerAuthorization.from_mapping(wrong_scope_map)
        wrong_scope_signature, wrong_scope_verifier = _sign_runner_authorization(wrong_scope)
        _expect(
            "not bound to the authenticated reservation/qualification chain",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=_fresh_dir(root, "wrong-scope-ledger"),
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "wrong-scope-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=wrong_scope,
                runner_signature=wrong_scope_signature,
                verifier=wrong_scope_verifier,
                now_provider=parent._SequenceClock(["2026-09-12T19:11:31Z"]),
            ),
        )

        # A payload changed after signing fails cryptographically. authorization_id
        # is intentionally outside chain binding, so this reaches signature verify.
        tampered_payload_map = runner_authorization.to_dict()
        tampered_payload_map["authorization_id"] = "rsi-runner-auth-tampered"
        tampered_payload = PhysicalCampaignRunnerAuthorization.from_mapping(tampered_payload_map)
        _expect(
            "authority verification failed",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=_fresh_dir(root, "tampered-signature-ledger"),
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "tampered-signature-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=tampered_payload,
                runner_signature=runner_signature,
                verifier=runner_verifier,
                now_provider=parent._SequenceClock(["2026-09-12T19:11:32Z"]),
            ),
        )

        # Runner bytes are authority: changing them before lock blocks admission.
        runner_path.write_bytes(b"tampered runner\n")
        _expect(
            "runner byte count changed",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=_fresh_dir(root, "runner-tamper-ledger"),
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "runner-tamper-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=runner_signature,
                verifier=runner_verifier,
                now_provider=parent._SequenceClock(["2026-09-12T19:11:33Z"]),
            ),
        )
        runner_path.write_bytes(runner_bytes)

        # Moving main after admission lock leaves a recovery-required lock rather
        # than re-opening the authority path.
        move_main_ledger = _fresh_dir(root, "move-main-ledger")
        original_main = (repository_root / ".modelrig-main-sha").read_text(encoding="ascii")

        def move_main(call: int) -> None:
            if call == 2:
                (repository_root / ".modelrig-main-sha").write_text("e" * 40 + "\n", encoding="ascii")

        _expect(
            "pre-start main head does not match",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=move_main_ledger,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "move-main-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=runner_signature,
                verifier=runner_verifier,
                now_provider=parent._SequenceClock(
                    ["2026-09-12T19:11:40Z", "2026-09-12T19:11:41Z"],
                    mutate=move_main,
                ),
            ),
        )
        _expect(
            "host-locally consumed but requires recovery",
            lambda: _PhysicalCampaignAdmissionLedger(move_main_ledger).load(reservation.sha256),
        )
        (repository_root / ".modelrig-main-sha").write_text(original_main, encoding="ascii")

        # Runner changing after lock is equally terminal and recovery-required.
        runner_move_ledger = _fresh_dir(root, "runner-move-ledger")

        def move_runner(call: int) -> None:
            if call == 2:
                runner_path.write_bytes(b"runner changed after lock\n")

        _expect(
            "runner byte count changed",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=runner_move_ledger,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "runner-move-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=runner_signature,
                verifier=runner_verifier,
                now_provider=parent._SequenceClock(
                    ["2026-09-12T19:11:50Z", "2026-09-12T19:11:51Z"],
                    mutate=move_runner,
                ),
            ),
        )
        _expect(
            "host-locally consumed but requires recovery",
            lambda: _PhysicalCampaignAdmissionLedger(runner_move_ledger).load(reservation.sha256),
        )
        runner_path.write_bytes(runner_bytes)

        # Authorization expiry crossed after lock must not reopen the reservation.
        expiring = build_physical_campaign_runner_authorization(
            reservation=reservation,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            authorization_id="rsi-runner-auth-expiring",
            campaign_id="rsi-dc-l15-campaign-expiring",
            runner_relative_path=runner_rel,
            runner_sha256=runner_sha,
            runner_bytes=len(runner_bytes),
            authorized_at_utc="2026-09-12T19:12:00Z",
            expires_at_utc="2026-09-12T19:12:02Z",
        )
        expiring_signature, expiring_verifier = _sign_runner_authorization(
            expiring, signed_at_utc="2026-09-12T19:12:00Z"
        )
        expiry_ledger = _fresh_dir(root, "expiry-ledger")
        _expect(
            "not currently valid",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=expiry_ledger,
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "expiry-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=expiring,
                runner_signature=expiring_signature,
                verifier=expiring_verifier,
                now_provider=parent._SequenceClock(
                    [
                        "2026-09-12T19:12:01Z",
                        "2026-09-12T19:12:02Z",
                        "2026-09-12T19:12:03Z",
                    ]
                ),
            ),
        )
        _expect(
            "host-locally consumed but requires recovery",
            lambda: _PhysicalCampaignAdmissionLedger(expiry_ledger).load(reservation.sha256),
        )

        # A stale reservation cannot be revived by a new runner authorization.
        stale_auth = build_physical_campaign_runner_authorization(
            reservation=reservation,
            qualification=qualification,
            snapshot_receipt=snapshot_receipt,
            authorization_id="rsi-runner-auth-stale-parent",
            campaign_id="rsi-dc-l15-campaign-stale-parent",
            runner_relative_path=runner_rel,
            runner_sha256=runner_sha,
            runner_bytes=len(runner_bytes),
            authorized_at_utc="2026-09-12T19:26:00Z",
            expires_at_utc="2026-09-12T19:29:00Z",
        )
        stale_signature, stale_verifier = _sign_runner_authorization(
            stale_auth, signed_at_utc="2026-09-12T19:26:00Z"
        )
        _expect(
            "reservation is stale at admission",
            lambda: _issue_physical_campaign_admission_once(
                ledger_root=_fresh_dir(root, "stale-parent-ledger"),
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=_fresh_dir(root, "stale-parent-operation"),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=stale_auth,
                runner_signature=stale_signature,
                verifier=stale_verifier,
                now_provider=parent._SequenceClock(["2026-09-12T19:26:30Z"]),
            ),
        )

        # Serialized authority escalation and probe drift remain impossible.
        elevated = admission.to_dict()
        elevated["pilot_go_authorized"] = True
        _expect(
            "authority boundary is invalid",
            lambda: PhysicalCampaignAdmission.from_mapping(elevated),
        )
        global_claim = admission.to_dict()
        global_claim["global_replay_safe"] = True
        _expect(
            "authority boundary is invalid",
            lambda: PhysicalCampaignAdmission.from_mapping(global_claim),
        )
        probe_drift = runner_authorization.to_dict()
        probe_drift["required_probes"] = probe_drift["required_probes"][:-1]
        _expect(
            "exact DC-L15 probe set",
            lambda: PhysicalCampaignRunnerAuthorization.from_mapping(probe_drift),
        )
        for bad_path in ("../runner.py", "/tmp/runner.py", "scripts\\runner.py", "C:/runner.py"):
            mapping = runner_authorization.to_dict()
            mapping["runner_relative_path"] = bad_path
            _expect(
                "runner_relative_path is invalid",
                lambda mapping=mapping: PhysicalCampaignRunnerAuthorization.from_mapping(mapping),
            )

        # Canonical persisted admission bytes are fail-closed against tampering.
        final_path = admission_ledger_root / f"{reservation.sha256}.json"
        final_path.write_bytes(admission.canonical_json().encode("utf-8") + b"\n")
        _expect(
            "not canonical",
            lambda: _PhysicalCampaignAdmissionLedger(admission_ledger_root).load(
                reservation.sha256
            ),
        )
