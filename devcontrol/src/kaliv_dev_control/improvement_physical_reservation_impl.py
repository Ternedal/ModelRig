"""Non-authority compatibility namespace for RSI physical reservation internals.

The production authority entry point lives only in
``improvement_physical_reservation`` and resolves its trust root from host
state. This module intentionally exposes no verifier-taking consume wrapper.
Selected implementation seams are forwarded solely to preserve deterministic
repository tests while the real implementation module remains private.
"""
from __future__ import annotations

import sys
import types

from . import _improvement_physical_reservation_impl as _impl

LocalMainHeadObservation = _impl.LocalMainHeadObservation
PhysicalQualificationReservation = _impl.PhysicalQualificationReservation
PhysicalQualificationReservationError = _impl.PhysicalQualificationReservationError

_FORWARDED_TEST_SEAMS = frozenset(
    {
        "_verify_request_at",
        "create_once_file",
        "unlink_durable",
        "_canonical",
    }
)


class _CompatibilityModule(types.ModuleType):
    def __getattr__(self, name: str):
        if name in _FORWARDED_TEST_SEAMS:
            return getattr(_impl, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:
        if name in _FORWARDED_TEST_SEAMS:
            setattr(_impl, name, value)
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _CompatibilityModule

__all__ = [
    "LocalMainHeadObservation",
    "PhysicalQualificationReservation",
    "PhysicalQualificationReservationError",
]
