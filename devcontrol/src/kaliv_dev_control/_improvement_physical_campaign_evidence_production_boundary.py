"""Production trust/runtime boundary for post-DC-L15 physical evidence collection.

The underlying evidence collector intentionally keeps an injectable verifier and
transaction-private Trusted-Git staging seam for deterministic adversarial tests.
Those inputs are not production authority.  The public production facade instead
pins all mutable trust-bearing state to administrator-controlled host locations:

* the physical-report evidence root is fixed and host-admin controlled;
* the HMAC verification keyring is fixed, canonical and host-admin controlled;
* the exact TrustedGitRuntime must satisfy the hardened physical host-runtime
  boundary; and
* the post-campaign ``main`` observation uses the already-installed direct,
  read-only host-controlled Git reader.

The legacy DC-L04 report format uses HMAC.  A verifier that holds those HMAC
secrets has signing-equivalent capability, so this boundary deliberately grants
only ``verified-physical-evidence-only`` output.  It cannot establish exact runner
execution, continuous-main freeze, DC-L15 completion, pilot GO, publication,
merge, release, deploy or activation authority.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping

from . import improvement_physical_reservation as reservation_module
from ._improvement_physical_runtime_host_control import (
    PhysicalHostRuntimeError,
    _HostControlledPhysicalGitReader,
    _require_host_controlled_physical_git_runtime,
)
from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)
from .physical_isolation import PhysicalIsolationError, WindowsPhysicalIsolationVerifier
from .trusted_git_runtime_model import _has_linkish_component
from .trusted_git_runtime_staging import TrustedGitRuntime

PHYSICAL_EVIDENCE_KEYRING_SCHEMA = (
    "kaliv-rsi-physical-campaign-evidence-hmac-keyring/v1"
)
PHYSICAL_EVIDENCE_AUTHORITY_DOMAIN = "rsi-dc-l15-physical-campaign-evidence"
_KEYRING_FIELDS = {"schema", "authority_domain", "trusted_hmac_keys"}
_KEY_FIELDS = {"key_id", "secret_hex"}
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_HEX = re.compile(r"^[0-9a-f]+$")
_MAX_EVIDENCE_AGE = timedelta(minutes=15)
_PRODUCTION_EVIDENCE_CONTEXT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "rsi_physical_campaign_evidence_production_context",
    default=False,
)


class PhysicalCampaignEvidenceProductionBoundaryError(ValueError):
    """Production post-campaign evidence trust state is unavailable or unsafe."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical evidence HMAC keyring is not canonical JSON"
        ) from exc


def _canonical_physical_campaign_evidence_root_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\evidence\rsi-physical-campaign-evidence-v1"
        )
    if os.name == "posix":
        return Path("/var/lib/modelrig/devcontrol/rsi-physical-campaign-evidence-v1")
    raise PhysicalCampaignEvidenceProductionBoundaryError(
        "physical campaign evidence root is unsupported on this platform"
    )


def _canonical_physical_campaign_evidence_keyring_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-physical-campaign-evidence-hmac-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-physical-campaign-evidence-hmac-keyring-v1.json"
        )
    raise PhysicalCampaignEvidenceProductionBoundaryError(
        "physical campaign evidence keyring is unsupported on this platform"
    )


def _host_controlled_evidence_root(path: Path) -> Path:
    try:
        return _require_host_controlled_ledger_root(Path(path))
    except PhysicalHostStateError as exc:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence root is not host-admin controlled"
        ) from exc


def _load_physical_campaign_evidence_verifier_at(
    keyring_path: Path,
    evidence_root: Path,
    *,
    require_host_control: bool = True,
) -> WindowsPhysicalIsolationVerifier:
    """Load one exact HMAC verifier from fixed-format local trust state.

    This is intentionally a verification adapter for the legacy DC-L04 HMAC
    report format, not a new signing API.  Because HMAC is symmetric, possession
    of the verifier secrets is still signing-equivalent capability; downstream
    authority must therefore remain false until a separate asymmetric/human
    completion binding exists.
    """

    root = Path(evidence_root)
    if require_host_control:
        root = _host_controlled_evidence_root(root)
    elif not root.is_absolute() or not root.is_dir() or _has_linkish_component(root):
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence root is unsafe"
        )

    try:
        payload = _read_keyring_bytes(
            Path(keyring_path),
            require_host_control=require_host_control,
        )
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence HMAC keyring could not be read safely"
        ) from exc

    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence HMAC keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence HMAC keyring fields mismatch"
        )
    if value.get("schema") != PHYSICAL_EVIDENCE_KEYRING_SCHEMA:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence HMAC keyring schema is unsupported"
        )
    if value.get("authority_domain") != PHYSICAL_EVIDENCE_AUTHORITY_DOMAIN:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence HMAC keyring belongs to another authority domain"
        )
    raw_keys = value.get("trusted_hmac_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence HMAC keyring must contain trusted keys"
        )

    trusted: dict[str, bytes] = {}
    canonical_keys: list[dict[str, str]] = []
    previous: str | None = None
    for raw in raw_keys:
        if not isinstance(raw, Mapping) or set(raw) != _KEY_FIELDS:
            raise PhysicalCampaignEvidenceProductionBoundaryError(
                "physical campaign evidence HMAC key entry fields mismatch"
            )
        key_id = raw.get("key_id")
        secret_hex = raw.get("secret_hex")
        if not isinstance(key_id, str) or _KEY_ID.fullmatch(key_id) is None:
            raise PhysicalCampaignEvidenceProductionBoundaryError(
                "physical campaign evidence HMAC key id is invalid"
            )
        if previous is not None and key_id <= previous:
            raise PhysicalCampaignEvidenceProductionBoundaryError(
                "physical campaign evidence HMAC keys must be sorted and unique"
            )
        if (
            not isinstance(secret_hex, str)
            or len(secret_hex) < 64
            or len(secret_hex) > 8192
            or len(secret_hex) % 2 != 0
            or _HEX.fullmatch(secret_hex) is None
        ):
            raise PhysicalCampaignEvidenceProductionBoundaryError(
                "physical campaign evidence HMAC secret is invalid"
            )
        secret = bytes.fromhex(secret_hex)
        if not 32 <= len(secret) <= 4096:
            raise PhysicalCampaignEvidenceProductionBoundaryError(
                "physical campaign evidence HMAC secret is outside its bound"
            )
        previous = key_id
        trusted[key_id] = secret
        canonical_keys.append({"key_id": key_id, "secret_hex": secret_hex})

    canonical = {
        "schema": PHYSICAL_EVIDENCE_KEYRING_SCHEMA,
        "authority_domain": PHYSICAL_EVIDENCE_AUTHORITY_DOMAIN,
        "trusted_hmac_keys": canonical_keys,
    }
    if payload != _canonical_json(canonical):
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence HMAC keyring is not canonical"
        )
    try:
        return WindowsPhysicalIsolationVerifier(
            root,
            trusted,
            max_age=_MAX_EVIDENCE_AGE,
        )
    except PhysicalIsolationError as exc:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence verifier could not be constructed safely"
        ) from exc


