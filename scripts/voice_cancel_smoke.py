#!/usr/bin/env python3
"""Isolated four-probe Kaliv voice cancellation smoke test.

Run against a loopback-only test worker. Does not change the worker or production.
Uses the repository's existing streaming and cleanup test primitives.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import voice_baseline as vb


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-url", default="http://127.0.0.1:8101")
    parser.add_argument("--fixture", type=Path, default=Path("validation/voice-fixtures/turn-01.wav"))
    parser.add_argument("--probes", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--cleanup-timeout", type=float, default=15)
    parser.add_argument("--report", type=Path, default=Path("validation/voice-cancel-smoke.json"))
    args = parser.parse_args()

    if not 1 <= args.probes <= 20:
        parser.error("--probes must be between 1 and 20")
    if not 1 <= args.cleanup_timeout <= 120:
        parser.error("--cleanup-timeout must be between 1 and 120")
    if not 1 <= args.timeout <= 900:
        parser.error("--timeout must be between 1 and 900")

    # Enforces the same localhost-only restriction as voice_baseline.py.
    vb.parse_worker_url(args.worker_url)
    raw = args.fixture.read_bytes()
    if len(raw) < 44 or raw[:4] not in (b"RIFF", b"RF64") or raw[8:12] != b"WAVE":
        parser.error("fixture must be a non-empty WAV file")

    vb.get_json(args.worker_url, "/healthz", min(args.timeout, 10))
    # Remember the entire campaign's starting temp state.  A leaked directory
    # from probe 2 must not become invisible merely because probe 3 snapshots
    # it in its own "before" set.
    campaign_before = vb._voice_temp_entries()
    results = []
    for index in range(args.probes):
        trigger = "transcript" if index % 2 == 0 else "first_chunk"
        before = vb._voice_temp_entries()
        item = {
            "probe": index + 1,
            "trigger": trigger,
            "aborted": False,
            "worker_healthy": False,
            "cleanup": None,
            "error": None,
        }
        try:
            state = vb.stream_turn(
                args.worker_url,
                audio_bytes=raw,
                language="da",
                model=None,
                timeout_s=args.timeout,
                abort_after=trigger,
            )
            item["aborted"] = bool(state["aborted"])
        except Exception as exc:
            item["error"] = vb._safe_error(exc)
        finally:
            item["cleanup"] = vb.wait_for_cleanup(before, timeout_s=args.cleanup_timeout)
            try:
                vb.get_json(args.worker_url, "/healthz", min(args.timeout, 10))
                item["worker_healthy"] = True
            except Exception as exc:
                item["error"] = item["error"] or vb._safe_error(exc)

        item["passed"] = (
            item["aborted"]
            and item["worker_healthy"]
            and bool(item["cleanup"]["clean"])
            and item["error"] is None
        )
        results.append(item)
        print(
            f"Probe {index + 1}/{args.probes} {trigger}: "
            f"{'PASS' if item['passed'] else 'FAIL'} "
            f"(aborted={item['aborted']}, "
            f"cleanup={item['cleanup']['clean']}, "
            f"healthy={item['worker_healthy']})",
            flush=True,
        )

    passed = sum(1 for result in results if result["passed"])
    campaign_cleanup = vb.wait_for_cleanup(
        campaign_before, timeout_s=args.cleanup_timeout
    )
    report = {
        "schema": "kaliv-voice-cancel-smoke/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": vb._git_sha(Path(__file__).resolve().parents[1]),
        "worker_url": args.worker_url,
        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
        "probes": results,
        "campaign_cleanup": campaign_cleanup,
        "summary": {
            "passed": passed,
            "total": args.probes,
            "gate_passed": passed == args.probes and campaign_cleanup["clean"],
        },
    }
    vb._write_json_atomic(args.report, report)
    print(
        f"Result: {passed}/{args.probes} probes; "
        f"whole-campaign cleanup={campaign_cleanup['clean']}; "
        f"report: {args.report}",
        flush=True,
    )
    return 0 if report["summary"]["gate_passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, vb.VoiceBaselineError, ValueError) as exc:
        print(f"SETUP FAILED: {exc}", file=sys.stderr)
        sys.exit(2)
