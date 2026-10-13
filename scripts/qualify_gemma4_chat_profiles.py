"""Opt-in local ModelRig Ollama chat qualification; no actions or cloud access.

Usage (PowerShell, from repo root):
  $env:MODELRIG_OLLAMA_URL="http://127.0.0.1:11434"
  .\\venv\\Scripts\\python.exe scripts/qualify_gemma4_chat_profiles.py --run-live --model gemma4:26b

The script uses only the existing worker ollama_client.chat path; the default
is dry-run. Prompts contain no personal data. Output never prints responses.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

PROMPTS = (
    "Forklar kort forskellen på RAM og VRAM på dansk.",
    "Hvad er to fordele og en ulempe ved lokal AI?",
    "Forklar på dansk hvorfor et afbrudt modelsvar ikke må vises som færdigt.",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Actually call local Ollama")
    parser.add_argument("--model", default="gemma4:26b")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("validation/gemma4-chat-profiles.json"))
    return parser.parse_args()


async def _sample(chat, model: str, mode: str | None, prompt: str) -> dict:
    if mode is None:
        os.environ.pop("MODELRIG_EXPERIMENTAL_CHAT_PROFILE", None)
    else:
        os.environ["MODELRIG_EXPERIMENTAL_CHAT_PROFILE"] = mode
    started = time.perf_counter()
    try:
        answer = await chat([{"role": "user", "content": prompt}], model=model)
    except Exception as exc:
        return {"ok": False, "seconds": round(time.perf_counter() - started, 3),
                "error_type": type(exc).__name__}
    return {"ok": bool(answer and answer.strip()),
            "seconds": round(time.perf_counter() - started, 3),
            "answer_chars": len(answer or "")}


async def _run(model: str, repeats: int) -> dict:
    from app.ollama_client import chat

    # Interleave modes for the same prompt to reduce warm-model and
    # prompt-difficulty bias. No concurrent requests: env profile is process-wide.
    labels = ("baseline", "voice_brief", "chat_brief", "detailed")
    rows_by_label = {label: [] for label in labels}
    for i in range(repeats):
        prompt = PROMPTS[i % len(PROMPTS)]
        # Rotate order each round so baseline is not always first.
        ordered = labels[i % len(labels):] + labels[:i % len(labels)]
        for label in ordered:
            mode = None if label == "baseline" else label
            rows_by_label[label].append(await _sample(chat, model, mode, prompt))
    results = {}
    for label, rows in rows_by_label.items():
        successful = [row["seconds"] for row in rows if row["ok"]]
        results[label] = {
            "measurements": rows,
            "median_seconds": round(statistics.median(successful), 3) if successful else None,
            "all_successful": len(successful) == len(rows),
        }
    return results


def main() -> int:
    args = _parse_args()
    if args.repeats < 1 or args.repeats > 20:
        raise SystemExit("--repeats must be 1..20")
    if not args.run_live:
        print("DRY RUN: no inference or rig access attempted. Pass --run-live to execute.")
        return 0
    original_profile = os.environ.get("MODELRIG_EXPERIMENTAL_CHAT_PROFILE")
    try:
        results = asyncio.run(_run(args.model, args.repeats))
    finally:
        if original_profile is None:
            os.environ.pop("MODELRIG_EXPERIMENTAL_CHAT_PROFILE", None)
        else:
            os.environ["MODELRIG_EXPERIMENTAL_CHAT_PROFILE"] = original_profile
    report = {
        "model": args.model,
        "repeats": args.repeats,
        "profiles": results,
        "limitations": [
            "Non-streaming local worker chat only; no TTS/ASR or first-audio metric",
            "Latency includes warm/cold state and host contention",
            "Answer quality and safety require separate human review",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}; no answer content included")
    for label, stats in results.items():
        print(f"{label}: median={stats['median_seconds']}s all_successful={stats['all_successful']}")
    return 0 if all(s["all_successful"] for s in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
