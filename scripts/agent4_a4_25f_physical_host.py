#!/usr/bin/env python3
"""Run the A4-25f dormant v2 snapshot read host on loopback only.

This is a physical-test host, not production bootstrap. It opens only the
immutable snapshot authority plus append-only timeline/evidence history needed
by Agent4SnapshotOperatorReadService. It owns no campaign repository, scheduler,
resource manager, handoff executor, publication path or background lifecycle.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.snapshot_operator import Agent4SnapshotOperatorReadService  # noqa: E402
from app.agent4.snapshot_operator_api import build_agent4_snapshot_operator_router  # noqa: E402
from app.agent4.snapshot_store import JsonOperatorSnapshotStore  # noqa: E402
from app.agent4.timeline import JsonCampaignTimelineStore  # noqa: E402
from app.agent4.timeline_evidence import JsonCampaignEvidenceRecordStore  # noqa: E402

MARKER_SCHEMA = "modelrig-agent4/a4-25f-output-root/v1"
HEALTH_SCHEMA = "modelrig-agent4/a4-25f-physical-host-health/v1"
LOOPBACK = "127.0.0.1"
MAX_CLOCK_OFFSET_MINUTES = 120


def _git_head() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_exact_head(expected_sha: str) -> str:
    if len(expected_sha) != 40 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise ValueError("expected SHA must be 40 lowercase hexadecimal characters")
    actual = _git_head()
    if actual != expected_sha:
        raise RuntimeError(f"wrong checkout: expected {expected_sha}, got {actual}")
    return actual


def _require_data_root(data_root: Path) -> Path:
    resolved = data_root.expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("A4-25f physical data root must stay outside repository")
    if resolved.name != "fixture-data":
        raise ValueError("A4-25f host requires the marked workspace fixture-data directory")
    marker = resolved.parent / ".modelrig-a4-25f-output.json"
    if not marker.is_file():
        raise RuntimeError("A4-25f output marker is missing")
    raw = json.loads(marker.read_text(encoding="utf-8"))
    if raw.get("schema") != MARKER_SCHEMA or raw.get("production_activation") is not False:
        raise RuntimeError("A4-25f output marker is invalid")
    if not resolved.is_dir():
        raise RuntimeError("A4-25f fixture-data directory is missing")
    return resolved


def _require_clock_offset(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("clock offset must be an integer number of minutes")
    if value < 0 or value > MAX_CLOCK_OFFSET_MINUTES:
        raise ValueError(
            f"clock offset must be between 0 and {MAX_CLOCK_OFFSET_MINUTES} minutes"
        )
    return value


def build_app(
    data_root: Path,
    *,
    expected_sha: str,
    clock_offset_minutes: int = 0,
) -> FastAPI:
    repository_sha = _require_exact_head(expected_sha)
    data_root = _require_data_root(data_root)
    offset = _require_clock_offset(clock_offset_minutes)
    snapshots = JsonOperatorSnapshotStore(
        data_root / "operator-snapshots",
        clock=lambda: datetime.now(timezone.utc) + timedelta(minutes=offset),
    )
    current = snapshots.load_current()
    if current is None:
        raise RuntimeError("A4-25f immutable current root is missing")
    operator = Agent4SnapshotOperatorReadService(
        snapshots=snapshots,
        timeline=JsonCampaignTimelineStore(data_root / "timeline"),
        evidence=JsonCampaignEvidenceRecordStore(data_root / "evidence"),
    )
    app = FastAPI(
        title="ModelRig A4-25f physical snapshot host",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(build_agent4_snapshot_operator_router(operator))

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        selected = snapshots.load_current()
        if selected is None:
            raise RuntimeError("A4-25f immutable current root disappeared")
        return {
            "schema": HEALTH_SCHEMA,
            "repository_sha": repository_sha,
            "current_snapshot_id": selected.snapshot_id,
            "root_sequence": selected.root_sequence,
            "retention_clock_offset_minutes": offset,
            "writer_authority": False,
            "publication_authority": False,
            "background_runtime": False,
            "public_network": False,
            "production_activation": False,
        }

    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--host", default=LOOPBACK)
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--clock-offset-minutes", type=int, default=0)
    args = parser.parse_args()
    if args.host != LOOPBACK:
        raise ValueError("A4-25f worker host is hard-limited to 127.0.0.1")
    if not 1024 <= args.port <= 65535:
        raise ValueError("A4-25f host port must be between 1024 and 65535")
    app = build_app(
        args.data_root,
        expected_sha=args.expected_sha,
        clock_offset_minutes=args.clock_offset_minutes,
    )
    uvicorn.run(
        app,
        host=LOOPBACK,
        port=args.port,
        access_log=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
