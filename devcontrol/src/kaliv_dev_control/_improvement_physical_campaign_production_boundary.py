"""Production trust-root and host-runtime boundary for DC-L15 campaign admission.

The private admission transaction remains injectable for deterministic adversarial
tests. Production must not trust a caller-selected Ed25519 verifier or execute
Trusted-Git from a same-user mutable staging tree. This installer therefore wraps
the public campaign-admission facade with two fixed host-controlled inputs:

* a verification-only runner-authority keyring at a canonical administrator-
  controlled path; and
* the exact host-controlled TrustedGitRuntime already pinned by the signed
  qualification/reservation chain.

The host runtime is executed directly through the restricted read-only Git reader.
A process-owned sentinel directory exists only to satisfy the private transaction's
cleanup contract; no executable/runtime bytes are copied into it.
"""
from __future__ import annotations

import contextvars
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_runtime_host_control import (
    PhysicalHostRuntimeError,
    _HostControlledPhysicalGitReader,
    _require_host_controlled_physical_git_runtime,
)
from .asymmetric_authority import (
    AsymmetricAuthorityError,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)
from . import improvement_physical_reservation as reservation_module
from .trusted_git_runtime_model import _has_linkish_component
from .trusted_git_runtime_staging import TrustedGitRuntime

RUNNER_AUTHORITY_KEYRING_SCHEMA = (
    "kaliv-rsi-physical-campaign-runner-authority-keyring/v1"
)
RUNNER_AUTHORITY_DOMAIN = "rsi-dc-l15-physical-campaign-runner"
RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID = "kaliv-rsi-dc-l15-runner-authority-v1"
_KEYRING_FIELDS = {
    "schema",
    "authority_domain",
    "minimum_keyring_epoch",
    "trusted_keys",
}
_PRODUCTION_CAMPAIGN_CONTEXT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "rsi_physical_campaign_production_context",
    default=False,
)


