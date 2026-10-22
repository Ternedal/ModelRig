"""Opt-in ASR cold/warm timing probe. Never records transcripts or audio.

Run on a controlled worker environment, not on the production worker:
    python scripts/asr_cold_warm_probe.py --audio path/to/test.wav --runs 3

Each process starts with an unloaded model. Model construction is timed
separately from the first and subsequent transcriptions. No environment is modified.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--language", default="da", choices=("da", "en"))
    args = parser.parse_args()
    if args.runs < 2 or args.runs > 20:
        parser.error("--runs must be between 2 and 20")
    if not args.audio.is_file():
        parser.error("audio file does not exist")
    worker = Path(__file__).resolve().parents[1] / "worker"
    sys.path.insert(0, str(worker))
    from app import voice_asr

    durations = []
    try:
        load_start = time.perf_counter()
        voice_asr._get_model()
        model_load_seconds = round(time.perf_counter() - load_start, 3)
        for _ in range(args.runs):
            start = time.perf_counter()
            result = voice_asr.transcribe_wav(str(args.audio), language=args.language)
            elapsed = time.perf_counter() - start
            durations.append(round(elapsed, 3))
            if not isinstance(result, dict):
                raise RuntimeError("ASR returned unexpected response")
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 1
    warm = durations[1:]
    print(json.dumps({
        "ok": True,
        "device": voice_asr._device(),
        "model": voice_asr._model_name(),
        "compute": voice_asr._compute_type(),
        "language": args.language,
        "model_load_seconds": model_load_seconds,
        "first_inference_seconds": durations[0],
        "warm_seconds": warm,
        "warm_median_seconds": round(statistics.median(warm), 3),
        "first_to_warm_ratio": round(durations[0] / statistics.median(warm), 2)
            if statistics.median(warm) > 0 else None,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
