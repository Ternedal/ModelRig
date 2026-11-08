#!/usr/bin/env python3
"""Contract test for tests/support/check_wav.py, the audio check in ci.yml's frozen-worker step.

ChatGPT #2362 6720023370: the step first sliced the WAV at a fixed 44-byte offset, so a missing or
truncated file gave an opaque index error instead of a verdict. The check now parses the RIFF
structure. Here every way the packaged Piper could fail to produce audio has to be named for what
it is, and real audio has to pass.

Run: python3 tests/workflow_wav_check.py
"""
from __future__ import annotations

import io
import math
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "tests" / "support" / "check_wav.py"

passed = failed = 0


def check(ok: bool, message: str) -> None:
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}: {message}")
    if ok:
        passed += 1
    else:
        failed += 1


def wav_bytes(seconds: float = 0.45, rate: int = 22050, width: int = 2, channels: int = 1, silent: bool = False) -> bytes:
    frames = int(seconds * rate)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 2:
            values = [0 if silent else int(9000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(frames)]
            w.writeframes(struct.pack(f"<{frames * channels}h", *[v for v in values for _ in range(channels)]))
        else:
            w.writeframes(bytes(frames * channels * width))
    return out.getvalue()


def run(data: bytes | None) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.wav"
        if data is not None:
            path.write_bytes(data)
        result = subprocess.run([sys.executable, str(CHECK), str(path), "--rate", "22050", "--min-seconds", "0.1"],
                                capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr


good = wav_bytes()
code, out = run(good)
check(code == 0 and "valid audio: 0.45 s, 22050 Hz" in out, f"real 16-bit mono audio passes ({out.strip()})")

float_wav = bytearray(good)
float_wav[20:22] = struct.pack("<H", 3)  # fmt chunk: audio format 3 (IEEE float) instead of 1 (PCM)
truncated_data = good[:len(good) // 2]  # header promises more frames than the data chunk holds

cases = {
    "a missing file": (None, "no such file"),
    "an empty file": (b"", "too short to be a WAV file"),
    "a file shorter than any WAV header": (good[:30], "too short to be a WAV file"),
    "a file that is not RIFF": (b"JUNK" + good[4:], "not a PCM WAV file"),
    "a RIFF file that is not WAVE": (good[:8] + b"AVI " + good[12:], "not a PCM WAV file"),
    "a non-PCM WAV": (bytes(float_wav), "not a PCM WAV file"),
    "a data chunk cut short": (truncated_data, "truncated"),
    "silence": (wav_bytes(silent=True), "silent"),
    "the wrong sample rate": (wav_bytes(rate=16000), "sample rate 16000, expected 22050"),
    "8-bit samples": (wav_bytes(width=1), "8-bit samples, expected 16-bit PCM"),
    "stereo": (wav_bytes(channels=2), "2 channels, expected mono"),
    "too little audio": (wav_bytes(seconds=0.05), "expected at least 0.1 s"),
}
for name, (data, reason) in cases.items():
    code, out = run(data)
    check(code == 1 and reason in out and "Traceback" not in out, f"{name} is refused as '{reason}' ({out.strip()})")

workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
check("python tests/support/check_wav.py $wav --rate 22050 --min-seconds 0.1" in workflow,
      "ci.yml's frozen-worker step uses this check")
check("[44.." not in workflow, "ci.yml no longer slices the WAV at a fixed 44-byte offset")
check("--scope tests/support/check_wav.py" in workflow, "a change to the check runs the frozen-worker job")

print(f"\n===== WAV CHECK: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