class PhysicalCampaignProductionBoundaryError(ValueError):
    """Production campaign authority inputs are unavailable or not host controlled."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring is not canonical JSON"
        ) from exc


def _canonical_physical_campaign_runner_authority_keyring_path() -> Path:
    """Return the fixed host-admin runner trust-root path."""

    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-physical-campaign-runner-authority-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-physical-campaign-runner-authority-keyring-v1.json"
        )
    raise PhysicalCampaignProductionBoundaryError(
        "physical campaign runner authority keyring is unsupported on this platform"
    )


def _load_physical_campaign_runner_authority_verifier_at(
    path: Path,
    *,
    require_host_control: bool = True,
) -> Ed25519AuthorityVerifier:
    """Load one exact public runner keyring; never caller-selected in production."""

    try:
        payload = _read_keyring_bytes(
            path,
            require_host_control=require_host_control,
        )
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring fields mismatch"
        )
    if value.get("schema") != RUNNER_AUTHORITY_KEYRING_SCHEMA:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring schema is unsupported"
        )
    if value.get("authority_domain") != RUNNER_AUTHORITY_DOMAIN:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring belongs to another authority domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if (
        not isinstance(minimum_epoch, int)
        or isinstance(minimum_epoch, bool)
        or minimum_epoch < 1
    ):
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring must contain trusted public keys"
        )

    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID:
                raise PhysicalCampaignProductionBoundaryError(
                    "physical campaign runner authority key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise PhysicalCampaignProductionBoundaryError(
                    "physical campaign runner authority keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except PhysicalCampaignProductionBoundaryError:
        raise
    except (AsymmetricAuthorityError, AttributeError, TypeError, ValueError) as exc:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring contains invalid public-key evidence"
        ) from exc

    canonical_mapping = {
        "schema": RUNNER_AUTHORITY_KEYRING_SCHEMA,
        "authority_domain": RUNNER_AUTHORITY_DOMAIN,
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign runner authority keyring is not canonical"
        )
    return verifier


def _canonical_physical_campaign_runner_authority_verifier() -> Ed25519AuthorityVerifier:
    """Resolve the production runner trust root from fixed host-admin state."""

    return _load_physical_campaign_runner_authority_verifier_at(
        _canonical_physical_campaign_runner_authority_keyring_path(),
        require_host_control=True,
    )


def install_physical_campaign_production_boundary(implementation: Any) -> None:
    """Install a production-only host trust/runtime facade around the private seam."""

    if implementation is None:
        raise PhysicalCampaignProductionBoundaryError(
            "physical campaign admission implementation is unavailable"
        )
    if getattr(implementation, "_production_campaign_boundary_installed", False):
        return

    original_snapshot = implementation._snapshot_trusted_git_runtime
    original_observe = implementation.observe_local_main_head
    private_issue = implementation._issue_physical_campaign_admission_once

    def snapshot_runtime(
        trusted_git: TrustedGitRuntime,
        *,
        operation_root: Path,
    ) -> tuple[TrustedGitRuntime, Path]:
        if not _PRODUCTION_CAMPAIGN_CONTEXT.get():
            return original_snapshot(trusted_git, operation_root=operation_root)
        runtime = _require_host_controlled_physical_git_runtime(trusted_git)
        operation = Path(operation_root)
        if (
            not operation.is_absolute()
            or not operation.is_dir()
            or _has_linkish_component(operation)
        ):
            raise PhysicalCampaignProductionBoundaryError(
                "physical campaign Git operation root is unsafe"
            )
        cleanup_root = Path(
            tempfile.mkdtemp(prefix=".rsi-campaign-host-runtime-sentinel-", dir=operation)
        ).resolve()
        if _has_linkish_component(cleanup_root):
            raise PhysicalCampaignProductionBoundaryError(
                "physical campaign host-runtime cleanup sentinel is unsafe"
            )
        return runtime, cleanup_root

    def observe_local_main_head(
        *,
        trusted_git: TrustedGitRuntime,
        repository_root: Path,
        operation_root: Path,
        observed_at_utc: str,
        repository: str = "Ternedal/ModelRig",
    ) -> Any:
        if not _PRODUCTION_CAMPAIGN_CONTEXT.get():
            return original_observe(
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=operation_root,
                observed_at_utc=observed_at_utc,
                repository=repository,
            )
        del operation_root
        runtime = _require_host_controlled_physical_git_runtime(trusted_git)
        manifest = runtime.receipt.manifest
        executable = next(
            item
            for item in manifest.files
            if item.relative_path == manifest.executable_relative_path
        )
        observation = reservation_module._observe_with_reader(
            reader=_HostControlledPhysicalGitReader(runtime),
            repository_root=repository_root,
            repository=repository,
            observed_at_utc=observed_at_utc,
            git_runtime_manifest_sha256=manifest.sha256,
            git_executable_sha256=executable.sha256,
        )
        _require_host_controlled_physical_git_runtime(runtime)
        return observation

    def issue_physical_campaign_admission_once(
        *,
        trusted_git: TrustedGitRuntime,
        reservation: Any,
        qualification: Any,
        snapshot_receipt: Any,
        runner_authorization: Any,
        runner_signature: Any,
        verifier: Ed25519AuthorityVerifier | None = None,
    ) -> Any:
        """Production facade; caller verifier is compatibility-only and never trusted."""

        if verifier is not None:
            raise implementation.PhysicalCampaignAdmissionError(
                "caller-selected campaign runner verifier is not production authority"
            )
        try:
            host_verifier = _canonical_physical_campaign_runner_authority_verifier()
            runtime = _require_host_controlled_physical_git_runtime(trusted_git)
        except (PhysicalCampaignProductionBoundaryError, PhysicalHostRuntimeError) as exc:
            raise implementation.PhysicalCampaignAdmissionError(
                "host-controlled physical campaign authority state is unavailable"
            ) from exc

        token = _PRODUCTION_CAMPAIGN_CONTEXT.set(True)
        try:
            return private_issue(
                ledger_root=implementation._canonical_campaign_ledger_root(),
                trusted_git=runtime,
                repository_root=implementation._canonical_repository_root(),
                operation_root=implementation._canonical_campaign_operation_root(),
                reservation=reservation,
                qualification=qualification,
                snapshot_receipt=snapshot_receipt,
                runner_authorization=runner_authorization,
                runner_signature=runner_signature,
                verifier=host_verifier,
                now_provider=implementation._now_utc_seconds,
            )
        except PhysicalHostRuntimeError as exc:
            raise implementation.PhysicalCampaignAdmissionError(
                "host-controlled physical campaign Git runtime is unavailable"
            ) from exc
        finally:
            _PRODUCTION_CAMPAIGN_CONTEXT.reset(token)

    implementation._snapshot_trusted_git_runtime = snapshot_runtime
    implementation.observe_local_main_head = observe_local_main_head
    implementation.issue_physical_campaign_admission_once = (
        issue_physical_campaign_admission_once
    )
    implementation._production_campaign_boundary_installed = True


__all__: list[str] = []
