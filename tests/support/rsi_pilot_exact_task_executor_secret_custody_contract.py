"""Adversarial contract for ADR-DC-036 Windows HMAC secret custody."""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

import kaliv_dev_control.improvement_pilot_exact_task_executor_capability as capability  # noqa: E402
import kaliv_dev_control._improvement_pilot_exact_task_executor_capability_production_boundary as production  # noqa: E402
import kaliv_dev_control._improvement_pilot_exact_task_executor_capability_secret_custody as custody  # noqa: E402


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-036 accepted unsafe HMAC secret custody")


def run_contract() -> None:
    trusted = sorted(custody._WINDOWS_TRUSTED_CONTROL_SIDS)[0]
    users = "S-1-5-32-545"  # BUILTIN\\Users
    everyone = "S-1-1-0"

    # Trusted host principals may read the symmetric verifier material.
    custody._validate_secret_acl_snapshot(
        trusted,
        ((custody._FILE_READ_DATA, trusted),),
    )
    custody._validate_secret_acl_snapshot(
        trusted,
        ((custody._GENERIC_READ, trusted),),
    )

    # Any untrusted read-data grant is equivalent to HMAC signing authority and
    # must therefore fail closed even if write/control custody is otherwise safe.
    _reject(
        lambda: custody._validate_secret_acl_snapshot(
            trusted,
            ((custody._FILE_READ_DATA, users),),
        )
    )
    _reject(
        lambda: custody._validate_secret_acl_snapshot(
            trusted,
            ((custody._GENERIC_READ, everyone),),
        )
    )
    _reject(lambda: custody._validate_secret_acl_snapshot(users, ()))
    _reject(
        lambda: custody._validate_secret_acl_snapshot(
            trusted,
            ((True, trusted),),
        )
    )

    # HMAC files are the only profile resources promoted to confidential-secret
    # custody; the ordinary executor profile remains host-controlled config.
    assert production._WINDOWS_PHYSICAL_KEYRING != production._WINDOWS_PROFILE
    assert production._WINDOWS_RUNTIME_KEYRING != production._WINDOWS_PROFILE

    facade_source = inspect.getsource(capability)
    assert "install_pilot_exact_task_executor_secret_custody" in facade_source
    secret_source = inspect.getsource(custody)
    assert "_FILE_READ_DATA" in secret_source
    assert "_GENERIC_READ" in secret_source
    assert "_windows_acl_snapshot" in secret_source

    if os.name != "nt":
        _reject(
            lambda: custody._require_windows_secret_confidentiality(
                Path("/not-a-windows-secret")
            )
        )


if __name__ == "__main__":
    run_contract()
