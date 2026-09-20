"""Adversarial contract for ADR-DC-100 fresh product-pilot runtime preflight."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from source_code import code_of  # noqa: E402
from kaliv_dev_control.asymmetric_authority import (  # noqa: E402
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control.improvement_pilot_runtime_preflight_attestation import (  # noqa: E402
    PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID,
)
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_runtime_preflight as runtime  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_task_registry as registry  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_task_registry_contract as registry_contract  # noqa: E402

CLAIM_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-product-pilot-runtime-preflight-attestation-v1.schema.json"
RECEIPT_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-product-pilot-runtime-preflight-receipt-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_product_pilot_runtime_preflight.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-100 unexpectedly accepted unsafe runtime preflight")


def _evidence() -> dict[str, str]:
    return {
        name: hashlib.sha256(("adr-dc-100:" + name).encode("utf-8")).hexdigest()
        for name in runtime.EVIDENCE_FIELDS
    }


def _checks(*, all_green=True) -> dict[str, bool]:
    result = {name: True for name in runtime.CHECK_FIELDS}
    if not all_green:
        result["network_writes_blocked_verified"] = False
    return result


def _authority(claim):
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("64" * 32))
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="product-runtime-preflight-key-001",
        issuer_actor_id=claim.observer_actor_id,
        issuer_system_id=PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-15T00:00:00Z",
        valid_until_utc="2027-09-15T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=policy,
    )
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)
    payload = claim.canonical_json().encode("utf-8")
    message = authority_signing_message(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=policy,
        payload=payload,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=policy,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private.sign(message).hex(),
        signed_at_utc=claim.observed_at_utc,
    )
    return verifier, signature


def _registry_receipt(fixture):
    lineage_receipt = lineage_contract._attest(fixture)
    _completion, _decision, _signature, proof = registry_contract._fresh_go(
        fixture, lineage_receipt
    )
    payload, _task, _task_sha = registry_contract._host_registry(lineage_receipt)
    return registry_contract._build(lineage_receipt, proof, payload), lineage_receipt


def _claim(registry_receipt, *, all_green=True):
    return runtime.build_pilot_exact_task_product_pilot_runtime_preflight_attestation(
        task_registry_receipt=registry_receipt,
        observer_actor_id="host-observer",
        observer_host_id="modelrig-host-001",
        observed_at_utc="2026-09-15T09:54:30Z",
        evidence_sha256=_evidence(),
        checks=_checks(all_green=all_green),
    )


def run_contract(*, shared_fixture=None) -> None:
    if os.name == "nt":
        return

    owns_fixture = shared_fixture is None
    fixture = lineage_contract._build_fixture() if owns_fixture else shared_fixture
    try:
        registry_receipt, lineage_receipt = _registry_receipt(fixture)
        assert registry_receipt.registry_authenticated is True

        claim = _claim(registry_receipt)
        assert claim.task_registry_receipt_sha256 == registry_receipt.sha256
        assert claim.lineage_attestation_sha256 == lineage_receipt.sha256
        assert claim.all_checks_satisfied is True
        assert claim.runtime_preflight_satisfied is False
        assert claim.product_pilot_start_ready is False
        assert runtime.PilotExactTaskProductPilotRuntimePreflightAttestation.from_mapping(
            claim.to_dict()
        ) == claim

        verifier, signature = _authority(claim)
        receipt = runtime._verify_pilot_exact_task_product_pilot_runtime_preflight(
            task_registry_receipt=registry_receipt,
            attestation=claim,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-15T09:54:31Z",
        )
        assert receipt.preflight_authenticated is True
        assert receipt.runtime_preflight_satisfied is True
        assert receipt.product_pilot_start_ready is False
        assert receipt.product_pilot_start_authorized is False
        assert receipt.product_pilot_started is False
        assert receipt.task_execution_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.attestation_age_seconds == 1
        assert all(getattr(receipt, name) is True for name in runtime.CHECK_FIELDS)

        serialized = runtime.PilotExactTaskProductPilotRuntimePreflightReceipt.from_mapping(
            receipt.to_dict()
        )
        assert serialized == receipt
        assert serialized.preflight_authenticated is False

        bad_claim = _claim(registry_receipt, all_green=False)
        bad_verifier, bad_signature = _authority(bad_claim)
        _reject(
            lambda: runtime._verify_pilot_exact_task_product_pilot_runtime_preflight(
                task_registry_receipt=registry_receipt,
                attestation=bad_claim,
                signature=bad_signature,
                verifier=bad_verifier,
                now_provider=lambda: "2026-09-15T09:54:31Z",
            )
        )

        _reject(
            lambda: runtime._verify_pilot_exact_task_product_pilot_runtime_preflight(
                task_registry_receipt=registry_receipt,
                attestation=claim,
                signature=signature,
                verifier=verifier,
                now_provider=lambda: "2026-09-15T09:55:31Z",
            )
        )

        replayed_registry = registry.PilotExactTaskProductPilotTaskRegistryReceipt.from_mapping(
            registry_receipt.to_dict()
        )
        assert replayed_registry.registry_authenticated is False
        _reject(
            lambda: runtime.build_pilot_exact_task_product_pilot_runtime_preflight_attestation(
                task_registry_receipt=replayed_registry,
                observer_actor_id="host-observer",
                observer_host_id="modelrig-host-001",
                observed_at_utc="2026-09-15T09:54:30Z",
                evidence_sha256=_evidence(),
                checks=_checks(),
            )
        )

        raw = receipt.to_dict()
        raw["product_pilot_start_ready"] = True
        _reject(lambda: runtime.PilotExactTaskProductPilotRuntimePreflightReceipt.from_mapping(raw))
    finally:
        if owns_fixture:
            lineage_contract._cleanup(fixture)

    claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
    receipt_schema = json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8"))
    claim_fields = set(runtime.PilotExactTaskProductPilotRuntimePreflightAttestation.__dataclass_fields__)
    receipt_fields = set(runtime.PilotExactTaskProductPilotRuntimePreflightReceipt.__dataclass_fields__)
    assert set(claim_schema["properties"]) == claim_fields
    assert set(claim_schema["required"]) == claim_fields
    assert set(receipt_schema["properties"]) == receipt_fields
    assert set(receipt_schema["required"]) == receipt_fields

    public = inspect.signature(runtime.verify_pilot_exact_task_product_pilot_runtime_preflight)
    assert tuple(public.parameters) == (
        "task_registry_receipt",
        "attestation",
        "signature",
        "verifier",
    )
    source = code_of(SOURCE)
    for forbidden in (
        "subprocess.",
        "urllib.",
        "requests.",
        "http.client",
        ".write_text(",
        ".write_bytes(",
        ".unlink(",
        ".rename(",
    ):
        assert forbidden not in source


if __name__ == "__main__":
    run_contract()
