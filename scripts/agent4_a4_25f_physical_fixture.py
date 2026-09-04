#!/usr/bin/env python3
"""Build the isolated A4-25f physical snapshot-authority fixture.

The fixture is preparation only. It composes the canonical Agent 4 writer,
creates harmless synthetic campaigns/timeline/evidence, explicitly publishes
one immutable A4-25 root and verifies the dormant snapshot read service against
that root. It never mounts an API, starts background work, dispatches Agent 3 or
touches product data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.composition import compose_agent4_runtime  # noqa: E402
from app.agent4.domain import (  # noqa: E402
    CampaignEventKind,
    CampaignSpec,
)
from app.agent4.handoff import (  # noqa: E402
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalRequest,
    DispatchOutcomeKind,
)
from app.agent4.snapshot_operator import Agent4SnapshotOperatorReadService  # noqa: E402
from app.agent4.timeline_evidence import CampaignEvidenceReference  # noqa: E402

SCHEMA = "modelrig-agent4/a4-25f-physical-fixture/v1"
MARKER_SCHEMA = "modelrig-agent4/a4-25f-output-root/v1"
SELECTED_CAMPAIGN_ID = "a4-25f-physical-primary"
CAMPAIGN_COUNT = 31
EVIDENCE_COUNT = 31


class _NoExternalExecutor:
    """Fixture boundary that refuses every external handoff."""

    def dispatch(self, request: CampaignDispatchRequest):
        raise RuntimeError(f"A4-25f fixture forbids dispatch {request.dispatch_id}")

    def signal(self, request: CampaignSignalRequest):
        raise RuntimeError(f"A4-25f fixture forbids signal {request.signal_id}")

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        return CampaignDispatchOutcome(
            dispatch_id=dispatch_id,
            kind=DispatchOutcomeKind.UNKNOWN,
        )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _require_exact_head(expected_sha: str) -> str:
    if len(expected_sha) != 40 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise ValueError("expected SHA must be 40 lowercase hexadecimal characters")
    actual = _git_head()
    if actual != expected_sha:
        raise RuntimeError(f"wrong checkout: expected {expected_sha}, got {actual}")
    return actual


def _outside_repository(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = ROOT.resolve()
    try:
        resolved.relative_to(repo)
    except ValueError:
        pass
    else:
        raise ValueError("A4-25f physical output must stay outside the repository")
    if resolved == resolved.parent:
        raise ValueError("filesystem root cannot be used as A4-25f output")
    return resolved


def _prepare_output(output_root: Path, *, replace: bool) -> tuple[Path, Path]:
    output_root = _outside_repository(output_root)
    marker = output_root / ".modelrig-a4-25f-output.json"
    data_root = output_root / "fixture-data"
    manifest_path = output_root / "fixture-manifest.json"

    if output_root.exists() and any(output_root.iterdir()) and not marker.is_file():
        raise RuntimeError(
            "non-empty output root is not an existing ModelRig A4-25f workspace"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    if marker.exists():
        raw = json.loads(marker.read_text(encoding="utf-8"))
        if raw.get("schema") != MARKER_SCHEMA:
            raise RuntimeError("A4-25f output marker has an unsupported schema")
    else:
        marker.write_text(
            json.dumps(
                {"schema": MARKER_SCHEMA, "production_activation": False},
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    existing = data_root.exists() or manifest_path.exists()
    if existing and not replace:
        raise RuntimeError("A4-25f fixture already exists; pass --replace explicitly")
    if data_root.exists():
        shutil.rmtree(data_root)
    if manifest_path.exists():
        manifest_path.unlink()
    mutations = output_root / "mutations"
    if mutations.exists():
        if not replace:
            raise RuntimeError("A4-25f mutation receipts already exist")
        shutil.rmtree(mutations)
    return data_root, manifest_path


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_fixture(
    output_root: Path,
    *,
    expected_sha: str,
    replace: bool,
) -> dict[str, object]:
    actual_sha = _require_exact_head(expected_sha)
    data_root, manifest_path = _prepare_output(output_root, replace=replace)

    base_time = datetime.now(timezone.utc).replace(microsecond=0)
    context = compose_agent4_runtime(
        data_root,
        executor=_NoExternalExecutor(),
        resource_capacities={"physical-fixture": 1},
        resource_resolver=lambda _spec: {"physical-fixture": 1},
        resource_lease_ttl=timedelta(minutes=30),
    )

    # Keep the selected campaign queued. This allows the physical mutation
    # harness to exercise a real canonical state revision via request_cancel()
    # without any external handoff/signal authority.
    context.scheduler.submit(
        CampaignSpec(
            campaign_id=SELECTED_CAMPAIGN_ID,
            name="A4-25f physical snapshot primary",
            workflow="agent3.read.fixture",
            created_at=base_time,
        )
    )

    fixture_events = [
        context.event_recorder.record(
            SELECTED_CAMPAIGN_ID,
            CampaignEventKind.CHECKPOINTED,
            occurred_at=base_time + timedelta(seconds=index),
            payload={
                "fixture": "a4-25f",
                "ordinal": index,
                "production_activation": False,
            },
        )
        for index in range(1, EVIDENCE_COUNT + 1)
    ]

    artifacts = data_root / "physical-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    for index in range(1, EVIDENCE_COUNT + 1):
        evidence_id = f"a4-25f-evidence-{index:03d}"
        payload = {
            "schema": "modelrig-agent4/a4-25f-evidence-fixture/v1",
            "campaign_id": SELECTED_CAMPAIGN_ID,
            "evidence_id": evidence_id,
            "ordinal": index,
            "production_activation": False,
        }
        payload_bytes = _canonical_json(payload) + b"\n"
        artifact = artifacts / f"{evidence_id}.json"
        artifact.write_bytes(payload_bytes)
        context.evidence_recorder.record(
            SELECTED_CAMPAIGN_ID,
            CampaignEvidenceReference(
                evidence_id=evidence_id,
                media_type="application/json",
                location=f"physical-artifacts/{evidence_id}.json",
                sha256=hashlib.sha256(payload_bytes).hexdigest(),
                size_bytes=len(payload_bytes),
                metadata={
                    "fixture": "a4-25f",
                    "ordinal": index,
                    "production_activation": False,
                },
            ),
            recorded_at=base_time + timedelta(seconds=index),
            related_event_id=fixture_events[index - 1].event_id,
        )

    for index in range(1, CAMPAIGN_COUNT):
        context.scheduler.submit(
            CampaignSpec(
                campaign_id=f"a4-25f-physical-{index:03d}",
                name=f"A4-25f physical list campaign {index:03d}",
                workflow="agent3.read.fixture",
                created_at=base_time - timedelta(minutes=index),
            )
        )

    if context.repository.pending_projections():
        raise RuntimeError("fixture contains unreconciled projection intents")

    root = context.publish_operator_snapshot()
    operator = Agent4SnapshotOperatorReadService(
        snapshots=context.snapshot_store,
        timeline=context.timeline,
        evidence=context.evidence_records,
    )
    campaigns = operator.campaign_page(snapshot_id=root.snapshot_id, limit=1_000)
    detail = operator.campaign(SELECTED_CAMPAIGN_ID, snapshot_id=root.snapshot_id)
    timeline = operator.timeline_page(
        SELECTED_CAMPAIGN_ID,
        snapshot_id=root.snapshot_id,
        limit=1_000,
    )
    evidence = operator.evidence_page(
        SELECTED_CAMPAIGN_ID,
        snapshot_id=root.snapshot_id,
        limit=1_000,
    )
    verification = operator.verification(
        SELECTED_CAMPAIGN_ID,
        snapshot_id=root.snapshot_id,
    )

    if len(campaigns.campaigns) != CAMPAIGN_COUNT:
        raise RuntimeError("campaign fixture count is incomplete")
    if len(timeline.page.entries) <= 25:
        raise RuntimeError("timeline fixture does not cross the physical page boundary")
    if len(evidence.page.records) != EVIDENCE_COUNT:
        raise RuntimeError("evidence fixture count is incomplete")
    if verification.verification.record_count != EVIDENCE_COUNT:
        raise RuntimeError("evidence verification count is incomplete")
    if any(
        value != root.snapshot_id
        for value in (
            campaigns.snapshot_id,
            detail.snapshot_id,
            timeline.snapshot_id,
            evidence.snapshot_id,
            verification.snapshot_id,
        )
    ):
        raise RuntimeError("snapshot read fixture did not stay on one immutable root")

    selected_snapshot_id = root.campaigns[SELECTED_CAMPAIGN_ID]
    selected_snapshot = context.snapshot_store.load_campaign(selected_snapshot_id)
    persisted_files = sorted(path for path in data_root.rglob("*") if path.is_file())
    manifest: dict[str, object] = {
        "schema": SCHEMA,
        "created_at": _iso(base_time),
        "repository_sha": actual_sha,
        "data_root": str(data_root.resolve()),
        "selected_campaign_id": SELECTED_CAMPAIGN_ID,
        "root_snapshot_id": root.snapshot_id,
        "root_sequence": root.root_sequence,
        "root_parent_snapshot_id": root.parent_snapshot_id,
        "selected_campaign_snapshot_id": selected_snapshot_id,
        "selected_state_revision": selected_snapshot.state_revision,
        "campaign_count": len(campaigns.campaigns),
        "timeline_count": len(timeline.page.entries),
        "timeline_head": (
            f"sha256:{selected_snapshot.timeline_head_sha256}"
            if selected_snapshot.timeline_head_sha256 is not None
            else None
        ),
        "evidence_count": len(evidence.page.records),
        "evidence_head": (
            f"sha256:{selected_snapshot.evidence_head_sha256}"
            if selected_snapshot.evidence_head_sha256 is not None
            else None
        ),
        "latest_evidence_timeline_head": (
            f"sha256:{selected_snapshot.latest_evidence_timeline_head_sha256}"
            if selected_snapshot.latest_evidence_timeline_head_sha256 is not None
            else None
        ),
        "persisted_file_count": len(persisted_files),
        "persisted_files_sha256": "sha256:"
        + hashlib.sha256(
            _canonical_json(
                [
                    {
                        "path": path.relative_to(data_root).as_posix(),
                        "size_bytes": path.stat().st_size,
                        "sha256": f"sha256:{_sha256_file(path)}",
                    }
                    for path in persisted_files
                ]
            )
        ).hexdigest(),
        "external_dispatch": False,
        "background_runtime": False,
        "api_mounted": False,
        "public_network": False,
        "production_activation": False,
    }
    manifest_bytes = _canonical_json(manifest)
    manifest["manifest_sha256"] = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    build_fixture(
        args.output_root,
        expected_sha=args.expected_sha,
        replace=args.replace,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
