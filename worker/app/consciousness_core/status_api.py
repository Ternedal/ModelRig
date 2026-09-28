"""Privacy-safe read-only runtime status for Consciousness Core.

Mounted on the production entrypoint but reachable only from loopback. The route
exposes activation/readiness booleans and aggregate counters; it never emits
Self/Person ids, model prompts, memory refs, event ids or chain-of-thought.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..netguard import is_loopback
from ..person_api import registry_path
from ..person_registry import PersonRegistry
from .profile_source import cognitive_profile_config_path
from .self_state import SelfStateStore
from .session_lifecycle import ProductionCognitiveSession
from .supervisor_lifecycle import ProductionSupervisorBridge


def _loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _flag(name: str) -> bool:
    return os.getenv(name, "0") == "1"


def _safe_prerequisites() -> tuple[bool, bool, bool]:
    self_state_present = False
    active_person_available = False
    profile_available = False
    try:
        self_state_present = SelfStateStore().read() is not None
    except Exception:
        pass
    try:
        path = Path(registry_path())
        if path.exists():
            active_person_available = PersonRegistry(path).active_bindings() is not None
    except Exception:
        pass
    try:
        profile_available = cognitive_profile_config_path().is_file()
    except Exception:
        pass
    return self_state_present, active_person_available, profile_available


def build_consciousness_status_router() -> APIRouter:
    router = APIRouter(
        prefix="/experimental/consciousness",
        tags=["experimental-consciousness"],
    )

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        if not _loopback(request):
            raise HTTPException(
                status_code=403,
                detail="Consciousness status is loopback-only",
            )

        supervisor = getattr(request.app.state, "consciousness_supervisor", None)
        session = getattr(request.app.state, "consciousness_session", None)
        self_present, person_available, profile_available = _safe_prerequisites()

        live = isinstance(session, ProductionCognitiveSession)
        return {
            "schema": "kaliv-consciousness-core/runtime-status/v1",
            "enabled": {
                "core": _flag("KALIV_CONSCIOUSNESS_CORE_ENABLED"),
                "supervisor": _flag("KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED"),
                "chat_admission": _flag("KALIV_CONSCIOUSNESS_CHAT_ENABLED"),
                "turn_cognition": _flag("KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED"),
                "event_step": _flag("KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED"),
                "guidance": _flag("KALIV_CONSCIOUSNESS_GUIDANCE_ENABLED"),
                "reply_guidance": _flag("KALIV_CONSCIOUSNESS_REPLY_GUIDANCE_ENABLED"),
                "visionrig_admission": _flag("KALIV_CONSCIOUSNESS_VISIONRIG_ENABLED"),
            },
            "mounted": {
                "supervisor": isinstance(supervisor, ProductionSupervisorBridge),
                "live_session": live,
            },
            "prerequisites": {
                "self_state_present": self_present,
                "active_person_available": person_available,
                "cognitive_profile_available": profile_available,
            },
            "completed_cycles": (
                session.live_state.completed_cycles if live else 0
            ),
            "ready_for_user_driven_cognition": bool(
                _flag("KALIV_CONSCIOUSNESS_CORE_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_CHAT_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED")
                and isinstance(supervisor, ProductionSupervisorBridge)
                and live
                and profile_available
            ),
            "production_activation": False,
        }

    return router
