#!/usr/bin/env python3
"""Check that a file is a complete, non-silent PCM WAV, or say exactly what is wrong.

Used by ci.yml's frozen-worker step on what the packaged Piper wrote (#2362). The structure is
parsed by the standard library's `wave` module (RIFF/WAVE, a PCM `fmt ` chunk, the `data` chunk),
never by assuming a fixed 44-byte header, and the samples are read from the data chunk itself:

    python tests/support/check_wav.py OUT.wav --rate 22050 --min-seconds 0.1

Exit 0 and one summary line when the audio is valid; exit 1 and the reason otherwise. Covered by
tests/workflow_wav_check.py.
"""
from __future__ import annotations

import argparse
import array
import os
import sys
import wave

MIN_AUDIBLE = 0.01  # at least 1 % of the samples are not zero


def problem(path: str, rate: int, min_seconds: float) -> str | None:
    """None when `path` is valid audio, otherwise why it is not."""
    if not os.path.isfile(path):
        return "no such file"
    size = os.path.getsize(path)
    if size < 44:
        return f"{size} bytes: too short to be a WAV file"
    try:
        with wave.open(path, "rb") as w:
            channels, width, actual_rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            data = w.readframes(frames)
    except (wave.Error, EOFError) as exc:
        return f"not a PCM WAV file: {exc}"
    if actual_rate != rate:
        return f"sample rate {actual_rate}, expected {rate}"
    if width != 2:
        return f"{8 * width}-bit samples, expected 16-bit PCM"
    if channels != 1:
        return f"{channels} channels, expected mono"
    if len(data) != frames * channels * width:
        return f"truncated: the header promises {frames} frames, the data chunk holds {len(data) // (channels * width)}"
    if frames < min_seconds * rate:
        return f"{frames / rate:.3f} s of audio, expected at least {min_seconds} s"
    samples = array.array("h")
    samples.frombytes(data)
    if sys.byteorder == "big":
        samples.byteswap()
    audible = sum(1 for s in samples if s)
    if audible < MIN_AUDIBLE * len(samples):
        return f"silent: {audible} of {len(samples)} samples are not zero"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path")
    parser.add_argument("--rate", type=int, required=True)
    parser.add_argument("--min-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    reason = problem(args.path, args.rate, args.min_seconds)
    if reason:
        print(f"invalid audio in {args.path}: {reason}")
        return 1
    with wave.open(args.path, "rb") as w:
        print(f"valid audio: {w.getnframes() / w.getframerate():.2f} s, {w.getframerate()} Hz, 16-bit mono PCM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
