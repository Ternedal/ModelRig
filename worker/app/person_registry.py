"""Multi-person Person Profile registry (#752).

One stable identity per person; versioned body, voice and personality
components underneath it. The rule this module exists to enforce:

    Body, voice and personality are NEVER activated independently.

Component revisions are candidates. The only thing that can be active is
an approved *Person Revision* -- a specific triple such as

    person-r0007 = body-r0003 + voice-r0002 + personality-r0005

and a Person Revision can only be created when a compatibility review has
explicitly confirmed all four checks (body<->voice, voice<->personality,
body<->personality, overall coherence). A new component revision changes
nothing about the active person until it is part of an approved revision.

Identity: ``person-<32 lowercase hex>``. Body ids, VoiceRig voice ids,
Stash performer ids and display names are component/source identities and
are deliberately not the person's stable id.

Persistence is a single JSON document written atomically; the registry is
small (people, not events) and this keeps the worker dependency-free.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PERSON_ID_RE = re.compile(r"^person-[0-9a-f]{32}$")
REVISION_RE = re.compile(r"^(body|voice|personality|person)-r\d{4}$")
REVIEW_CHECKS = ("body_voice", "voice_personality", "body_personality", "overall")
SCHEMA = "modelrig-person-registry/v1"


class RegistryError(Exception):
    status = 400


class NotFound(RegistryError):
    status = 404


class Invalid(RegistryError):
    status = 422


class Conflict(RegistryError):
    status = 409


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_person_id() -> str:
    return "person-" + secrets.token_hex(16)


@dataclass
class ComponentRevision:
    id: str
    created_at: str
    source_id: str
    note: str = ""


@dataclass
class PersonalityRevision:
    id: str
    created_at: str
    system_instructions: str
    default_language: str
    style_notes: str = ""
    feedback: str = ""


@dataclass
class PersonRevision:
    id: str
    created_at: str
    body: str
    voice: str
    personality: str
    review: dict[str, bool]
    reviewer: str
    note: str = ""
    approved: bool = True


@dataclass
class Person:
    person_id: str
    display_name: str
    created_at: str
    body_revisions: list[ComponentRevision] = field(default_factory=list)
    voice_revisions: list[ComponentRevision] = field(default_factory=list)
    personality_revisions: list[PersonalityRevision] = field(default_factory=list)
    person_revisions: list[PersonRevision] = field(default_factory=list)
    active_person_revision: str | None = None

    def revision(self, rev_id: str) -> PersonRevision | None:
        return next((r for r in self.person_revisions if r.id == rev_id), None)


def _next_id(prefix: str, existing: list[Any]) -> str:
    return f"{prefix}-r{len(existing) + 1:04d}"


class PersonRegistry:
    def __init__(self, path: str | os.PathLike[str]):
        self._path = Path(path)
        self._lock = threading.RLock()
        self._persons: dict[str, Person] = {}
        self._selected: str | None = None
        self._load()

    # ---- persistence -------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        doc = json.loads(self._path.read_text(encoding="utf-8"))
        if doc.get("schema") != SCHEMA:
            raise Invalid(f"unsupported registry schema: {doc.get('schema')!r}")
        for raw in doc.get("persons", []):
            person = Person(
                person_id=raw["person_id"],
                display_name=raw["display_name"],
                created_at=raw["created_at"],
                body_revisions=[ComponentRevision(**x) for x in raw.get("body_revisions", [])],
                voice_revisions=[ComponentRevision(**x) for x in raw.get("voice_revisions", [])],
                personality_revisions=[PersonalityRevision(**x) for x in raw.get("personality_revisions", [])],
                person_revisions=[PersonRevision(**x) for x in raw.get("person_revisions", [])],
                active_person_revision=raw.get("active_person_revision"),
            )
            self._persons[person.person_id] = person
        self._selected = doc.get("selected_person_id")
        if self._selected not in self._persons:
            self._selected = None

    def _save(self) -> None:
        doc = {
            "schema": SCHEMA,
            "selected_person_id": self._selected,
            "persons": [asdict(p) for p in self._persons.values()],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    # ---- persons -----------------------------------------------------------

    def list_persons(self) -> list[Person]:
        with self._lock:
            return list(self._persons.values())

    def get(self, person_id: str) -> Person:
        with self._lock:
            person = self._persons.get(person_id)
            if person is None:
                raise NotFound(f"unknown person: {person_id}")
            return person

    def create_person(self, display_name: str) -> Person:
        name = (display_name or "").strip()
        if not name:
            raise Invalid("display_name is required")
        with self._lock:
            person = Person(person_id=new_person_id(), display_name=name, created_at=_now())
            self._persons[person.person_id] = person
            self._save()
            return person

    # ---- component revisions (candidates only) ----------------------------

    def add_body_revision(self, person_id: str, source_id: str, note: str = "") -> ComponentRevision:
        return self._add_component(person_id, "body", source_id, note)

    def add_voice_revision(self, person_id: str, source_id: str, note: str = "") -> ComponentRevision:
        return self._add_component(person_id, "voice", source_id, note)

    def _add_component(self, person_id: str, kind: str, source_id: str, note: str) -> ComponentRevision:
        src = (source_id or "").strip()
        if not src:
            raise Invalid(f"{kind} source_id is required")
        with self._lock:
            person = self.get(person_id)
            bucket = person.body_revisions if kind == "body" else person.voice_revisions
            rev = ComponentRevision(id=_next_id(kind, bucket), created_at=_now(), source_id=src, note=note or "")
            bucket.append(rev)
            self._save()
            return rev

    def add_personality_revision(
        self,
        person_id: str,
        *,
        system_instructions: str,
        default_language: str,
        style_notes: str = "",
        feedback: str = "",
    ) -> PersonalityRevision:
        if not (system_instructions or "").strip():
            raise Invalid("system_instructions is required")
        if not (default_language or "").strip():
            raise Invalid("default_language is required")
        with self._lock:
            person = self.get(person_id)
            rev = PersonalityRevision(
                id=_next_id("personality", person.personality_revisions),
                created_at=_now(),
                system_instructions=system_instructions,
                default_language=default_language.strip(),
                style_notes=style_notes or "",
                feedback=feedback or "",
            )
            person.personality_revisions.append(rev)
            self._save()
            return rev

    # ---- person revisions (the only activatable unit) ----------------------

    def propose_person_revision(
        self,
        person_id: str,
        *,
        body: str,
        voice: str,
        personality: str,
        review: dict[str, Any],
        reviewer: str,
        note: str = "",
    ) -> PersonRevision:
        if not (reviewer or "").strip():
            raise Invalid("reviewer is required")
        missing = [c for c in REVIEW_CHECKS if review.get(c) is not True]
        if missing:
            raise Invalid("compatibility review incomplete: " + ", ".join(missing))
        with self._lock:
            person = self.get(person_id)
            if not any(r.id == body for r in person.body_revisions):
                raise Invalid(f"unknown body revision: {body}")
            if not any(r.id == voice for r in person.voice_revisions):
                raise Invalid(f"unknown voice revision: {voice}")
            if not any(r.id == personality for r in person.personality_revisions):
                raise Invalid(f"unknown personality revision: {personality}")
            rev = PersonRevision(
                id=_next_id("person", person.person_revisions),
                created_at=_now(),
                body=body,
                voice=voice,
                personality=personality,
                review={c: True for c in REVIEW_CHECKS},
                reviewer=reviewer.strip(),
                note=note or "",
            )
            person.person_revisions.append(rev)
            self._save()
            return rev

    def activate(self, person_id: str, person_revision: str) -> Person:
        """The ONLY way any body, voice or personality becomes active."""
        with self._lock:
            person = self.get(person_id)
            rev = person.revision(person_revision)
            if rev is None:
                raise NotFound(f"unknown person revision: {person_revision}")
            if not rev.approved:
                raise Conflict(f"{person_revision} is not approved")
            person.active_person_revision = rev.id
            self._save()
            return person

    # ---- selection and resolution -----------------------------------------

    def select(self, person_id: str) -> Person:
        with self._lock:
            person = self.get(person_id)
            self._selected = person.person_id
            self._save()
            return person

    @property
    def selected_person_id(self) -> str | None:
        return self._selected

    def active_bindings(self) -> dict[str, Any] | None:
        """Resolved body/voice/personality for the selected person, or None.

        All three come from the SAME approved Person Revision by
        construction -- there is no field anywhere that could hold a
        different active body than the revision names.
        """
        with self._lock:
            if self._selected is None:
                return None
            person = self._persons[self._selected]
            if person.active_person_revision is None:
                return None
            rev = person.revision(person.active_person_revision)
            if rev is None:
                return None
            body = next(r for r in person.body_revisions if r.id == rev.body)
            voice = next(r for r in person.voice_revisions if r.id == rev.voice)
            personality = next(r for r in person.personality_revisions if r.id == rev.personality)
            return {
                "person_id": person.person_id,
                "display_name": person.display_name,
                "person_revision": rev.id,
                "body": asdict(body),
                "voice": asdict(voice),
                "personality": asdict(personality),
            }
