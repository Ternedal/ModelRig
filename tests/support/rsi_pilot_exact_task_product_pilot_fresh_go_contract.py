"""Adversarial contract for ADR-DC-099 fresh human product-pilot GO."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control.asymmetric_authority import Ed25519AuthorityVerifier  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_fresh_go as fresh_go  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_lineage_attestation as lineage  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_post_production_activation_attestation as post  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_product_pilot_fresh_go_production_boundary as fresh_go_boundary  # noqa: E402
import rsi_human_pilot_decision_production_boundary as human_contract  # noqa: E402
import rsi_pilot_exact_task_product_pilot_lineage_attestation_contract as lineage_contract  # noqa: E402

CLAIM_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-fresh-go-claim-v1.schema.json"
)
PROOF_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-product-pilot-fresh-go-proof-v1.schema.json"
)
IMPL = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "_improvement_pilot_exact_task_product_pilot_fresh_go_impl.py"
)
BOUNDARY = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "_improvement_pilot_exact_task_product_pilot_fresh_go_production_boundary.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError, AttributeError):
        return
    raise AssertionError("ADR-DC-099 unexpectedly accepted unsafe human GO")


def _claim(lineage_receipt, post_receipt, **overrides):
    values = dict(
        product_pilot_lineage_attestation=lineage_receipt,
        post_production_activation_attestation=post_receipt,
        decision_id="product-pilot-go-099",
        decision_maker_actor_id="product.pilot.owner",
        decided_at_utc="2026-09-15T09:54:05Z",
        expires_at_utc="2026-09-15T09:59:05Z",
    )
    values.update(overrides)
    return fresh_go.build_pilot_exact_task_product_pilot_fresh_go_claim(**values)


def _authority(claim):
    private_key, key = human_contract._trusted_key(
        actor=claim.decision_maker_actor_id
    )
    signature = human_contract._sign(claim, private_key, key)
    verifier = Ed25519AuthorityVerifier(
        {key.key_id: key},
        minimum_keyring_epoch=1,
    )
    return verifier, signature


def _verify(claim, signature, verifier, lineage_receipt, post_receipt, *, now="2026-09-15T09:54:06Z"):
    return fresh_go._verify_pilot_exact_task_product_pilot_fresh_go(
        claim=claim,
        signature=signature,
        product_pilot_lineage_attestation=lineage_receipt,
        post_production_activation_attestation=post_receipt,
        verifier=verifier,
        now_provider=lambda: now,
    )


def _assert_inert(proof) -> None:
    assert proof.fresh_product_pilot_go_verified is True
    assert proof.exact_lineage_bound is True
    assert proof.exact_requirements_bound is True
    assert proof.exact_pilot_scope_bound is True
    assert proof.next_boundary_readiness_required is True
    for field in (
        "product_pilot_start_ready",
        "product_pilot_start_authorized",
        "product_pilot_started",
        "task_execution_authorized",
        "local_commit_authorized",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
        "nonce_reusable",
    ):
        assert getattr(proof, field) is False, field


def run_contract() -> None:
    if os.name == "nt":
        return

    fixture = lineage_contract._build_fixture()
    try:
        lineage_receipt = lineage_contract._attest(fixture)
        post_receipt = fixture["post_production"]

        claim = _claim(lineage_receipt, post_receipt)
        assert claim.product_pilot_lineage_attestation_sha256 == lineage_receipt.sha256
        assert (
            claim.historical_human_go_proof_sha256
            == lineage_receipt.human_decision_proof_sha256
        )
        assert (
            claim.production_activation_candidate_sha256
            == lineage_receipt.production_activation_candidate_sha256
            == post_receipt.production_activation_candidate_sha256
        )
        assert claim.execution_nonce_sha256 == lineage_receipt.execution_nonce_sha256
        assert claim.operator_surface == lineage_receipt.operator_surface
        assert claim.selected_pilot_task_id == lineage_receipt.selected_pilot_task_id
        assert (
            claim.workspace_root_path_sha256
            == lineage_receipt.workspace_root_path_sha256
        )
        assert claim.feature_flag_name == lineage_receipt.feature_flag_name
        assert claim.product_route == lineage_receipt.product_route
        assert claim.decision == "go"
        assert claim.local_commits_allowed is False
        assert claim.remote_write_allowed is False
        assert claim.unattended_cadence_allowed is False
        assert claim.product_pilot_start_ready is False
        assert claim.product_pilot_start_authorized is False
        assert claim.product_pilot_started is False

        verifier, signature = _authority(claim)
        proof = _verify(
            claim,
            signature,
            verifier,
            lineage_receipt,
            post_receipt,
        )
        assert proof.claim == claim
        assert proof.claim_sha256 == claim.sha256
        assert proof.signature_sha256 == signature.sha256
        assert proof.go_authenticated is True
        _assert_inert(proof)

        serialized = fresh_go.PilotExactTaskProductPilotFreshGoProof.from_mapping(
            proof.to_dict()
        )
        assert serialized == proof
        assert serialized.sha256 == proof.sha256
        assert serialized.go_authenticated is False

        with patch.object(
            fresh_go_boundary,
            "_canonical_human_pilot_decision_verifier",
            return_value=verifier,
        ):
            production_proof = fresh_go.verify_pilot_exact_task_product_pilot_fresh_go(
                claim=claim,
                signature=signature,
                product_pilot_lineage_attestation=lineage_receipt,
                post_production_activation_attestation=post_receipt,
            )
        assert production_proof.go_authenticated is True
        assert production_proof.sha256 == proof.sha256

        _reject(
            lambda: fresh_go.verify_pilot_exact_task_product_pilot_fresh_go(
                claim=claim,
                signature=signature,
                product_pilot_lineage_attestation=lineage_receipt,
                post_production_activation_attestation=post_receipt,
                verifier=verifier,
            )
        )

        stale_post = post.PilotExactTaskPostProductionActivationAttestationReceipt.from_mapping(
            post_receipt.to_dict()
        )
        assert stale_post.attestation_authenticated is False
        _reject(lambda: _claim(lineage_receipt, stale_post))
        _reject(
            lambda: _verify(
                claim,
                signature,
                verifier,
                lineage_receipt,
                stale_post,
            )
        )

        wrong_lineage_raw = lineage_receipt.to_dict()
        wrong_lineage_raw["production_activation_candidate_sha256"] = (
            "f" * 64
            if lineage_receipt.production_activation_candidate_sha256 != "f" * 64
            else "e" * 64
        )
        wrong_lineage = lineage.PilotExactTaskProductPilotLineageAttestationReceipt.from_mapping(
            wrong_lineage_raw
        )
        _reject(lambda: _claim(wrong_lineage, post_receipt))
        _reject(
            lambda: _verify(
                claim,
                signature,
                verifier,
                wrong_lineage,
                post_receipt,
            )
        )

        _reject(
            lambda: _claim(
                lineage_receipt,
                post_receipt,
                decided_at_utc="2026-09-15T09:53:59Z",
            )
        )
        _reject(
            lambda: _claim(
                lineage_receipt,
                post_receipt,
                expires_at_utc="2026-09-15T09:59:06Z",
            )
        )
        _reject(
            lambda: _verify(
                claim,
                signature,
                verifier,
                lineage_receipt,
                post_receipt,
                now="2026-09-15T09:59:06Z",
            )
        )

        tampered_raw = claim.to_dict()
        tampered_raw["selected_pilot_task_id"] = "other.task"
        tampered = fresh_go.PilotExactTaskProductPilotFreshGoClaim.from_mapping(
            tampered_raw
        )
        _reject(
            lambda: _verify(
                tampered,
                signature,
                verifier,
                lineage_receipt,
                post_receipt,
            )
        )

        for field, value in (
            ("decision", "no_go"),
            ("local_commits_allowed", True),
            ("remote_write_allowed", True),
            ("unattended_cadence_allowed", True),
            ("product_pilot_start_ready", True),
            ("product_pilot_start_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            raw = claim.to_dict()
            raw[field] = value
            _reject(
                lambda raw=raw: (
                    fresh_go.PilotExactTaskProductPilotFreshGoClaim.from_mapping(raw)
                )
            )

        for field in (
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "task_execution_authorized",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        ):
            raw = proof.to_dict()
            raw[field] = True
            _reject(
                lambda raw=raw: (
                    fresh_go.PilotExactTaskProductPilotFreshGoProof.from_mapping(raw)
                )
            )
    finally:
        lineage_contract._cleanup(fixture)

    claim_schema = json.loads(CLAIM_SCHEMA.read_text(encoding="utf-8"))
    proof_schema = json.loads(PROOF_SCHEMA.read_text(encoding="utf-8"))
    claim_fields = set(
        fresh_go.PilotExactTaskProductPilotFreshGoClaim.__dataclass_fields__
    )
    proof_fields = set(
        fresh_go.PilotExactTaskProductPilotFreshGoProof.__dataclass_fields__
    )
    assert set(claim_schema["properties"]) == claim_fields
    assert set(claim_schema["required"]) == claim_fields
    assert claim_schema["additionalProperties"] is False
    assert set(proof_schema["properties"]) == proof_fields
    assert set(proof_schema["required"]) == proof_fields
    assert proof_schema["additionalProperties"] is False
    assert set(proof_schema["properties"]["claim"]["properties"]) == claim_fields

    build_public = inspect.signature(
        fresh_go.build_pilot_exact_task_product_pilot_fresh_go_claim
    )
    assert tuple(build_public.parameters) == (
        "product_pilot_lineage_attestation",
        "post_production_activation_attestation",
        "decision_id",
        "decision_maker_actor_id",
        "decided_at_utc",
        "expires_at_utc",
    )
    verify_public = inspect.signature(
        fresh_go.verify_pilot_exact_task_product_pilot_fresh_go
    )
    assert tuple(verify_public.parameters) == (
        "claim",
        "signature",
        "product_pilot_lineage_attestation",
        "post_production_activation_attestation",
        "verifier",
    )
    assert verify_public.parameters["verifier"].default is None

    impl_source = code_of(IMPL)
    boundary_source = code_of(BOUNDARY)
    for source in (impl_source, boundary_source):
        for forbidden in (
            "subprocess.",
            "urllib.",
            "requests.",
            "http.client",
            "create_once_file",
            ".write_text(",
            ".write_bytes(",
            ".unlink(",
            ".rename(",
            "Ed25519PrivateKey",
        ):
            assert forbidden not in source
    assert "_canonical_human_pilot_decision_verifier" in boundary_source
    assert "product_pilot_start_ready: bool = False" in impl_source
    assert "product_pilot_start_authorized: bool = False" in impl_source
    assert "product_pilot_started: bool = False" in impl_source


if __name__ == "__main__":
    run_contract()
