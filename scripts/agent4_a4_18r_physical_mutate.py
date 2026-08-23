#!/usr/bin/env python3
"""Apply one explicit A4-18R snapshot mutation while its worker is stopped."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
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

SCHEMA = "modelrig-agent4/a4-18r-physical-mutation/v1"
FIXTURE_SCHEMA = "modelrig-agent4/a4-18r-physical-fixture/v1"
SELECTED_CAMPAIGN_ID = "a4-18r-physical-primary"


class _ReadFixtureExecutor:
    def dispatch(self, request: CampaignDispatchRequest) -> CampaignDispatchAcknowledgement:
        raise RuntimeError(f"A4-18R mutation forbids dispatch {request.dispatch_id}")

    def signal(self, request: CampaignSignalRequest) -> CampaignSignalAcknowledgement:
        raise RuntimeError(f"A4-18R mutation forbids signal {request.signal_id}")

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        return CampaignDispatchOutcome(dispatch_id=dispatch_id, kind=DispatchOutcomeKind.UNKNOWN)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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
        raise ValueError("A4-18R mutation paths must stay inside the output root") from exc
    return resolved


def _self_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def mutate(
    output_root: Path,
    data_root: Path,
    fixture_manifest_path: Path,
    mode: str,
    receipt_path: Path,
    *,
    expected_sha: str,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise ValueError("expected SHA must be 40 lowercase hex")
    output_root = safe_output_root(output_root)
    data_root = inside_output(data_root, output_root)
    fixture_manifest_path = inside_output(fixture_manifest_path, output_root)
    receipt_path = inside_output(receipt_path, output_root)
    if not data_root.is_dir() or data_root.is_symlink():
        raise RuntimeError(f"A4-18R fixture root is missing or unsafe: {data_root}")
    if receipt_path.exists():
        raise RuntimeError(f"mutation receipt already exists: {receipt_path}")
    fixture = json.loads(fixture_manifest_path.read_text(encoding="utf-8"))
    if fixture.get("schema") != FIXTURE_SCHEMA or fixture.get("repository_sha") != expected_sha:
        raise RuntimeError("fixture manifest is not bound to the requested exact SHA")

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

    if mode == "campaign-record":
        mutation_id = f"a4-18r-campaign-mutation-{now.strftime('%Y%m%dT%H%M%SZ')}"
        context.scheduler.submit(
            CampaignSpec(
                campaign_id=mutation_id,
                name="A4-18R stale campaign snapshot mutation",
                workflow="agent3.read.fixture",
                created_at=now + timedelta(seconds=1),
            )
        )
    elif mode == "summary":
        ordinal = before_verification.record_count + 1
        mutation_id = f"a4-18r-summary-mutation-{ordinal:03d}"
        payload = {
            "schema": "modelrig-agent4/a4-18r-summary-mutation/v1",
            "campaign_id": SELECTED_CAMPAIGN_ID,
            "evidence_id": mutation_id,
            "ordinal": ordinal,
            "production_activation": False,
        }
        payload_bytes = canonical_json(payload) + b"\n"
        artifacts = data_root / "physical-artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        artifact = artifacts / f"{mutation_id}.json"
        artifact.write_bytes(payload_bytes)
        summary_event = context.event_recorder.record(
            SELECTED_CAMPAIGN_ID,
            CampaignEventKind.CHECKPOINTED,
            occurred_at=now,
            payload={
                "fixture": "a4-18r-summary-mutation",
                "ordinal": ordinal,
                "production_activation": False,
            },
        )
        context.evidence_recorder.record(
            SELECTED_CAMPAIGN_ID,
            CampaignEvidenceReference(
                evidence_id=mutation_id,
                media_type="application/json",
                location=f"physical-artifacts/{mutation_id}.json",
                sha256=hashlib.sha256(payload_bytes).hexdigest(),
                size_bytes=len(payload_bytes),
                metadata={"fixture": "a4-18r-summary-mutation", "production_activation": False},
            ),
            recorded_at=now,
            related_event_id=summary_event.event_id,
        )
    else:
        raise ValueError("mode must be campaign-record or summary")

    after_campaigns = len(context.scheduler.list())
    after_verification = context.evidence_operator.verification(SELECTED_CAMPAIGN_ID)
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "repository_sha": expected_sha,
        "mutated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "mutation_id": mutation_id,
        "campaign_count_before": before_campaigns,
        "campaign_count_after": after_campaigns,
        "evidence_count_before": before_verification.record_count,
        "evidence_count_after": after_verification.record_count,
        "timeline_head_before": (
            f"sha256:{before_verification.latest_timeline_head_hash}"
            if before_verification.latest_timeline_head_hash is not None else None
        ),
        "timeline_head_after": (
            f"sha256:{after_verification.latest_timeline_head_hash}"
            if after_verification.latest_timeline_head_hash is not None else None
        ),
        "evidence_head_before": (
            f"sha256:{before_verification.head_hash}" if before_verification.head_hash is not None else None
        ),
        "evidence_head_after": (
            f"sha256:{after_verification.head_hash}" if after_verification.head_hash is not None else None
        ),
        "external_dispatch": False,
        "background_runtime": False,
        "public_network": False,
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
        if after_verification.latest_timeline_head_hash == before_verification.latest_timeline_head_hash:
            raise RuntimeError("summary mutation did not change timeline head")

    receipt["receipt_sha256"] = _self_digest(receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--fixture-manifest", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("campaign-record", "summary"))
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    result = mutate(
        args.output_root,
        args.data_root,
        args.fixture_manifest,
        args.mode,
        args.receipt,
        expected_sha=args.expected_sha,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
