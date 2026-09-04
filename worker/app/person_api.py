"""HTTP surface for the Person Profile registry (#752).

Mounted at /persons on the worker; the backend forwards /api/v1/persons
behind device-token auth. Every write goes through PersonRegistry, which is
where the invariant lives -- and the route inventory is itself part of the
contract: there is NO route that activates a body, a voice or a
personality on its own. The only activation route takes a Person Revision.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .person_registry import PersonRegistry, RegistryError

PERSONS_STORE_ENV = "KALIV_PERSONS_STORE"
DEFAULT_STORE = "persons-registry.json"


def registry_path() -> str:
    return os.environ.get(PERSONS_STORE_ENV) or DEFAULT_STORE


def _person_json(person: Any) -> dict[str, Any]:
    return asdict(person)


def build_person_router(registry: PersonRegistry | None = None) -> APIRouter:
    router = APIRouter(prefix="/persons", tags=["persons"])
    state: dict[str, PersonRegistry | None] = {"registry": registry}

    def reg() -> PersonRegistry:
        if state["registry"] is None:
            # Opened lazily: route construction stays side-effect free, like
            # the schedule router, so importing the app never touches disk.
            state["registry"] = PersonRegistry(registry_path())
        return state["registry"]

    async def body_of(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="JSON body required")
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        return data

    def guard(fn):
        try:
            return fn()
        except RegistryError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc))

    @router.get("")
    def list_persons() -> dict[str, Any]:
        r = reg()
        return {
            "selected_person_id": r.selected_person_id,
            "persons": [_person_json(p) for p in r.list_persons()],
        }

    @router.post("", status_code=201)
    async def create_person(request: Request) -> dict[str, Any]:
        data = await body_of(request)
        return _person_json(guard(lambda: reg().create_person(str(data.get("display_name", "")))))

    @router.get("/active")
    def active() -> dict[str, Any]:
        bindings = reg().active_bindings()
        return {"selected_person_id": reg().selected_person_id, "active": bindings}

    @router.post("/select")
    async def select(request: Request) -> dict[str, Any]:
        data = await body_of(request)
        return _person_json(guard(lambda: reg().select(str(data.get("person_id", "")))))

    @router.get("/{person_id}")
    def get_person(person_id: str) -> dict[str, Any]:
        return _person_json(guard(lambda: reg().get(person_id)))

    @router.post("/{person_id}/body-revisions", status_code=201)
    async def add_body(person_id: str, request: Request) -> dict[str, Any]:
        data = await body_of(request)
        return asdict(guard(lambda: reg().add_body_revision(
            person_id, str(data.get("source_id", "")), str(data.get("note", "")))))

    @router.post("/{person_id}/voice-revisions", status_code=201)
    async def add_voice(person_id: str, request: Request) -> dict[str, Any]:
        data = await body_of(request)
        return asdict(guard(lambda: reg().add_voice_revision(
            person_id, str(data.get("source_id", "")), str(data.get("note", "")))))

    @router.post("/{person_id}/personality-revisions", status_code=201)
    async def add_personality(person_id: str, request: Request) -> dict[str, Any]:
        data = await body_of(request)
        return asdict(guard(lambda: reg().add_personality_revision(
            person_id,
            system_instructions=str(data.get("system_instructions", "")),
            default_language=str(data.get("default_language", "")),
            style_notes=str(data.get("style_notes", "")),
            feedback=str(data.get("feedback", "")),
        )))

    @router.post("/{person_id}/person-revisions", status_code=201)
    async def propose(person_id: str, request: Request) -> dict[str, Any]:
        data = await body_of(request)
        review = data.get("review")
        if not isinstance(review, dict):
            raise HTTPException(status_code=422, detail="review object required")
        return asdict(guard(lambda: reg().propose_person_revision(
            person_id,
            body=str(data.get("body", "")),
            voice=str(data.get("voice", "")),
            personality=str(data.get("personality", "")),
            review=review,
            reviewer=str(data.get("reviewer", "")),
            note=str(data.get("note", "")),
        )))

    @router.post("/{person_id}/activate")
    async def activate(person_id: str, request: Request) -> dict[str, Any]:
        # Takes a Person Revision and nothing else. Body, voice and
        # personality move together or not at all.
        data = await body_of(request)
        return _person_json(guard(lambda: reg().activate(
            person_id, str(data.get("person_revision", "")))))

    return router


def route_inventory(router: APIRouter) -> list[tuple[str, str]]:
    """(method, path) pairs -- used by the contract test that proves there
    is no single-component activation route."""
    out: list[tuple[str, str]] = []
    for route in router.routes:
        methods = getattr(route, "methods", None) or set()
        for m in sorted(methods):
            out.append((m, route.path))
    return sorted(out)
