#!/usr/bin/env python3
"""Apply one isolated A4-25f physical mutation and publish a new root.

Every mode operates only inside a marked A4-25f output workspace. Mutations are
harmless synthetic writes through canonical Agent 4 services/stores, followed by
an explicit caller-driven immutable snapshot publication. No API is mounted and
no external handoff or production activation is possible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.composition import compose_agent4_runtime  # noqa: E402
from app.agent4.domain import CampaignEventKind, CampaignSpec  # noqa: E402
from app.agent4.handoff import (  # noqa: E402
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalRequest,
    DispatchOutcomeKind,
)
from app.agent4.timeline import CampaignEvidenceReference  # noqa: E402

MARKER_SCHEMA = "modelrig-agent4/a4-25f-output-root/v1"
RECEIPT_SCHEMA = "modelrig-agent4/a4-25f-physical-mutation/v1"
SELECTED_CAMPAIGN_ID = "a4-25f-physical-primary"
# Created 30 minutes before the baseline root. With the 31-campaign fixture and
# 25-item Android page size this campaign is deterministically on page 2, so the
# add+delete race cannot accidentally exercise only first-page membership.
DELETE_CAMPAIGN_ID = "a4-25f-physical-030"
MODES = (
    "campaign-transition",
    "evidence-append",
    "campaign-add",
    "campaign-delete",
)


class _NoExternalExecutor:
    def dispatch(self, request: CampaignDispatchRequest):
        raise RuntimeError(f"A4-25f mutation forbids dispatch {request.dispatch_id}")

    def signal(self, request: CampaignSignalRequest):
        raise RuntimeError(f"A4-25f mutation forbids signal {request.signal_id}")

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


def _workspace(output_root: Path) -> tuple[Path, Path]:
    resolved = output_root.expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("A4-25f output must stay outside the repository")
    marker = resolved / ".modelrig-a4-25f-output.json"
    if not marker.is_file():
        raise RuntimeError("A4-25f output marker is missing")
    raw = json.loads(marker.read_text(encoding="utf-8"))
    if raw.get("schema") != MARKER_SCHEMA or raw.get("production_activation") is not False:
        raise RuntimeError("A4-25f output marker is invalid")
    data_root = resolved / "fixture-data"
    manifest = resolved / "fixture-manifest.json"
    if not data_root.is_dir() or not manifest.is_file():
        raise RuntimeError("A4-25f baseline fixture is incomplete")
    return data_root, resolved / "mutations"


def _snapshot_summary(context, root, campaign_id: str) -> dict[str, object] | None:
    snapshot_id = root.campaigns.get(campaign_id)
    if snapshot_id is None:
        return None
    snapshot = context.snapshot_store.load_campaign(snapshot_id)
    return {
        "campaign_snapshot_id": snapshot_id,
        "state_revision": snapshot.state_revision,
        "timeline_sequence": snapshot.timeline_head_sequence,
        "timeline_head": (
            f"sha256:{snapshot.timeline_head_sha256}"
            if snapshot.timeline_head_sha256 is not None
            else None
        ),
        "evidence_sequence": snapshot.evidence_head_sequence,
        "evidence_head": (
            f"sha256:{snapshot.evidence_head_sha256}"
            if snapshot.evidence_head_sha256 is not None
            else None
        ),
        "latest_evidence_timeline_head": (
            f"sha256:{snapshot.latest_evidence_timeline_head_sha256}"
            if snapshot.latest_evidence_timeline_head_sha256 is not None
            else None
        ),
    }


def mutate(
    output_root: Path,
    *,
    expected_sha: str,
    mode: str,
) -> dict[str, object]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    repository_sha = _require_exact_head(expected_sha)
    data_root, mutations_root = _workspace(output_root)
    mutations_root.mkdir(parents=True, exist_ok=True)

    context = compose_agent4_runtime(
        data_root,
        executor=_NoExternalExecutor(),
        resource_capacities={"physical-fixture": 1},
        resource_resolver=lambda _spec: {"physical-fixture": 1},
        resource_lease_ttl=timedelta(minutes=30),
    )
    before = context.snapshot_store.load_current()
    if before is None:
        raise RuntimeError("A4-25f baseline immutable root is missing")
    if context.repository.pending_projections():
        raise RuntimeError("A4-25f mutation started with pending projections")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    selected_before = _snapshot_summary(context, before, SELECTED_CAMPAIGN_ID)
    campaign_count_before = len(before.campaigns)
    mutation_id: str

    if mode == "campaign-transition":
        record = context.scheduler.get(SELECTED_CAMPAIGN_ID)
        if record is None:
            raise RuntimeError("selected A4-25f campaign is missing")
        mutation_id = f"cancel-revision-{record.state.revision + 1}"
        updated = context.scheduler.request_cancel(SELECTED_CAMPAIGN_ID)
        if updated.state.revision != record.state.revision + 1:
            raise RuntimeError("canonical campaign transition did not advance revision")
    elif mode == "evidence-append":
        verification = context.evidence_operator.verification(SELECTED_CAMPAIGN_ID)
        ordinal = verification.record_count + 1
        mutation_id = f"a4-25f-evidence-mutation-{ordinal:03d}"
        payload = {
            "schema": "modelrig-agent4/a4-25f-evidence-mutation/v1",
            "campaign_id": SELECTED_CAMPAIGN_ID,
            "evidence_id": mutation_id,
            "ordinal": ordinal,
            "production_activation": False,
        }
        payload_bytes = _canonical_json(payload) + b"\n"
        artifacts = data_root / "physical-artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        artifact = artifacts / f"{mutation_id}.json"
        if artifact.exists():
            raise RuntimeError("evidence mutation artifact already exists")
        artifact.write_bytes(payload_bytes)
        event = context.event_recorder.record(
            SELECTED_CAMPAIGN_ID,
            CampaignEventKind.CHECKPOINTED,
            occurred_at=now,
            payload={
                "fixture": "a4-25f-evidence-mutation",
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
                metadata={
                    "fixture": "a4-25f-evidence-mutation",
                    "ordinal": ordinal,
                    "production_activation": False,
                },
            ),
            recorded_at=now,
            related_event_id=event.event_id,
        )
    elif mode == "campaign-add":
        mutation_id = f"a4-25f-added-{before.root_sequence + 1:03d}"
        if context.repository.get(mutation_id) is not None:
            raise RuntimeError("campaign-add mutation id already exists")
        context.scheduler.submit(
            CampaignSpec(
                campaign_id=mutation_id,
                name=f"A4-25f physical added campaign {before.root_sequence + 1:03d}",
                workflow="agent3.read.fixture",
                created_at=now,
            )
        )
    else:
        mutation_id = DELETE_CAMPAIGN_ID
        if not context.repository.delete(DELETE_CAMPAIGN_ID):
            raise RuntimeError("campaign-delete target is already absent")

    if context.repository.pending_projections():
        raise RuntimeError("A4-25f mutation left pending projections")

    after = context.publish_operator_snapshot()
    if after.root_sequence != before.root_sequence + 1:
        raise RuntimeError("A4-25f mutation did not publish exactly one new root")
    if after.parent_snapshot_id != before.snapshot_id:
        raise RuntimeError("A4-25f mutation root does not parent the previous root")
    if after.snapshot_id == before.snapshot_id:
        raise RuntimeError("A4-25f mutation unexpectedly reused the previous root")

    selected_after = _snapshot_summary(context, after, SELECTED_CAMPAIGN_ID)
    campaign_count_after = len(after.campaigns)

    if mode == "campaign-transition":
        if selected_before is None or selected_after is None:
            raise RuntimeError("selected campaign disappeared during transition")
        if selected_after["state_revision"] != selected_before["state_revision"] + 1:
            raise RuntimeError("transition root did not capture the new state revision")
    elif mode == "evidence-append":
        if selected_before is None or selected_after is None:
            raise RuntimeError("selected campaign disappeared during evidence mutation")
        if selected_after["evidence_sequence"] != selected_before["evidence_sequence"] + 1:
            raise RuntimeError("evidence mutation root did not capture one new record")
        if selected_after["timeline_sequence"] != selected_before["timeline_sequence"] + 1:
            raise RuntimeError("evidence mutation root did not capture one new timeline event")
    elif mode == "campaign-add":
        if campaign_count_after != campaign_count_before + 1 or mutation_id not in after.campaigns:
            raise RuntimeError("campaign-add root did not add exactly one campaign")
    else:
        if campaign_count_after != campaign_count_before - 1 or mutation_id in after.campaigns:
            raise RuntimeError("campaign-delete root did not remove exactly one campaign")

    receipt: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "mutated_at": now.isoformat().replace("+00:00", "Z"),
        "repository_sha": repository_sha,
        "mode": mode,
        "mutation_id": mutation_id,
        "root_before": before.snapshot_id,
        "root_after": after.snapshot_id,
        "root_sequence_before": before.root_sequence,
        "root_sequence_after": after.root_sequence,
        "root_after_parent": after.parent_snapshot_id,
        "campaign_count_before": campaign_count_before,
        "campaign_count_after": campaign_count_after,
        "selected_before": selected_before,
        "selected_after": selected_after,
        "pending_projections_after": len(context.repository.pending_projections()),
        "external_dispatch": False,
        "background_runtime": False,
        "api_mounted": False,
        "public_network": False,
        "production_activation": False,
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        _canonical_json(receipt)
    ).hexdigest()
    receipt_path = mutations_root / f"{after.root_sequence:04d}-{mode}.json"
    if receipt_path.exists():
        raise RuntimeError(f"mutation receipt already exists: {receipt_path}")
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--mode", required=True, choices=MODES)
    args = parser.parse_args()
    mutate(args.output_root, expected_sha=args.expected_sha, mode=args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
