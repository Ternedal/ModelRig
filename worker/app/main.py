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

VERSION = "2.0.12"
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

# T-036 GitHub pilot: separate, default-off operator decision.  Keeping the
# literal getenv here makes activation_readiness see the new network-capable
# surface instead of hiding it inside the connector module.  The registration
# function repeats the same guard, so importing/calling it through another path
# still cannot silently activate the pilot.
if _os.getenv("KALIV_GITHUB_CONNECTOR_PILOT", "0").strip().lower() in {"1", "true", "on"}:
    from .github_connector_admin import (
        build_github_connector_admin_router as _build_github_connector_admin_router,
    )
    from .github_connector_tool import (
        register_github_connector_pilot as _register_github_connector_pilot,
    )

    _register_github_connector_pilot(_impl.app)
    # Grant administration is never model-visible. It is mounted only beside
    # the explicitly enabled pilot and rechecks loopback admission on every
    # request; the authenticated Go backend remains the remote operator edge.
    _impl.app.include_router(_build_github_connector_admin_router())

# T-037 Google/Notion read-first package: four separate capabilities, one
# explicit default-off pilot decision.  The connector module repeats this guard
# and owns only read operations; standing grant administration is loopback-only
# and never enters ToolGate as a model-visible mutation.
if _os.getenv("KALIV_READ_CONNECTOR_PILOT", "0").strip().lower() in {"1", "true", "on"}:
    from .read_connector_tool import (
        register_read_connector_pilot as _register_read_connector_pilot,
    )

    _register_read_connector_pilot(_impl.app)

# T-038 RigGate/Home Assistant read-first pilot: default-off composition of the
# exact grant boundary, one-use T-032 data-sharing permission, pinned provider
# transports and side-effect-free wake/control preview. The literal switch is
# intentionally visible to activation_readiness; enabling it still does not
# create any wake/control execution path.
if _os.getenv("KALIV_HOME_RIG_PILOT", "0").strip().lower() in {"1", "true", "on"}:
    from .home_rig_tool import register_home_rig_pilot as _register_home_rig_pilot

    _register_home_rig_pilot(_impl.app)

# Return the implementation module for every import of app.main. This preserves
# module-global monkeypatching and private helper access instead of copying names
# into a wrapper namespace whose functions would still close over main_impl.
_sys.modules[__name__] = _impl
