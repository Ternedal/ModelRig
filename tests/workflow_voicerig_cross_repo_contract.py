#!/usr/bin/env python3
"""ModelRig must speak VoiceRig's wire, including how it encodes headers.

VoiceRig builds .mrvoice profiles; ModelRig asks it to speak as a person and
then decides whether the person's own voice was used. That decision is a
string comparison across a repository boundary, and it was wrong: VoiceRig
percent-encodes header values so they stay ASCII, and we compared the raw
header to the name we sent. "søren-stemme.mrvoice" -- VoiceRig's own test
case -- came back "s%C3%B8ren-stemme.mrvoice" and voice_bound said false
while the right package had been used. Danish names only, which is every
name that matters here.

Verified 5/9/2026 against VoiceRig commit 03f41c1c2d3b8d03690c6abadf1221e78f1792a8:
request field `voice_package`, response headers X-VoiceRig-Voice,
-Voice-ID and -Package, encoded with quote(value, safe="._-").
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "worker"))

from app.voice_tts import _decoded_package  # noqa: E402

# Exactly VoiceRig's own _ascii_header (voicerig/app/tts_api.py).
def voicerig_header(value: str) -> str:
    return quote(str(value), safe="._-")


passed = failed = 0


def check(condition: object, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


for name in ("voice.mrvoice", "søren-stemme.mrvoice", "kaliv-æøå.mrvoice",
             "navn med mellemrum.mrvoice", "Kaliv_2.mrvoice"):
    sent = voicerig_header(name)
    check(_decoded_package({"X-VoiceRig-Package": sent}) == name,
          f"a package VoiceRig encoded is recognised again: {name!r}")

check(_decoded_package({}) is None, "a missing header stays None, not an empty match")
check(_decoded_package({"X-VoiceRig-Package": voicerig_header("anden.mrvoice")}) != "kaliv.mrvoice",
      "a genuinely different package is still a mismatch")
# ASCII names must be unaffected: quote() leaves them alone, and so must we.
check(voicerig_header("voice.mrvoice") == "voice.mrvoice",
      "VoiceRig leaves ASCII names untouched, so nothing changes for them")

print(f"\n===== VOICERIG CROSS-REPO CONTRACT: {passed} passed, {failed} failed =====")
if failed:
    raise SystemExit(1)
