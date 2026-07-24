"""Compatibility module for the dormant Win32 desktop adapter.

The hardened implementation lives in :mod:`app.desktop_win32_v2`. Importers
receive that module directly so private ABI helpers and injected-native tests
retain normal module-global behaviour. Nothing here registers a tool or enables
input injection.
"""
from __future__ import annotations

import sys as _sys

from . import desktop_win32_v2 as _impl

_sys.modules[__name__] = _impl
