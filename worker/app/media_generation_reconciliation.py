"""Read-only reconciliation between durable generation jobs and gallery media.

Never changes SQLite state or media files. A candidate receipt is not proof
that inference completed; the caller must decide recovery policy separately.
"""
from __future__ import annotations

from .image_job_store import ImageJobStore
from .media_gallery_store import ExternalMediaSink
from .media_generation_contract import ArtifactSinkUnavailable


def inspect_generation_consistency(jobs: ImageJobStore, sink: ExternalMediaSink) -> list[dict]:
    """Return deterministic diagnostic findings without modifying either store."""
    findings = []
    with jobs._db() as db:
        rows = db.execute(
            "SELECT id, state, asset_id FROM image_jobs "
            "WHERE state IN ('running','completed','failed') ORDER BY created,id"
        ).fetchall()
    for row in rows:
        job_id, state, recorded = row["id"], row["state"], row["asset_id"]
        # Legacy generic publication uses a random asset ID. Never label
        # those completed jobs as missing solely from a deterministic lookup.
        expected = sink.job_asset_id(job_id)
        try:
            receipt = sink.inspect_job_asset(job_id)
        except ArtifactSinkUnavailable as exc:
            findings.append({"job_id": job_id, "state": state,
                             "status": "media_conflict", "reason": str(exc)})
            continue
        if state == "completed":
            if recorded != expected:
                status = "completed_non_job_scoped_asset"
            elif receipt is None:
                status = "completed_without_job_artifact"
            elif recorded != receipt["asset_id"]:
                status = "completed_asset_mismatch"
            elif not receipt["indexed"]:
                status = "completed_not_indexed"
            else:
                status = "consistent"
        elif receipt is None:
            status = "no_job_artifact"
        elif receipt["indexed"]:
            status = "interrupted_with_indexed_artifact"
        else:
            status = "interrupted_with_unindexed_artifact"
        findings.append({"job_id": job_id, "state": state, "status": status,
                         "asset_id": receipt["asset_id"] if receipt else None})
    return findings
