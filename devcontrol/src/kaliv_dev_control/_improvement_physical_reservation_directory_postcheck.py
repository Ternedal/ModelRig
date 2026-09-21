"""Post-validation history guard for RSI reservation directory provenance.

The base directory-history implementation drains kernel history before checking
retained descriptors against their canonical paths. A protected rename can be
queued while those path checks are running. Production therefore performs one
second history drain after the identity validation and before a binding may
return true.
"""
from __future__ import annotations

from . import _improvement_physical_reservation_directory_provenance as _history


def install_directory_history_postcheck_guard() -> None:
    """Require a clean history queue both before and after ancestry validation."""

    if getattr(_history, "_directory_history_postcheck_guard_installed", False):
        return

    original_binding_matches = _history._binding_matches

    def binding_matches(binding: _history._Binding) -> bool:
        if not original_binding_matches(binding):
            return False
        if binding.revoked or not _history._history_clean(binding):
            binding.revoked = True
            return False
        return True

    _history._binding_matches = binding_matches
    _history._directory_history_postcheck_guard_installed = True


__all__: list[str] = []
