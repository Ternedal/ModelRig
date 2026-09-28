"""Development-only SelfState bootstrap for a live Consciousness Core session.

This helper never creates or activates a Person. It only bootstraps the durable
SelfState when an already-selected, already-approved active Person Revision
exists. Existing SelfState is validated and left untouched.

The helper is intentionally safe to run on every dev-appliance startup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from ..person_api import registry_path
from ..person_registry import PersonRegistry
from .self_state import (
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateError,
    SelfStateStore,
    bootstrap_self_state,
    verify_active_person,
)


class DevSelfBootstrapError(RuntimeError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _stable_self_id(person_id: str) -> str:
    digest = hashlib.sha256(
        ("kaliv-consciousness-dev-self|" + person_id).encode("utf-8")
    ).hexdigest()
    return "self-" + digest[:32]


def _personality_state_ref(personality: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(personality)).hexdigest()
    return "personality-state:" + digest


def ensure_dev_self_state(
    *,
    store: SelfStateStore | None = None,
    registry: PersonRegistry | None = None,
) -> dict[str, Any]:
    """Ensure durable SelfState exists for the active approved Person Revision.

    No Person/profile mutation is permitted here. A missing active Person is a
    hard prerequisite failure rather than a reason to fabricate identity.
    """
    store = store or SelfStateStore()
    registry = registry or PersonRegistry(Path(registry_path()))

    active = registry.active_bindings()
    if active is None:
        raise DevSelfBootstrapError(
            "no selected active approved Person Revision; Consciousness Core "
            "cannot bootstrap identity"
        )

    person_id = str(active.get("person_id", ""))
    person_revision = str(active.get("person_revision", ""))
    personality = active.get("personality")
    if not person_id or not person_revision or not isinstance(personality, dict):
        raise DevSelfBootstrapError("active Person binding is incomplete")

    current = store.read()
    if current is not None:
        try:
            verify_active_person(
                current,
                active_person_id=person_id,
                active_person_revision=person_revision,
            )
        except SelfStateError as exc:
            raise DevSelfBootstrapError(
                "existing SelfState does not match the active Person Revision; "
                "explicit rebind is required"
            ) from exc
        return {
            "status": "existing",
            "self_id": current.self_id,
            "self_revision": current.revision,
            "person_id": current.person_id,
            "person_revision": current.person_revision,
            "self_state_path": str(store.path),
            "production_activation": False,
        }

    authority = SelfBootstrapAuthority(
        schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
        self_id=_stable_self_id(person_id),
        person_id=person_id,
        person_revision=person_revision,
        authority="operator_review",
        authority_ref="operator:dev-consciousness-activation-2026-09-28",
        source_refs=[
            "person-registry:active",
            f"person-revision:{person_revision}",
        ],
        production_activation=False,
    )
    state = bootstrap_self_state(
        authority,
        personality_state_ref=_personality_state_ref(personality),
        world_state_ref="world-state:bootstrap-pending-runtime",
        workspace_ref="workspace:bootstrap-pending-runtime",
        affect=SelfAffect(
            labels=["baseline"],
            valence=0.0,
            arousal=0.0,
            confidence=1.0,
            source_refs=["operator:dev-consciousness-activation-2026-09-28"],
        ),
        active_goal_refs=[],
        active_intention_refs=[],
        known_uncertainties=[],
        last_experience_ref=None,
    )
    store.bootstrap(state, authority)
    return {
        "status": "bootstrapped",
        "self_id": state.self_id,
        "self_revision": state.revision,
        "person_id": state.person_id,
        "person_revision": state.person_revision,
        "self_state_path": str(store.path),
        "production_activation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure dev Consciousness Core has a durable SelfState."
    )
    parser.parse_args()
    try:
        result = ensure_dev_self_state()
    except (DevSelfBootstrapError, SelfStateError, OSError, ValueError) as exc:
        print(json.dumps(
            {
                "ok": False,
                "error": type(exc).__name__,
                "detail": str(exc),
                "production_activation": False,
            },
            ensure_ascii=True,
        ))
        return 2

    print(json.dumps({"ok": True, **result}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
