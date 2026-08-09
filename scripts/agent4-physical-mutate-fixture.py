#!/usr/bin/env python3
"""Apply one explicit A4-18 snapshot mutation while the worker is stopped.

The script is confined to validation/agent4-physical-runtime. It opens the same
canonical Agent 4 stores in a separate process, performs exactly one harmless
fixture write and emits a content-bound receipt. It never mounts an API, starts
background work, calls Agent 3 or changes production activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
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

SELECTED_CAMPAIGN_ID = "a4-18-physical-primary"


class _ReadFixtureExecutor:
    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        raise RuntimeError(f"physical mutation forbids dispatch {request.dispatch_id}")

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        raise RuntimeError(f"physical mutation forbids signal {request.signal_id}")

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        return CampaignDispatchOutcome(
            dispatch_id=dispatch_id,
            kind=DispatchOutcomeKind.UNKNOWN,
        )


def _validation_root() -> Path:
    return (ROOT / "validation" / "agent4-physical-runtime").resolve()


def _inside_validation(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(_validation_root())
    except ValueError as exc:
        raise ValueError(
            "mutation paths must stay below validation/agent4-physical-runtime"
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


def mutate(data_root: Path, mode: str, receipt_path: Path) -> None:
    data_root = _inside_validation(data_root)
    receipt_path = _inside_validation(receipt_path)
    if not data_root.is_dir():
        raise RuntimeError(f"physical fixture root is missing: {data_root}")
    if receipt_path.exists():
        raise RuntimeError(f"mutation receipt already exists: {receipt_path}")

    context = compose_agent4_runtime(
        data_root,
        executor=_ReadFixtureExecutor(),
        resource_capacities={"fixture-read": 1},
        resource_resolver=lambda _spec: {"fixture-read": 1},
        resource_lease_ttl=timedelta(minutes=30),
    )
    now = datetime.now(timezone.utc).replace(microsecond=0)
    before_campaigns = len(context.scheduler.list())
    before_verification = context.evidence_operator.verification(SELECTED_CAMPAIGN_ID)
    mutation_id: str

    if mode == "campaign-record":
        mutation_id = f"a4-18-campaign-mutation-{now.strftime('%Y%m%dT%H%M%SZ')}"
        context.scheduler.submit(
            CampaignSpec(
                campaign_id=mutation_id,
                name="A4-18 stale campaign snapshot mutation",
                workflow="agent3.read.fixture",
                created_at=now + timedelta(seconds=1),
            )
        )
    elif mode == "summary":
        ordinal = before_verification.record_count + 1
        mutation_id = f"physical-summary-mutation-{ordinal:03d}"
        payload = {
            "schema": "modelrig-agent4/physical-summary-mutation/v1",
            "campaign_id": SELECTED_CAMPAIGN_ID,
            "evidence_id": mutation_id,
            "ordinal": ordinal,
            "production_activation": False,
        }
        payload_bytes = _canonical_json(payload) + b"\n"
        artifacts = data_root / "physical-artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        artifact = artifacts / f"{mutation_id}.json"
        artifact.write_bytes(payload_bytes)
        latest = context.timeline.latest(SELECTED_CAMPAIGN_ID)
        if latest is None:
            raise RuntimeError("selected campaign has no timeline event")
        context.evidence_recorder.record(
            SELECTED_CAMPAIGN_ID,
            CampaignEvidenceReference(
                evidence_id=mutation_id,
                media_type="application/json",
                location=f"physical-artifacts/{mutation_id}.json",
                sha256=hashlib.sha256(payload_bytes).hexdigest(),
                size_bytes=len(payload_bytes),
                metadata={
                    "fixture": "a4-18-summary-mutation",
                    "production_activation": False,
                },
            ),
            recorded_at=now,
            related_event_id=latest.event.event_id,
        )
    else:
        raise ValueError("mode must be campaign-record or summary")

    after_campaigns = len(context.scheduler.list())
    after_verification = context.evidence_operator.verification(SELECTED_CAMPAIGN_ID)
    receipt = {
        "schema": "modelrig-agent4/physical-read-mutation/v1",
        "mutated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "mutation_id": mutation_id,
        "campaign_count_before": before_campaigns,
        "campaign_count_after": after_campaigns,
        "evidence_count_before": before_verification.record_count,
        "evidence_count_after": after_verification.record_count,
        "timeline_head_before": (
            f"sha256:{before_verification.latest_timeline_head_hash}"
            if before_verification.latest_timeline_head_hash is not None
            else None
        ),
        "timeline_head_after": (
            f"sha256:{after_verification.latest_timeline_head_hash}"
            if after_verification.latest_timeline_head_hash is not None
            else None
        ),
        "evidence_head_before": (
            f"sha256:{before_verification.head_hash}"
            if before_verification.head_hash is not None
            else None
        ),
        "evidence_head_after": (
            f"sha256:{after_verification.head_hash}"
            if after_verification.head_hash is not None
            else None
        ),
        "external_dispatch": False,
        "background_runtime": False,
        "production_activation": False,
    }
    if mode == "campaign-record":
        if after_campaigns != before_campaigns + 1:
            raise RuntimeError("campaign mutation did not change exactly one record")
        if after_verification != before_verification:
            raise RuntimeError("campaign mutation unexpectedly changed evidence summary")
    else:
        if after_campaigns != before_campaigns:
            raise RuntimeError("summary mutation unexpectedly changed campaign count")
        if after_verification.record_count != before_verification.record_count + 1:
            raise RuntimeError("summary mutation did not add exactly one evidence record")
        if after_verification.head_hash == before_verification.head_hash:
            raise RuntimeError("summary mutation did not change evidence head")
        if (
            after_verification.latest_timeline_head_hash
            == before_verification.latest_timeline_head_hash
        ):
            raise RuntimeError("summary mutation did not change timeline head")

    encoded_without_digest = _canonical_json(receipt)
    receipt["receipt_sha256"] = (
        "sha256:" + hashlib.sha256(encoded_without_digest).hexdigest()
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(
            receipt,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("campaign-record", "summary"),
    )
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    mutate(args.data_root, args.mode, args.receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
