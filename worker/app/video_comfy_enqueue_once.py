"""Explicit operator-only video enqueue. No network, models or background tasks."""
from __future__ import annotations

import argparse

from .video_contract import VideoRequest
from .video_job_store import VideoJobStore


def enqueue(prompt: str, *, width: int = 512, height: int = 320,
            fps: int = 16, duration_seconds: int = 3) -> str:
    """Validate first; then write one queued job to the external-volume store."""
    request = VideoRequest(kind="text_to_video", prompt=prompt, width=width,
                           height=height, fps=fps, duration_seconds=duration_seconds)
    return VideoJobStore.on_external_volume().create(request)


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue one experimental flat video job")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=320)
    parser.add_argument("--fps", type=int, default=16)
    parser.add_argument("--seconds", type=int, default=3)
    args = parser.parse_args()
    try:
        job_id = enqueue(args.prompt, width=args.width, height=args.height,
                         fps=args.fps, duration_seconds=args.seconds)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"Video enqueue unavailable: {type(exc).__name__}: {exc}\n")
    print(f"Queued video job: {job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
