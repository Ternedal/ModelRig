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

VERSION = "1.58.147"
_impl.VERSION = VERSION
_impl.app.version = VERSION

# Computer Use I3/I4: eksplicit feature-gated registrering, intet andet. Det
# literale getenv-kald er med vilje -- scripts/activation_readiness.py laeser
# feature-switches fra kildekoden, saa ny magt skal dukke op paa den genererede
# readiness-side i stedet for at gemme sig bag et konstantnavn. Hver
# registreringsfunktion gentager sit eget tjek og er fail-closed fra enhver
# import-sti.
#
# Registreringen bor her og ikke i entrypointet, fordi vision-broen skal wrappe
# _run_tool_loop i selve implementeringsmodulet: en flade der monteres senere i
# ASGI-laget ville lade et enkelt tool-loop slippe uden om broen. Pinnet i
# tests/worker_desktop_screenshot_entrypoint.py, som proever en FRISK proces.
if _os.getenv("KALIV_COMPUTER_USE", "0").strip().lower() in {"1", "true", "on"}:
    # Lazy med vilje: med flaget slukket importerer normal worker-opstart
    # hverken screenshot, vision, preview/action-plan eller Win32-adapteren.
    from .desktop_action_preview_tool import (
        register_desktop_action_preview_tool as _register_desktop_action_preview_tool,
    )
    from .desktop_screenshot_tool import (
        register_desktop_screenshot_tool as _register_desktop_screenshot_tool,
    )
    from .desktop_vision_bridge import (
        install_desktop_vision_bridge as _install_desktop_vision_bridge,
    )

    _install_desktop_vision_bridge(_impl)
    _register_desktop_screenshot_tool()
    # SKAL foelge screenshot-registreringen: preview-graensen wrapper praecis
    # det godkendte capture-resultat og binder sit token til den udstedende
    # samtale.
    _register_desktop_action_preview_tool()

# Return the implementation module for every import of app.main. This preserves
# module-global monkeypatching and private helper access instead of copying names
# into a wrapper namespace whose functions would still close over main_impl.
_sys.modules[__name__] = _impl
