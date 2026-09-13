"""Adversarial contract for the ADR-DC-010 production-only trust/runtime boundary."""
from __future__ import annotations

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
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
)
import kaliv_dev_control._improvement_physical_campaign_production_boundary as boundary  # noqa: E402
import kaliv_dev_control.improvement_physical_campaign_admission as campaign  # noqa: E402


def _trusted_key(*, issuer_system_id: str = boundary.RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID):
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    key = TrustedEd25519AuthorityKey(
        key_id="rsi-dc-l15-runner-production-test-key",
        issuer_actor_id="anders.runner-authorizer",
        issuer_system_id=issuer_system_id,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-13T00:00:00Z",
        valid_until_utc="2026-09-14T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=asymmetric_authority_key_custody_policy_sha256(),
    )
    return key


def _canonical_keyring(key: TrustedEd25519AuthorityKey) -> bytes:
    return json.dumps(
        {
            "schema": boundary.RUNNER_AUTHORITY_KEYRING_SCHEMA,
            "authority_domain": boundary.RUNNER_AUTHORITY_DOMAIN,
            "minimum_keyring_epoch": 1,
            "trusted_keys": [key.to_dict()],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _expect_boundary_error(fragment: str, fn) -> None:
    try:
        fn()
    except boundary.PhysicalCampaignProductionBoundaryError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalCampaignProductionBoundaryError containing {fragment!r}"
        )


def _expect_campaign_error(fragment: str, fn) -> None:
    try:
        fn()
    except campaign.PhysicalCampaignAdmissionError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(
            f"expected PhysicalCampaignAdmissionError containing {fragment!r}"
        )


def run_contract() -> None:
    assert campaign._production_campaign_boundary_installed is True
    public = inspect.signature(campaign.issue_physical_campaign_admission_once)
    assert set(public.parameters) == {
        "trusted_git",
        "reservation",
        "qualification",
        "snapshot_receipt",
        "runner_authorization",
        "runner_signature",
        "verifier",
    }
    assert public.parameters["verifier"].default is None
    private = inspect.signature(campaign._issue_physical_campaign_admission_once)
    assert "verifier" in private.parameters

    key = _trusted_key()
    verifier = Ed25519AuthorityVerifier({key.key_id: key}, minimum_keyring_epoch=1)

    # The historical public verifier argument is compatibility-only: any caller
    # attempt to populate it fails before host state or transaction inputs matter.
    _expect_campaign_error(
        "caller-selected campaign runner verifier",
        lambda: campaign.issue_physical_campaign_admission_once(
            trusted_git=None,
            reservation=None,
            qualification=None,
            snapshot_receipt=None,
            runner_authorization=None,
            runner_signature=None,
            verifier=verifier,
        ),
    )

    with tempfile.TemporaryDirectory(prefix="rsi-runner-keyring-") as directory:
        root = Path(directory).resolve()
        path = root / "runner-keyring.json"
        payload = _canonical_keyring(key)
        path.write_bytes(payload)
        loaded = boundary._load_physical_campaign_runner_authority_verifier_at(
            path,
            require_host_control=False,
        )
        assert type(loaded) is Ed25519AuthorityVerifier
        assert set(loaded._trusted_keys) == {key.key_id}

        wrong_domain = json.loads(payload)
        wrong_domain["authority_domain"] = "another-domain"
        path.write_bytes(
            json.dumps(
                wrong_domain,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
        _expect_boundary_error(
            "another authority domain",
            lambda: boundary._load_physical_campaign_runner_authority_verifier_at(
                path,
                require_host_control=False,
            ),
        )

        wrong_issuer = _trusted_key(issuer_system_id="some-other-runner-authority")
        path.write_bytes(_canonical_keyring(wrong_issuer))
        _expect_boundary_error(
            "another issuer system",
            lambda: boundary._load_physical_campaign_runner_authority_verifier_at(
                path,
                require_host_control=False,
            ),
        )

        path.write_bytes(payload + b"\n")
        _expect_boundary_error(
            "not canonical",
            lambda: boundary._load_physical_campaign_runner_authority_verifier_at(
                path,
                require_host_control=False,
            ),
        )

    # Production snapshot mode retains the host-controlled runtime object itself;
    # only a disposable empty cleanup sentinel is created under operation state.
    original_require = boundary._require_host_controlled_physical_git_runtime
    dummy_runtime = object()
    boundary._require_host_controlled_physical_git_runtime = lambda value: value
    try:
        with tempfile.TemporaryDirectory(prefix="rsi-campaign-operation-") as directory:
            operation = Path(directory).resolve()
            token = boundary._PRODUCTION_CAMPAIGN_CONTEXT.set(True)
            try:
                observed_runtime, cleanup_root = campaign._snapshot_trusted_git_runtime(
                    dummy_runtime,
                    operation_root=operation,
                )
            finally:
                boundary._PRODUCTION_CAMPAIGN_CONTEXT.reset(token)
            assert observed_runtime is dummy_runtime
            assert cleanup_root.parent == operation
            assert cleanup_root.is_dir()
            assert list(cleanup_root.iterdir()) == []
            cleanup_root.rmdir()
    finally:
        boundary._require_host_controlled_physical_git_runtime = original_require

    # Missing/untrusted production runtime is normalized to the campaign boundary
    # and cannot fall through to the private caller-controlled staging seam.
    original_verifier = boundary._canonical_physical_campaign_runner_authority_verifier
    original_require = boundary._require_host_controlled_physical_git_runtime
    boundary._canonical_physical_campaign_runner_authority_verifier = lambda: verifier

    def reject_runtime(_value):
        raise boundary.PhysicalHostRuntimeError("test runtime is not host controlled")

    boundary._require_host_controlled_physical_git_runtime = reject_runtime
    try:
        _expect_campaign_error(
            "host-controlled physical campaign authority state is unavailable",
            lambda: campaign.issue_physical_campaign_admission_once(
                trusted_git=None,
                reservation=None,
                qualification=None,
                snapshot_receipt=None,
                runner_authorization=None,
                runner_signature=None,
            ),
        )
    finally:
        boundary._canonical_physical_campaign_runner_authority_verifier = original_verifier
        boundary._require_host_controlled_physical_git_runtime = original_require

    # Production keyring location is fixed and caller-independent.
    path = boundary._canonical_physical_campaign_runner_authority_keyring_path()
    if os.name == "nt":
        assert str(path).lower().startswith(r"c:\program files\modelrig\devcontrol\authority")
    elif os.name == "posix":
        assert path == Path(
            "/etc/modelrig/devcontrol/authority/rsi-physical-campaign-runner-authority-keyring-v1.json"
        )
