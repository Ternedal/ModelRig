#!/usr/bin/env python3
"""Build the isolated A4-18R read-product fixture outside the repository.

The fixture uses the canonical Agent 4 composition/persistence services, but it
never mounts an API, starts background work, or grants lifecycle authority.  A
small in-process executor acknowledges exactly one fixture dispatch so the
selected campaign has real lifecycle/timeline state without external execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4 import (  # noqa: E402
    CampaignEventKind,
    CampaignEvidenceReference,
    CampaignSpec,
    compose_agent4_runtime,
)
from app.agent4.handoff import (  # noqa: E402
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    DispatchOutcomeKind,
)

SCHEMA = "modelrig-agent4/a4-18r-physical-fixture/v1"
SELECTED_CAMPAIGN_ID = "a4-18r-physical-primary"
CAMPAIGN_COUNT = 31
EVIDENCE_COUNT = 31
FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@dataclass(slots=True)
class _Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class _FixtureExecutor:
    """In-process acknowledgement only; no external execution authority."""

    def __init__(self) -> None:
        self.outcomes: dict[str, CampaignDispatchOutcome] = {}

    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        acknowledgement = CampaignDispatchAcknowledgement(
            dispatch_id=request.dispatch_id,
            runtime_reference=f"fixture:{request.campaign_id}:{request.attempt}",
            evidence_pointer=f"fixture-dispatch:{request.dispatch_id}",
        )
        self.outcomes[request.dispatch_id] = CampaignDispatchOutcome(
            dispatch_id=request.dispatch_id,
            kind=DispatchOutcomeKind.RUNNING,
            runtime_reference=acknowledgement.runtime_reference,
            evidence_pointer=acknowledgement.evidence_pointer,
        )
        return acknowledgement

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        raise RuntimeError(f"A4-18R fixture forbids lifecycle signal {request.signal_id}")

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        return self.outcomes.get(
            dispatch_id,
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.UNKNOWN,
            ),
        )


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_output_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    repo = ROOT.resolve()
    if path.exists() and path.is_symlink():
        raise ValueError("A4-18R output root may not be a symlink")
    try:
        resolved.relative_to(repo)
    except ValueError:
        pass
    else:
        raise ValueError("A4-18R output root must stay outside the repository")
    if resolved == Path(resolved.anchor):
        raise ValueError("A4-18R output root may not be a filesystem root")
    return resolved


def inside_output(path: Path, output_root: Path) -> Path:
    root = safe_output_root(output_root)
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("A4-18R fixture paths must stay inside the output root") from exc
    return resolved


def build_fixture(
    output_root: Path,
    data_root: Path,
    manifest_path: Path,
    *,
    expected_sha: str,
    replace: bool,
) -> dict[str, object]:
    if not __import__("re").fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise ValueError("expected SHA must be 40 lowercase hex")
    output_root = safe_output_root(output_root)
    data_root = inside_output(data_root, output_root)
    manifest_path = inside_output(manifest_path, output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    if data_root.exists():
        if not replace:
            raise RuntimeError(f"fixture root already exists: {data_root}; use --replace")
        if data_root.is_symlink():
            raise RuntimeError("fixture root may not be a symlink")
        shutil.rmtree(data_root)
    if manifest_path.exists():
        if not replace:
            raise RuntimeError(f"fixture manifest already exists: {manifest_path}; use --replace")
        if manifest_path.is_symlink():
            raise RuntimeError("fixture manifest may not be a symlink")
        manifest_path.unlink()

    clock = _Clock(FIXED_TIME)
    context = compose_agent4_runtime(
        data_root,
        executor=_FixtureExecutor(),
        resource_capacities={"fixture-read": 1},
        resource_resolver=lambda _spec: {"fixture-read": 1},
        clock=clock,
        resource_lease_ttl=timedelta(minutes=30),
    )

    selected = context.scheduler.submit(
        CampaignSpec(
            campaign_id=SELECTED_CAMPAIGN_ID,
            name="A4-18R fysisk read-kampagne",
            workflow="agent3.read.fixture",
            created_at=FIXED_TIME,
        )
    )
    dispatched = context.scheduler.dispatch_ready()
    if dispatched is None or dispatched.record.spec.campaign_id != SELECTED_CAMPAIGN_ID:
        raise RuntimeError("selected A4-18R fixture campaign was not dispatched")

    fixture_events = [
        context.event_recorder.record(
            SELECTED_CAMPAIGN_ID,
            CampaignEventKind.CHECKPOINTED,
            occurred_at=FIXED_TIME + timedelta(seconds=index),
            payload={
                "fixture": "a4-18r",
                "ordinal": index,
                "production_activation": False,
            },
        )
        for index in range(1, EVIDENCE_COUNT + 1)
    ]

    artifacts = data_root / "physical-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    evidence_ids: list[str] = []
    payload_hashes: list[str] = []
    for index in range(1, EVIDENCE_COUNT + 1):
        evidence_id = f"a4-18r-evidence-{index:03d}"
        payload = {
            "schema": "modelrig-agent4/a4-18r-evidence-fixture/v1",
            "campaign_id": SELECTED_CAMPAIGN_ID,
            "evidence_id": evidence_id,
            "ordinal": index,
            "production_activation": False,
        }
        payload_bytes = canonical_json(payload) + b"\n"
        artifact_path = artifacts / f"{evidence_id}.json"
        artifact_path.write_bytes(payload_bytes)
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        context.evidence_recorder.record(
            SELECTED_CAMPAIGN_ID,
            CampaignEvidenceReference(
                evidence_id=evidence_id,
                media_type="application/json",
                location=f"physical-artifacts/{evidence_id}.json",
                sha256=payload_hash,
                size_bytes=len(payload_bytes),
                metadata={
                    "fixture": "a4-18r",
                    "ordinal": index,
                    "production_activation": False,
                },
            ),
            recorded_at=FIXED_TIME + timedelta(seconds=index),
            related_event_id=fixture_events[index - 1].event_id,
        )
        evidence_ids.append(evidence_id)
        payload_hashes.append(payload_hash)

    for index in range(1, CAMPAIGN_COUNT):
        context.scheduler.submit(
            CampaignSpec(
                campaign_id=f"a4-18r-physical-{index:03d}",
                name=f"A4-18R fysisk listekampagne {index:03d}",
                workflow="agent3.read.fixture",
                created_at=FIXED_TIME - timedelta(minutes=index),
            )
        )

    campaign_page = context.operator.campaign_page(limit=1_000)
    timeline_page = context.operator.timeline_page(SELECTED_CAMPAIGN_ID, limit=1_000)
    evidence_page = context.evidence_operator.evidence_page(SELECTED_CAMPAIGN_ID, limit=1_000)
    verification = context.evidence_operator.verification(SELECTED_CAMPAIGN_ID)
    if len(campaign_page.campaigns) != CAMPAIGN_COUNT:
        raise RuntimeError("campaign fixture count is incomplete")
    if len(timeline_page.entries) <= 25:
        raise RuntimeError("timeline fixture does not cross the Android page boundary")
    if len(evidence_page.records) != EVIDENCE_COUNT:
        raise RuntimeError("evidence fixture count is incomplete")
    if verification.record_count != EVIDENCE_COUNT:
        raise RuntimeError("evidence verification count is incomplete")

    persisted_files = sorted(path for path in data_root.rglob("*") if path.is_file())
    file_receipts = [
        {
            "path": path.relative_to(data_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": f"sha256:{sha256_file(path)}",
        }
        for path in persisted_files
    ]
    manifest: dict[str, object] = {
        "schema": SCHEMA,
        "repository_sha": expected_sha,
        "created_at": FIXED_TIME.isoformat().replace("+00:00", "Z"),
        "selected_campaign_id": selected.spec.campaign_id,
        "campaign_count": len(campaign_page.campaigns),
        "timeline_count": len(timeline_page.entries),
        "evidence_count": len(evidence_page.records),
        "evidence_verification_count": verification.record_count,
        "latest_timeline_hash": (
            f"sha256:{verification.latest_timeline_head_hash}"
            if verification.latest_timeline_head_hash is not None
            else None
        ),
        "evidence_head_hash": (
            f"sha256:{verification.head_hash}" if verification.head_hash is not None else None
        ),
        "first_evidence_id": evidence_ids[0],
        "last_evidence_id": evidence_ids[-1],
        "first_payload_sha256": f"sha256:{payload_hashes[0]}",
        "last_payload_sha256": f"sha256:{payload_hashes[-1]}",
        "persisted_files": file_receipts,
        "external_dispatch": False,
        "background_runtime": False,
        "public_network": False,
        "production_activation": False,
    }
    encoded = json.dumps(manifest, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(encoded, encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    result = build_fixture(
        args.output_root,
        args.data_root,
        args.manifest,
        expected_sha=args.expected_sha,
        replace=args.replace,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
