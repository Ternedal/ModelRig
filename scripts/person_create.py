#!/usr/bin/env python3
"""Create a person end to end: identity, three component candidates, one
reviewed Person Revision, activate, select (#752).

Talks to the worker directly on loopback (no device token needed on the
rig), or to the backend with --token. The compatibility review is the
operator's statement, so the script refuses to approve unless
--reviewed is passed: "body <-> voice, voice <-> personality,
body <-> personality and overall coherence confirmed by me".

    python scripts\\person_create.py --name Kaliv ^
        --instructions "Du er Kaliv, en rolig, praecis assistent." ^
        --language dansk --style "korte svar" --reviewed --reviewer Anders
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

Call = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


def http_call(base: str, token: str | None) -> Call:
    def call(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SystemExit(f"{method} {path} -> {exc.code}: {detail}")
    return call


def run(call: Call, *, name: str, instructions: str, language: str, style: str,
        body_source: str, voice_source: str, reviewer: str, reviewed: bool,
        note: str, select: bool) -> dict[str, Any]:
    if not reviewed:
        raise SystemExit(
            "Refusing to approve a Person Revision without --reviewed: the "
            "compatibility review (body<->voice, voice<->personality, "
            "body<->personality, overall) is the operator's statement.")
    person = call("POST", "/persons", {"display_name": name})
    pid = person["person_id"]
    body = call("POST", f"/persons/{pid}/body-revisions", {"source_id": body_source})
    voice = call("POST", f"/persons/{pid}/voice-revisions", {"source_id": voice_source})
    personality = call("POST", f"/persons/{pid}/personality-revisions", {
        "system_instructions": instructions,
        "default_language": language,
        "style_notes": style,
    })
    review = {k: True for k in ("body_voice", "voice_personality", "body_personality", "overall")}
    revision = call("POST", f"/persons/{pid}/person-revisions", {
        "body": body["id"], "voice": voice["id"], "personality": personality["id"],
        "review": review, "reviewer": reviewer, "note": note,
    })
    call("POST", f"/persons/{pid}/activate", {"person_revision": revision["id"]})
    if select:
        call("POST", "/persons/select", {"person_id": pid})
    active = call("GET", "/persons/active", None)
    return {
        "person_id": pid,
        "person_revision": revision["id"],
        "selected": select,
        "active": active.get("active"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8099",
                    help="worker on loopback (default) or backend base URL")
    ap.add_argument("--token", default=None, help="device token when --base is the backend")
    ap.add_argument("--name", required=True)
    ap.add_argument("--instructions", required=True, help="system instructions (the persona)")
    ap.add_argument("--language", default="dansk")
    ap.add_argument("--style", default="")
    ap.add_argument("--body-source", default="unbound", help="bodyid-* from BodyRig, or 'unbound'")
    ap.add_argument("--voice-source", default="unbound",
                    help="VoiceRig .mrvoice package name (e.g. kaliv.mrvoice), or 'unbound'")
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--reviewed", action="store_true", help="I confirm the four compatibility checks")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-select", action="store_true", help="create and activate, but do not select")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    prefix = "/api/v1" if a.token else ""
    call = http_call(base + prefix, a.token)
    result = run(call, name=a.name, instructions=a.instructions, language=a.language,
                 style=a.style, body_source=a.body_source, voice_source=a.voice_source,
                 reviewer=a.reviewer, reviewed=a.reviewed, note=a.note, select=not a.no_select)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
