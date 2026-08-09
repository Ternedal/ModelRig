#!/usr/bin/env python3
"""Build a deterministic, isolated Agent 4 physical-read fixture.

The fixture uses the canonical A4-09 composition and persistence services. It
never mounts an API, starts a background task or calls Agent 3. A local fixture
executor acknowledges one dispatch in-process only so the selected campaign has
real lifecycle/timeline data. Evidence payloads are harmless JSON files under
the validation runtime and their canonical references are recorded through the
normal evidence recorder.
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

SCHEMA = "modelrig-agent4/physical-read-fixture/v1"
SELECTED_CAMPAIGN_ID = "a4-18-physical-primary"
CAMPAIGN_COUNT = 31
EVIDENCE_COUNT = 31


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
        raise RuntimeError(
            f"physical read fixture forbids lifecycle signal {request.signal_id}"
        )

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        return self.outcomes.get(
            dispatch_id,
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.UNKNOWN,
            ),
        )


def _validation_root() -> Path:
    return (ROOT / "validation" / "agent4-physical-runtime").resolve()


def _inside_validation(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(_validation_root())
    except ValueError as exc:
        raise ValueError(
            "fixture paths must stay below validation/agent4-physical-runtime"
        ) from exc
    return resolved


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


def build_fixture(data_root: Path, manifest_path: Path, *, replace: bool) -> None:
    data_root = _inside_validation(data_root)
    manifest_path = _inside_validation(manifest_path)
    runtime_root = _validation_root()
    runtime_root.mkdir(parents=True, exist_ok=True)

    if data_root.exists():
        if not replace:
            raise RuntimeError(
                f"fixture root already exists: {data_root}; use --replace explicitly"
            )
        shutil.rmtree(data_root)
    if manifest_path.exists():
        if not replace:
            raise RuntimeError(
                f"fixture manifest already exists: {manifest_path}; use --replace explicitly"
            )
        manifest_path.unlink()

    base_time = datetime.now(timezone.utc).replace(microsecond=0)
    clock = _Clock(base_time)
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
            name="A4-18 fysisk read-kampagne",
            workflow="agent3.read.fixture",
            created_at=base_time,
        )
    )
    dispatched = context.scheduler.dispatch_ready()
    if dispatched is None or dispatched.spec.campaign_id != SELECTED_CAMPAIGN_ID:
        raise RuntimeError("selected physical fixture campaign was not dispatched")

    artifacts = data_root / "physical-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    latest = context.timeline.latest(SELECTED_CAMPAIGN_ID)
    if latest is None:
        raise RuntimeError("selected fixture campaign has no timeline event")

    evidence_ids: list[str] = []
    payload_hashes: list[str] = []
    for index in range(1, EVIDENCE_COUNT + 1):
        evidence_id = f"physical-evidence-{index:03d}"
        payload = {
            "schema": "modelrig-agent4/physical-evidence-fixture/v1",
            "campaign_id": SELECTED_CAMPAIGN_ID,
            "evidence_id": evidence_id,
            "ordinal": index,
            "production_activation": False,
        }
        payload_bytes = _canonical_json(payload) + b"\n"
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
                    "fixture": "a4-18",
                    "ordinal": index,
                    "production_activation": False,
                },
            ),
            recorded_at=base_time + timedelta(seconds=index),
            related_event_id=(latest.event.event_id if index == 1 else None),
        )
        evidence_ids.append(evidence_id)
        payload_hashes.append(payload_hash)

    for index in range(1, CAMPAIGN_COUNT):
        context.scheduler.submit(
            CampaignSpec(
                campaign_id=f"a4-18-physical-{index:03d}",
                name=f"A4-18 fysisk listekampagne {index:03d}",
                workflow="agent3.read.fixture",
                created_at=base_time - timedelta(minutes=index),
            )
        )

    campaign_page = context.operator.campaign_page(limit=1_000)
    timeline_page = context.operator.timeline_page(
        SELECTED_CAMPAIGN_ID,
        limit=1_000,
    )
    evidence_page = context.evidence_operator.evidence_page(
        SELECTED_CAMPAIGN_ID,
        limit=1_000,
    )
    verification = context.evidence_operator.verification(SELECTED_CAMPAIGN_ID)

    if len(campaign_page.campaigns) != CAMPAIGN_COUNT:
        raise RuntimeError("campaign fixture count is incomplete")
    if len(timeline_page.entries) <= 25:
        raise RuntimeError("timeline fixture does not cross the Android page boundary")
    if len(evidence_page.records) != EVIDENCE_COUNT:
        raise RuntimeError("evidence fixture count is incomplete")
    if verification.record_count != EVIDENCE_COUNT:
        raise RuntimeError("evidence verification count is incomplete")

    persisted_files = sorted(
        path
        for path in data_root.rglob("*")
        if path.is_file()
    )
    file_receipts = [
        {
            "path": path.relative_to(data_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": f"sha256:{_sha256_file(path)}",
        }
        for path in persisted_files
    ]
    manifest = {
        "schema": SCHEMA,
        "created_at": base_time.isoformat().replace("+00:00", "Z"),
        "data_root": str(data_root),
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
            f"sha256:{verification.head_hash}"
            if verification.head_hash is not None
            else None
        ),
        "first_evidence_id": evidence_ids[0],
        "last_evidence_id": evidence_ids[-1],
        "first_payload_sha256": f"sha256:{payload_hashes[0]}",
        "last_payload_sha256": f"sha256:{payload_hashes[-1]}",
        "persisted_files": file_receipts,
        "external_dispatch": False,
        "background_runtime": False,
        "production_activation": False,
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    build_fixture(args.data_root, args.manifest, replace=args.replace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
