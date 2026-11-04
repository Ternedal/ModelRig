"""Read-only reconciliation between durable generation jobs and gallery media.

Never changes SQLite state or media files. A candidate receipt is not proof
that inference completed; the caller must decide recovery policy separately.
"""
from __future__ import annotations

import re

from .image_job_store import ImageJobStore
from .media_gallery_store import ExternalMediaSink
from .media_generation_contract import ArtifactSinkUnavailable
from .media_gallery_catalog import GalleryUnavailable, _index


def inspect_generation_consistency(jobs: ImageJobStore, sink: ExternalMediaSink, *, limit: int = 100, offset: int = 0) -> list[dict]:
    """Return a bounded read-only page, ordered by in-flight priority and age.

    ``offset`` permits an operator to inspect older jobs instead of repeatedly
    seeing only the first page. Pages are not a transactional snapshot: a
    concurrent writer may shift rows between calls.
    """
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("invalid_reconciliation_limit")
    if type(offset) is not int or offset < 0 or offset > 1000000:
        raise ValueError("invalid_reconciliation_offset")
    findings = []
    root = sink._root()
    index_path = root / "gallery-index.json"
    try:
        indexed = {entry["id"]: entry for entry in _index(root)} if (index_path.exists() or index_path.is_symlink()) else {}
    except GalleryUnavailable as exc:
        raise ArtifactSinkUnavailable("reconciliation_index_unavailable") from exc
    with jobs._db() as db:
        rows = db.execute(
            "SELECT id, state, asset_id FROM image_jobs "
            "WHERE state IN ('running','publishing','completed','failed') "
            "ORDER BY CASE WHEN state IN ('publishing','running') THEN 0 ELSE 1 END, "
            "created DESC,id DESC LIMIT ? OFFSET ?"
            , (limit, offset)
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
                # Legacy random-ID publication needs its own indexed-file check;
                # deterministic receipt absence cannot establish a missing file.
                entry = indexed.get(recorded) if isinstance(recorded, str) else None
                if receipt is not None:
                    # Two distinct assets for one completed job require operator
                    # review; neither receipt alone proves which output won.
                    status = "completed_legacy_and_job_artifact_conflict"
                elif not isinstance(recorded, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", recorded):
                    status = "completed_legacy_invalid_asset_id"
                elif entry is None:
                    status = "completed_legacy_not_indexed"
                else:
                    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4"}.get(entry["mime_type"])
                    if extension is None:
                        status = "completed_legacy_unsupported_media_type"
                    else:
                        import stat
                        path = root / (recorded + extension)
                        try:
                            info = path.lstat()
                        except FileNotFoundError:
                            status = "completed_legacy_missing_file"
                        except OSError:
                            # Permission errors, I/O faults and other failures
                            # are not evidence that the legacy asset is valid.
                            status = "completed_legacy_file_conflict"
                        else:
                            status = ("completed_legacy_indexed" if stat.S_ISREG(info.st_mode) and info.st_size == entry["size_bytes"]
                                      else "completed_legacy_file_conflict")
            elif receipt is None:
                status = "completed_without_job_artifact"
            elif recorded != receipt["asset_id"]:
                status = "completed_asset_mismatch"
            elif not receipt["indexed"]:
                status = "completed_not_indexed"
            else:
                status = "consistent"
        elif receipt is None:
            if state == "publishing" and recorded is not None:
                # A recorded asset reference with no deterministic receipt
                # cannot be called an ordinary pre-publication state.
                status = "publishing_recorded_asset_without_job_artifact"
            else:
                status = ("publishing_without_job_artifact" if state == "publishing" else "no_job_artifact")
        elif state == "running":
            status = ("running_with_indexed_artifact" if receipt["indexed"]
                      else "running_with_unindexed_artifact")
        elif state == "publishing":
            # The G2 commit point normally leaves asset_id unset until complete().
            # If another writer has recorded a different ID, never treat the
            # deterministic receipt as proof of a safe completion.
            if recorded is not None and recorded != receipt["asset_id"]:
                status = "publishing_asset_mismatch"
            else:
                status = ("publishing_with_indexed_artifact" if receipt["indexed"]
                          else "publishing_with_unindexed_artifact")
        else:
            status = ("failed_with_indexed_artifact" if receipt["indexed"]
                      else "failed_with_unindexed_artifact")
        findings.append({"job_id": job_id, "state": state, "status": status,
                         "asset_id": receipt["asset_id"] if receipt else None})
    return findings
