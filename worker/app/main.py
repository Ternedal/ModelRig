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

import os as _os
import sys as _sys

from . import main_impl as _impl
from .browser_research_tool import register_browser_research_tool as _register_browser_research_tool

VERSION = "1.58.145"
_impl.VERSION = VERSION
_impl.app.version = VERSION

# Explicit feature-gated registration only. The literal getenv is intentional:
# scripts/activation_readiness.py reads feature switches from code, so this new
# power must appear on the generated readiness page rather than hide behind a
# constant name. The registration function repeats the same check and remains
# fail-closed when called from any other import path.
if _os.getenv("KALIV_BROWSER_RESEARCH", "0").strip().lower() in {
    "1",
    "true",
    "on",
}:
    _register_browser_research_tool()

# Return the implementation module for every import of app.main. This preserves
# module-global monkeypatching and private helper access instead of copying names
# into a wrapper namespace whose functions would still close over main_impl.
_sys.modules[__name__] = _impl
