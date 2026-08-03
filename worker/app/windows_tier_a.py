"""Authoritative dormant Tier-A Windows launch surface.

Callers do not provide a child environment directly. This module derives a
small case-insensitive positive list of Windows initialization fields and then
invokes the lower-level AppContainer + Job Object substrate. Application
settings, credentials, GitHub Actions tokens, model keys, cookies and arbitrary
caller variables therefore cannot ride into the sandbox by naming convention
or prefix accident.

No registered ModelRig tool uses this module yet.
"""
from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from .windows_job import JobLimits
from .windows_restricted import (
    AppContainerProcess,
    AppContainerProfile,
    RestrictedLaunchError,
    RestrictedLaunchPolicy,
    WorkspaceAclReceipt,
    spawn_restricted_in_job,
)

# Values required by ordinary Windows process/profile initialization or native
# runtime discovery. This is intentionally a positive list. Adding a variable
# is a security-policy change and must be backed by the Windows kernel gate.
WINDOWS_TIER_A_ENV_NAMES = frozenset(
    name.casefold()
    for name in (
        "ALLUSERSPROFILE",
        "APPDATA",
        "CommonProgramFiles",
        "CommonProgramFiles(x86)",
        "CommonProgramW6432",
        "COMPUTERNAME",
        "ComSpec",
        "DriverData",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "LOGONSERVER",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "Path",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION",
        "ProgramData",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramW6432",
        "PUBLIC",
        "SystemDrive",
        "SystemRoot",
        "TEMP",
        "TMP",
        "USERDOMAIN",
        "USERDOMAIN_ROAMINGPROFILE",
        "USERNAME",
        "USERPROFILE",
        "windir",
    )
)

# These were the smallest stable initialization spine proven on the Windows
# candidate. Missing one is configuration drift; inheriting everything as a
# fallback would reintroduce credentials, so the launcher fails closed.
_REQUIRED_WINDOWS_ENV = frozenset(
    name.casefold()
    for name in (
        "APPDATA",
        "ComSpec",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "Path",
        "SystemDrive",
        "SystemRoot",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "windir",
    )
)


def appcontainer_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Return a validated, credential-free Windows initialization environment."""

    if not isinstance(source, Mapping):
        raise RestrictedLaunchError("Tier-A environment source must be a mapping")
    result: dict[str, str] = {}
    seen: set[str] = set()
    for key, value in source.items():
        if not isinstance(key, str) or not key or "=" in key or "\0" in key:
            raise RestrictedLaunchError("Tier-A environment contains an invalid key")
        folded = key.casefold()
        if folded in seen:
            raise RestrictedLaunchError(
                f"Tier-A environment contains a case-insensitive duplicate: {key}"
            )
        seen.add(folded)
        if folded not in WINDOWS_TIER_A_ENV_NAMES:
            continue
        if not isinstance(value, str) or "\0" in value:
            raise RestrictedLaunchError(
                f"Tier-A environment contains an invalid value for {key}"
            )
        result[key] = value

    present = {key.casefold() for key in result}
    missing = sorted(_REQUIRED_WINDOWS_ENV - present)
    if missing:
        raise RestrictedLaunchError(
            "Tier-A environment is missing required Windows fields: "
            + ", ".join(missing)
        )
    return result


def spawn_tier_a_in_job(
    command: Sequence[str],
    *,
    source_env: Mapping[str, str] | None = None,
    limits: JobLimits,
    policy: RestrictedLaunchPolicy,
    profile: AppContainerProfile,
    acl_receipt: WorkspaceAclReceipt,
) -> AppContainerProcess:
    """Launch through the only supported Tier-A environment boundary."""

    environment = appcontainer_environment(
        os.environ if source_env is None else source_env
    )
    return spawn_restricted_in_job(
        command,
        env=environment,
        limits=limits,
        policy=policy,
        profile=profile,
        acl_receipt=acl_receipt,
    )
