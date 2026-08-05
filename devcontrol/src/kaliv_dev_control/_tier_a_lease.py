"""Shared Tier-A execution error identity.

H10L moves only the established domain error out of the legacy execution core.
The core and every public facade re-export this exact class object.
"""
from __future__ import annotations

from .catalog import CatalogError


class TierAExecutionError(CatalogError):
    """A signed authority could not be converted into a safe Tier-A launch."""
