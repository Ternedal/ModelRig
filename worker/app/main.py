"""Compatibility module for the ModelRig worker application.

The implementation lives in :mod:`app.main_impl` so the large, previously
verified runtime blob can be retained byte-for-byte while release metadata is
owned by this small versioned module. Importers still receive the implementation
module itself; monkeypatching, private helpers and function globals therefore
behave exactly as they did when the implementation lived at ``app.main``.

Run the worker through ``uvicorn app.entrypoint:app``.
NOT ``uvicorn app.main:app``; the production entrypoint owns the outer hardening
and optional-service lifecycle.
"""
from __future__ import annotations

import sys as _sys

from . import main_impl as _impl

VERSION = "1.58.145"
_impl.VERSION = VERSION
_impl.app.version = VERSION

# Return the implementation module for every import of app.main. This preserves
# module-global monkeypatching and private helper access instead of copying names
# into a wrapper namespace whose functions would still close over main_impl.
_sys.modules[__name__] = _impl
