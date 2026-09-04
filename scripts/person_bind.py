#!/usr/bin/env python3
"""Bind a real body and/or voice to an existing person -- as a NEW reviewed
Person Revision, never by editing the active one (#752).

A person is created with `unbound` body and voice candidates so she can
speak on day one. When BodyRig has produced a bodyid and VoiceRig a
.mrvoice, this adds them as candidates, proposes one revision holding the
new triple, and activates it. The active revision only moves as a whole;
the compatibility review is the operator's statement, so --reviewed is
required exactly as in person_create.py.

    python scripts\\person_bind.py --person person-<hex> --voice kaliv.mrvoice ^
        --body bodyid-<hex> --reviewed --reviewer Anders
"""

from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0])
from person_create import Call, http_call  # noqa: E402


def run(call: Call, *, person_id: str, body: str | None, voice: str | None,
        reviewer: str, reviewed: bool, note: str) -> dict:
    if body is None and voice is None:
        raise SystemExit("nothing to bind: give --body and/or --voice")
    if not reviewed:
        raise SystemExit(
            "Refusing to approve a Person Revision without --reviewed: the "
            "compatibility review (body<->voice, voice<->personality, "
            "body<->personality, overall) is the operator's statement.")
    person = call("GET", f"/persons/{person_id}", None)
    active_id = person.get("active_person_revision")
    active = next((r for r in person.get("person_revisions", []) if r["id"] == active_id), None)
    if active is None:
        raise SystemExit(f"{person_id} has no active Person Revision to build on; use person_create.py first")
    body_rev = active["body"]
    voice_rev = active["voice"]
    if body is not None:
        body_rev = call("POST", f"/persons/{person_id}/body-revisions", {"source_id": body})["id"]
    if voice is not None:
        voice_rev = call("POST", f"/persons/{person_id}/voice-revisions", {"source_id": voice})["id"]
    review = {k: True for k in ("body_voice", "voice_personality", "body_personality", "overall")}
    revision = call("POST", f"/persons/{person_id}/person-revisions", {
        "body": body_rev, "voice": voice_rev, "personality": active["personality"],
        "review": review, "reviewer": reviewer, "note": note,
    })
    call("POST", f"/persons/{person_id}/activate", {"person_revision": revision["id"]})
    return {
        "person_id": person_id,
        "previous_revision": active_id,
        "person_revision": revision["id"],
        "body": body_rev, "voice": voice_rev, "personality": active["personality"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8099")
    ap.add_argument("--token", default=None)
    ap.add_argument("--person", required=True, help="person-<32 hex>")
    ap.add_argument("--body", default=None, help="bodyid-* from BodyRig (installed in KALIV_BODY_STORE)")
    ap.add_argument("--voice", default=None, help="VoiceRig .mrvoice package name, e.g. kaliv.mrvoice")
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--reviewed", action="store_true")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    prefix = "/api/v1" if a.token else ""
    call = http_call(a.base.rstrip("/") + prefix, a.token)
    print(json.dumps(run(call, person_id=a.person, body=a.body, voice=a.voice,
                         reviewer=a.reviewer, reviewed=a.reviewed, note=a.note), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