def _canonical_physical_campaign_evidence_verifier() -> WindowsPhysicalIsolationVerifier:
    """Resolve fixed production physical-report trust state."""

    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence collection requires an elevated host operator"
        ) from exc
    return _load_physical_campaign_evidence_verifier_at(
        _canonical_physical_campaign_evidence_keyring_path(),
        _canonical_physical_campaign_evidence_root_path(),
        require_host_control=True,
    )


def install_physical_campaign_evidence_production_boundary(implementation: Any) -> None:
    """Install the host-pinned production facade around the injectable collector."""

    if implementation is None:
        raise PhysicalCampaignEvidenceProductionBoundaryError(
            "physical campaign evidence implementation is unavailable"
        )
    if getattr(implementation, "_production_evidence_boundary_installed", False):
        return

    original_snapshot = implementation._snapshot_trusted_git_runtime
    original_observe = implementation.observe_local_main_head
    private_collect = implementation._collect_physical_campaign_evidence

    def snapshot_runtime(
        trusted_git: TrustedGitRuntime,
        *,
        operation_root: Path,
    ) -> tuple[TrustedGitRuntime, Path]:
        if not _PRODUCTION_EVIDENCE_CONTEXT.get():
            return original_snapshot(trusted_git, operation_root=operation_root)
        runtime = _require_host_controlled_physical_git_runtime(trusted_git)
        operation = Path(operation_root)
        if (
            not operation.is_absolute()
            or not operation.is_dir()
            or _has_linkish_component(operation)
        ):
            raise PhysicalCampaignEvidenceProductionBoundaryError(
                "physical campaign evidence Git operation root is unsafe"
            )
        cleanup_root = Path(
            tempfile.mkdtemp(prefix=".rsi-evidence-host-runtime-sentinel-", dir=operation)
        ).resolve()
        if _has_linkish_component(cleanup_root):
            raise PhysicalCampaignEvidenceProductionBoundaryError(
                "physical campaign evidence host-runtime cleanup sentinel is unsafe"
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
        if not _PRODUCTION_EVIDENCE_CONTEXT.get():
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

    def collect_physical_campaign_evidence(
        *,
        trusted_git: TrustedGitRuntime,
        admission: Any,
        attestation: Any,
        verifier: WindowsPhysicalIsolationVerifier | None = None,
    ) -> Any:
        """Production facade; caller verifier is compatibility-only and rejected."""

        if verifier is not None:
            raise implementation.PhysicalCampaignEvidenceError(
                "caller-selected physical evidence verifier is not production authority"
            )
        try:
            host_verifier = _canonical_physical_campaign_evidence_verifier()
            runtime = _require_host_controlled_physical_git_runtime(trusted_git)
        except (
            PhysicalCampaignEvidenceProductionBoundaryError,
            PhysicalHostRuntimeError,
        ) as exc:
            raise implementation.PhysicalCampaignEvidenceError(
                "host-controlled physical campaign evidence state is unavailable"
            ) from exc

        token = _PRODUCTION_EVIDENCE_CONTEXT.set(True)
        try:
            return private_collect(
                trusted_git=runtime,
                repository_root=implementation._canonical_repository_root(),
                operation_root=implementation._canonical_evidence_operation_root(),
                admission=admission,
                attestation=attestation,
                verifier=host_verifier,
                now_provider=implementation._now_utc_seconds,
            )
        except PhysicalHostRuntimeError as exc:
            raise implementation.PhysicalCampaignEvidenceError(
                "host-controlled physical campaign evidence Git runtime is unavailable"
            ) from exc
        finally:
            _PRODUCTION_EVIDENCE_CONTEXT.reset(token)

    implementation._snapshot_trusted_git_runtime = snapshot_runtime
    implementation.observe_local_main_head = observe_local_main_head
    implementation.collect_physical_campaign_evidence = collect_physical_campaign_evidence
    implementation._production_evidence_boundary_installed = True


__all__: list[str] = []
