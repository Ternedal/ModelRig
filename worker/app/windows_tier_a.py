"""Authoritative dormant Tier-A Windows launch surface.

Callers do not provide a child environment directly. This module derives a
small case-insensitive positive list of Windows initialization fields and then
invokes the lower-level AppContainer + Job Object substrate. Application
settings, credentials, GitHub Actions tokens, model keys, cookies and arbitrary
caller variables therefore cannot ride into the sandbox by naming convention
or prefix accident.

A second, exact-value allowlist permits only the reviewed non-secret settings
used by the immutable ModelRig command catalog. A caller cannot introduce a new
application key or alter one of those values.

Optional output capture is likewise narrow: it may inject only inherited
standard handles into the existing CreateProcessW call. It cannot choose a
command, environment, AppContainer or Job Object.

No registered ModelRig tool uses this module yet.
"""
from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from .windows_capture import WindowsOutputCapture
from .windows_job import JobLimits, terminate_attached_job
from .windows_restricted import (
    AppContainerProcess,
    AppContainerProfile,
    RestrictedLaunchError,
    RestrictedLaunchPolicy,
    WorkspaceAclReceipt,
    spawn_restricted_in_job,
)

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

WINDOWS_TIER_A_APPLICATION_ENVIRONMENT = MappingProxyType(
    {
        "CI": "1",
        "MODELRIG_DEVCONTROL": "1",
        "GOTOOLCHAIN": "local",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
)

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


def _application_environment(source: Mapping[str, str] | None) -> dict[str, str]:
    if source is None:
        return {}
    if not isinstance(source, Mapping):
        raise RestrictedLaunchError(
            "Tier-A application environment must be a mapping"
        )
    allowed = {
        key.casefold(): (key, expected)
        for key, expected in WINDOWS_TIER_A_APPLICATION_ENVIRONMENT.items()
    }
    clean: dict[str, str] = {}
    seen: set[str] = set()
    for key, value in source.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\0" in key
            or not isinstance(value, str)
            or "\0" in value
        ):
            raise RestrictedLaunchError(
                "Tier-A application environment contains an invalid entry"
            )
        folded = key.casefold()
        if folded in seen:
            raise RestrictedLaunchError(
                f"Tier-A application environment contains a duplicate key: {key}"
            )
        seen.add(folded)
        try:
            canonical_key, expected = allowed[folded]
        except KeyError as exc:
            raise RestrictedLaunchError(
                f"Tier-A application environment key is not reviewed: {key}"
            ) from exc
        if value != expected:
            raise RestrictedLaunchError(
                f"Tier-A application environment value is not reviewed: {canonical_key}"
            )
        clean[canonical_key] = value
    return clean


def appcontainer_environment(
    source: Mapping[str, str],
    *,
    application_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a validated, credential-free Windows child environment."""

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

    application = _application_environment(application_env)
    system_names = {key.casefold() for key in result}
    collisions = sorted(
        key for key in application if key.casefold() in system_names
    )
    if collisions:
        raise RestrictedLaunchError(
            "Tier-A application environment collides with Windows initialization: "
            + ", ".join(collisions)
        )
    result.update(application)
    return result


def spawn_tier_a_in_job(
    command: Sequence[str],
    *,
    source_env: Mapping[str, str] | None = None,
    application_env: Mapping[str, str] | None = None,
    limits: JobLimits,
    policy: RestrictedLaunchPolicy,
    profile: AppContainerProfile,
    acl_receipt: WorkspaceAclReceipt,
    output_capture: WindowsOutputCapture | None = None,
) -> AppContainerProcess:
    """Launch through the only supported Tier-A environment boundary."""

    environment = appcontainer_environment(
        os.environ if source_env is None else source_env,
        application_env=application_env,
    )
    if output_capture is not None:
        if not isinstance(output_capture, WindowsOutputCapture):
            raise RestrictedLaunchError("Tier-A output capture is invalid")
        if output_capture.native_api is not profile._api:
            raise RestrictedLaunchError(
                "Tier-A output capture is not bound to the AppContainer API"
            )
        output_capture.start()

    process: AppContainerProcess | None = None
    try:
        process = spawn_restricted_in_job(
            command,
            env=environment,
            limits=limits,
            policy=policy,
            profile=profile,
            acl_receipt=acl_receipt,
            api=output_capture.api if output_capture is not None else None,
        )
        if output_capture is not None:
            output_capture.assert_spawn_ready()
        return process
    except Exception:
        if process is not None:
            try:
                terminate_attached_job(process)
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            try:
                process.close()
            except Exception:
                pass
        if output_capture is not None:
            output_capture.abort()
        raise
