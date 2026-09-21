"""Confidential Windows custody for ADR-DC-036 symmetric verifier secrets.

The existing physical-isolation and runtime-closure verifiers are HMAC based.  Their
verification material is therefore also signing material and must not be treated like
a public verification keyring.  This module layers a read-confidentiality requirement
on top of the existing host-admin write/control custody before either HMAC keyring is
loaded in production.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _WINDOWS_TRUSTED_CONTROL_SIDS,
    _windows_acl_snapshot,
)

_GENERIC_READ = 0x80000000
_FILE_READ_DATA = 0x00000001
_SECRET_READ_MASK = _GENERIC_READ | _FILE_READ_DATA


class PilotExactTaskExecutorSecretCustodyError(ValueError):
    """A symmetric ADR-DC-036 verifier secret is not confidentially held."""


def _validate_secret_acl_snapshot(
    owner_sid: str,
    allow_entries: tuple[tuple[int, str], ...],
) -> None:
    """Require secret-file read authority to remain inside trusted host principals."""

    if owner_sid not in _WINDOWS_TRUSTED_CONTROL_SIDS:
        raise PilotExactTaskExecutorSecretCustodyError(
            "executor HMAC secret owner is not host-admin controlled"
        )
    for mask, sid in allow_entries:
        if (
            isinstance(mask, bool)
            or not isinstance(mask, int)
            or not isinstance(sid, str)
        ):
            raise PilotExactTaskExecutorSecretCustodyError(
                "executor HMAC secret ACL snapshot is malformed"
            )
        if mask & _SECRET_READ_MASK and sid not in _WINDOWS_TRUSTED_CONTROL_SIDS:
            raise PilotExactTaskExecutorSecretCustodyError(
                "executor HMAC secret grants read-data authority to an untrusted principal"
            )


def _require_windows_secret_confidentiality(path: Path) -> None:
    if os.name != "nt":
        raise PilotExactTaskExecutorSecretCustodyError(
            "executor HMAC secret confidentiality requires native Windows ACL inspection"
        )
    try:
        owner_sid, entries = _windows_acl_snapshot(Path(path))
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskExecutorSecretCustodyError(
            "executor HMAC secret ACL could not be inspected"
        ) from exc
    _validate_secret_acl_snapshot(owner_sid, entries)


def install_pilot_exact_task_executor_secret_custody(production: Any) -> None:
    if production is None:
        raise PilotExactTaskExecutorSecretCustodyError(
            "executor production boundary is unavailable"
        )
    marker = "_pilot_exact_task_executor_secret_custody_installed"
    if getattr(production, marker, False):
        return

    original_read = production._read_host_controlled
    secret_paths = frozenset(
        {
            production._WINDOWS_PHYSICAL_KEYRING,
            production._WINDOWS_RUNTIME_KEYRING,
        }
    )

    def guarded_read(path: Path, *, maximum: int) -> bytes:
        candidate = Path(path)
        if candidate not in secret_paths:
            return original_read(candidate, maximum=maximum)
        try:
            before = os.stat(candidate, follow_symlinks=False)
            _require_windows_secret_confidentiality(candidate)
            payload = original_read(candidate, maximum=maximum)
            after = os.stat(candidate, follow_symlinks=False)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise PilotExactTaskExecutorSecretCustodyError(
                    "executor HMAC secret file changed during custody verification"
                )
            _require_windows_secret_confidentiality(candidate)
            return payload
        except PilotExactTaskExecutorSecretCustodyError:
            raise
        except OSError as exc:
            raise PilotExactTaskExecutorSecretCustodyError(
                "executor HMAC secret file could not be stably inspected"
            ) from exc

    production._read_host_controlled = guarded_read
    setattr(production, marker, True)


__all__: list[str] = []
