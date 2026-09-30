"""Privacy-safe read-only runtime status for Consciousness Core.

Mounted on the production entrypoint but reachable only from loopback. The route
exposes activation/readiness booleans and aggregate counters; it never emits
Self/Person ids, model prompts, memory refs, event ids or chain-of-thought.
"""
from __future__ import annotations

import os
import secrets
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
from .autonomous_scheduler import ScheduledAutonomousCognitionBridge


_RUNTIME_INSTANCE_REF = "runtime-instance:" + secrets.token_hex(16)


def runtime_instance_ref() -> str:
    """Opaque process-instance reference; regenerated on worker process start."""
    return _RUNTIME_INSTANCE_REF


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
        autonomous = getattr(
            request.app.state,
            "consciousness_autonomous_scheduler",
            None,
        )
        self_present, person_available, profile_available = _safe_prerequisites()

        live = isinstance(session, ProductionCognitiveSession)
        return {
            "schema": "kaliv-consciousness-core/runtime-status/v1",
            "runtime_instance_ref": runtime_instance_ref(),
            "enabled": {
                "core": _flag("KALIV_CONSCIOUSNESS_CORE_ENABLED"),
                "supervisor": _flag("KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED"),
                "chat_admission": _flag("KALIV_CONSCIOUSNESS_CHAT_ENABLED"),
                "turn_cognition": _flag("KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED"),
                "event_step": _flag("KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED"),
                "guidance": _flag("KALIV_CONSCIOUSNESS_GUIDANCE_ENABLED"),
                "reply_guidance": _flag("KALIV_CONSCIOUSNESS_REPLY_GUIDANCE_ENABLED"),
                "visionrig_admission": _flag("KALIV_CONSCIOUSNESS_VISIONRIG_ENABLED"),
                "sleep_lifecycle": _flag("KALIV_CONSCIOUSNESS_SLEEP_LIFECYCLE_ENABLED"),
                "unplanned_liveness": _flag("KALIV_CONSCIOUSNESS_UNPLANNED_LIVENESS_ENABLED"),
                "policy_checkpoint": _flag("KALIV_CONSCIOUSNESS_POLICY_CHECKPOINT_ENABLED"),
                "checkpoint_liveness": _flag("KALIV_CONSCIOUSNESS_CHECKPOINT_LIVENESS_ENABLED"),
                "autonomous_cognition": _flag("KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED"),
                "autonomous_scheduler": _flag("KALIV_CONSCIOUSNESS_AUTONOMOUS_SCHEDULER_ENABLED"),
                "autonomous_checkpoint": _flag("KALIV_CONSCIOUSNESS_AUTONOMOUS_CHECKPOINT_ENABLED"),
                "continuous_loop": _flag("KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED"),
            },
            "mounted": {
                "supervisor": isinstance(supervisor, ProductionSupervisorBridge),
                "live_session": live,
                "autonomous_scheduler": isinstance(
                    autonomous,
                    ScheduledAutonomousCognitionBridge,
                ),
            },
            "prerequisites": {
                "self_state_present": self_present,
                "active_person_available": person_available,
                "cognitive_profile_available": profile_available,
            },
            "completed_cycles": (
                session.live_state.completed_cycles if live else 0
            ),
            "lived_continuity": {
                "temporal_state_present": bool(
                    live and session.temporal_state is not None
                ),
                "receipt_present": bool(
                    live and session.lived_continuity is not None
                ),
                "present_context_present": bool(
                    live and session.present_context is not None
                ),
            },
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
            "ready_for_lived_continuity": bool(
                _flag("KALIV_CONSCIOUSNESS_SLEEP_LIFECYCLE_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_UNPLANNED_LIVENESS_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_POLICY_CHECKPOINT_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_AUTONOMOUS_SCHEDULER_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_AUTONOMOUS_CHECKPOINT_ENABLED")
                and _flag("KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED")
                and live
                and isinstance(
                    autonomous,
                    ScheduledAutonomousCognitionBridge,
                )
                and autonomous.status().installed
            ),
            "autonomous_scheduler_status": (
                autonomous.status().model_dump(mode="json")
                if isinstance(
                    autonomous,
                    ScheduledAutonomousCognitionBridge,
                )
                else None
            ),
            "production_activation": False,
        }

    return router
