"""A sentence TTS cannot voice must skip, not kill the whole turn.

Found on the rig 26/07, twice in a row -- 39 of 40 voice turns completed, and
the one failure took the whole gate down with it:

    voice stream error 500: # channels not specified

The message is a lie told by an error inside an error. What actually happened:
Piper produced no audio for one sentence, so nothing was ever written to the
wave file. `getframerate()` then raised "frame rate not set", and while THAT
exception was unwinding, the `with` block's exit called close(), which raised
"# channels not specified" on top. The second error is the one that surfaced,
and it says nothing about the cause.

Why Piper produces nothing: `strip_markdown` removes markup and emoji, and the
pipeline skips a sentence that strips to empty. But a sentence that strips to
"—" or "..." is NOT empty -- it has characters and no words. Piper has nothing
to say, writes no frames, and the file never gets a header.

Two defects, so two fixes:

  * `synthesize_to_wav` must not turn "no audio" into a crash. It reports zero
    frames and leaves a valid file behind.
  * the pipeline must not hand TTS text with nothing speakable in it, and must
    skip a chunk that produced no audio.

Neither is cosmetic. A single unspeakable sentence in a forty-turn baseline was
enough to fail a rig day.

Run: PYTHONPATH=worker python3 tests/worker_voice_tts_empty_synthesis.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import voice_tts  # noqa: E402
from app.voice_pipeline import has_speech, strip_markdown  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


class _SilentVoice:
    """Piper when it has nothing to say: it writes nothing at all."""

    def synthesize_wav(self, text, wav_file):  # noqa: ARG002
        return None


class _RealishVoice:
    """Piper on ordinary text: params, then frames."""

    def synthesize_wav(self, text, wav_file):  # noqa: ARG002
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x01" * 2205)   # 0.1 s


_tmp = tempfile.mkdtemp(prefix="kaliv-tts-")


def synth(voice, text):
    out = os.path.join(_tmp, f"chunk_{abs(hash(text)) % 9999:04d}.wav")
    voice_tts._voice = voice          # type: ignore[attr-defined]
    voice_tts._load_error = None      # type: ignore[attr-defined]
    return out, voice_tts.synthesize_to_wav(text, out)


# --------------------------------------------------------- ordinary synthesis
out, res = synth(_RealishVoice(), "Motoren suger luft ind.")
check(res is not None and res.get("duration", 0) > 0,
      f"almindelig tekst giver lyd med varighed (fik {res.get('duration') if res else None})")
check(os.path.exists(out) and os.path.getsize(out) > 44,
      "wav-filen er skrevet og har indhold")


# ---------------------------------- THE REGRESSION: Piper produces no audio
try:
    out, res = synth(_SilentVoice(), "\u2014")
    crashed = None
except Exception as exc:                     # noqa: BLE001
    crashed = f"{type(exc).__name__}: {exc}"
    res = None

check(crashed is None,
      f"tavs syntese kaster IKKE -- det var rig-fejlen (fik {crashed})")
check(res is not None and res.get("duration") == 0,
      "tavs syntese rapporteres som nul varighed, ikke som en fejl")
if crashed is None and os.path.exists(out):
    try:
        with wave.open(out, "rb") as fh:
            readable = fh.getnframes() == 0
    except Exception:                        # noqa: BLE001
        readable = False
    check(readable,
          "filen der bliver tilbage er en gyldig, tom wav -- ikke en halv fil "
          "der kaster naar nogen aabner den")


# ------------------------------------------- the input guard the pipeline needs
unspeakable = ["\u2014", "...", "!", "  \u2013  ", "**", "\u2022", "?!", "\u2026", "   "]
missed = [t for t in unspeakable if has_speech(t)]
check(not missed, f"ordloes tekst naar ikke TTS (slap igennem: {missed})")

speakable_texts = ["Motoren suger luft ind.", "Trin 1.", "ok", "42", "A."]
blocked = [t for t in speakable_texts if not has_speech(t)]
check(not blocked, f"aegte tekst blokeres ikke (blokeret: {blocked})")

# strip_markdown alene er ikke nok -- den efterlader tegnsaetning, og det var
# praecis derfor den gamle guard (`if not speakable`) slap em-dashen igennem.
check(strip_markdown("\u2014").strip() != "" and not has_speech(strip_markdown("\u2014")),
      "strip_markdown efterlader '\u2014' som IKKE-tom, men has_speech fanger "
      "den -- det er hullet den gamle guard havde")

print(f"\n===== VOICE TTS EMPTY SYNTHESIS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
