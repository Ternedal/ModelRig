"""Reviewed Tier-A application environment policy and validation.

This module owns the exact immutable environment allowlist and validator.  The
legacy execution core re-exports both objects unchanged while the larger core is
split in small reviewable steps.  The domain error remains in the legacy core
for H10K, so it is imported lazily only when validation is invoked.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

TIER_A_APPLICATION_ENVIRONMENT = MappingProxyType(
    {
        "CI": "1",
        "MODELRIG_DEVCONTROL": "1",
        "GOTOOLCHAIN": "local",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
)


def _validated_application_env(value: Mapping[str, str]) -> Mapping[str, str]:
    # TierAExecutionError is scheduled for a later identity-preserving extraction.
    # Importing it at call time keeps this module directly importable while H10K
    # moves only the two environment-policy objects promised by the split contract.
    from ._tier_a_execution_core import TierAExecutionError

    if not isinstance(value, Mapping):
        raise TierAExecutionError("Tier-A application environment must be a mapping")
    clean: dict[str, str] = {}
    seen: set[str] = set()
    allowed = {
        key.casefold(): (key, expected)
        for key, expected in TIER_A_APPLICATION_ENVIRONMENT.items()
    }
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\0" in key
            or not isinstance(item, str)
            or "\0" in item
        ):
            raise TierAExecutionError("Tier-A application environment is invalid")
        folded = key.casefold()
        if folded in seen:
            raise TierAExecutionError(
                f"Tier-A application environment contains a duplicate key: {key}"
            )
        seen.add(folded)
        try:
            canonical_key, expected = allowed[folded]
        except KeyError as exc:
            raise TierAExecutionError(
                f"Tier-A application environment key is not reviewed: {key}"
            ) from exc
        if item != expected:
            raise TierAExecutionError(
                f"Tier-A application environment value is not reviewed: {canonical_key}"
            )
        clean[canonical_key] = item
    return MappingProxyType(dict(sorted(clean.items())))
