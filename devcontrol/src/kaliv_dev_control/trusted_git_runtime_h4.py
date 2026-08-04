"""Public H4 boundary for crash-durable trusted Git runtime publication."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .trusted_git_runtime_model import (
    TrustedGitRuntimeError,
    TrustedGitRuntimeManifest,
    _existing_link_free_directory,
    _transaction_id,
)
from .trusted_git_runtime_staging import (
    TRUSTED_GIT_RUNTIME_RECOVERY_SCHEMA,
    TrustedGitRuntime,
    TrustedGitRuntimeRecoveryReceipt,
    load_trusted_git_runtime_receipt,
    recover_trusted_git_runtime_transaction as _recover_transaction,
    stage_trusted_git_runtime as _stage_runtime,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


def stage_trusted_git_runtime(
    manifest: TrustedGitRuntimeManifest,
    *,
    source_root: Path,
    staging_root: Path,
) -> Path:
    """Reject pre-existing crash state before entering the staging transaction."""

    if not isinstance(manifest, TrustedGitRuntimeManifest):
        raise TrustedGitRuntimeError("Git runtime staging requires a manifest")
    destination = _existing_link_free_directory(
        staging_root, name="Git runtime staging root"
    )
    transaction_id = _transaction_id(manifest.sha256)
    pending = destination / f".{transaction_id}.pending"
    if pending.exists() or pending.is_symlink():
        raise TrustedGitRuntimeError(
            "Git runtime pending transaction requires explicit recovery"
        )
    return _stage_runtime(
        manifest,
        source_root=source_root,
        staging_root=destination,
    )


def recover_trusted_git_runtime_transaction(
    manifest: TrustedGitRuntimeManifest,
    *,
    staging_root: Path,
    action: str,
    recovery_authorization_sha256: str,
    operator_actor_id: str,
    recovered_at_utc: str,
) -> TrustedGitRuntimeRecoveryReceipt:
    """Validate explicit recovery authority before any filesystem mutation."""

    if not isinstance(recovery_authorization_sha256, str) or _HEX64.fullmatch(
        recovery_authorization_sha256
    ) is None:
        raise TrustedGitRuntimeError(
            "Git runtime recovery authorization hash is invalid"
        )
    if not isinstance(operator_actor_id, str) or _ACTOR.fullmatch(
        operator_actor_id
    ) is None:
        raise TrustedGitRuntimeError("Git runtime recovery operator is invalid")
    if not isinstance(recovered_at_utc, str) or _UTC.fullmatch(
        recovered_at_utc
    ) is None:
        raise TrustedGitRuntimeError("Git runtime recovery time is invalid")
    try:
        datetime.strptime(recovered_at_utc, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise TrustedGitRuntimeError("Git runtime recovery time is invalid") from exc
    return _recover_transaction(
        manifest,
        staging_root=staging_root,
        action=action,
        recovery_authorization_sha256=recovery_authorization_sha256,
        operator_actor_id=operator_actor_id,
        recovered_at_utc=recovered_at_utc,
    )


__all__ = [
    "TRUSTED_GIT_RUNTIME_RECOVERY_SCHEMA",
    "TrustedGitRuntime",
    "TrustedGitRuntimeRecoveryReceipt",
    "load_trusted_git_runtime_receipt",
    "recover_trusted_git_runtime_transaction",
    "stage_trusted_git_runtime",
]
