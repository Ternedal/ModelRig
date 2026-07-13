"""strip_markdown = the "speakable text" cleaner for the TTS path.

Two properties, both regression-guarded here:
  1. Emojis/pictographs are removed (2026-07-13: emojis dropped from the chat
     display were still read aloud, because the audio path never stripped them).
  2. Markdown markers are removed but the words survive (2026-07-09: Piper read
     "**bold**" as "stjerne stjerne bold stjerne stjerne").

And the guard that matters most: ordinary Danish text, digits, punctuation and
lone math asterisks must pass through untouched -- the stripper must not eat real
content on its way to muting decoration.

Run: PYTHONPATH=worker python3 tests/worker_voice_strip.py
"""
from __future__ import annotations

import sys

from app.voice_pipeline import strip_markdown as s

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def eq(inp, want, name):
    got = s(inp)
    check(got == want, f"{name}: {inp!r} -> {got!r}" + ("" if got == want else f" (want {want!r})"))


def no_emoji(inp, name):
    got = s(inp)
    # nothing left in the emoji/pictograph/dingbat/symbol ranges
    bad = [c for c in got if 0x1F000 <= ord(c) <= 0x1FAFF
           or 0x2600 <= ord(c) <= 0x27BF or 0x2B00 <= ord(c) <= 0x2BFF
           or 0x2300 <= ord(c) <= 0x23FF or ord(c) in (0x200D,) or 0xFE00 <= ord(c) <= 0xFE0F]
    check(not bad, f"{name}: {inp!r} -> {got!r}" + ("" if not bad else f" (emoji left: {bad})"))


# --- emojis are removed from spoken text (the new fix) ---
no_emoji("Hej 🚀 verden 🎯", "rocket + target")
no_emoji("Perfekt ✅ det virker ⚠️", "check + warning (with variation selector)")
no_emoji("Fanø 🏝️ og Rømø 🌊 er øer", "island + wave")
no_emoji("👨‍👩‍👧 er en familie", "ZWJ family sequence")
no_emoji("Flag: 🇩🇰 🇸🇪", "regional-indicator flags")
no_emoji("⭐ topkarakter ⏳ vent", "star + hourglass")
eq("Hej 🚀 verden", "Hej verden", "emoji removed, spacing normalised")

# --- markdown is removed but words survive (existing behaviour) ---
eq("**Vigtigt**", "Vigtigt", "bold markers dropped")
eq("Kør `git status` nu", "Kør git status nu", "inline code unwrapped")
eq("### Overskrift", "Overskrift", "heading marker dropped")
eq("- punkt et", "punkt et", "bullet dropped")
eq("[ModelRig](https://x.dev)", "ModelRig", "link text kept, url dropped")

# --- combined ---
eq("**Vigtigt** 🎯 se her", "Vigtigt se her", "markdown + emoji together")

# --- the guard: real content must survive ---
eq("Møn ligger i Østersøen, æbler koster 5 kr.", "Møn ligger i Østersøen, æbler koster 5 kr.",
   "Danish letters, digits, punctuation intact")
eq("Ring på 5 * 3 = 15", "Ring på 5 * 3 = 15", "lone math asterisk survives")
eq("Filen hedder my_file_name.txt", "Filen hedder my_file_name.txt", "underscores in a filename survive")
eq("Prisen er 250 € eller 1.800 kr.", "Prisen er 250 € eller 1.800 kr.", "currency + thousands separator intact")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
