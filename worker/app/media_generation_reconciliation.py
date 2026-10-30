"""Read-only reconciliation between durable generation jobs and gallery media.

Never changes SQLite state or media files. A candidate receipt is not proof
that inference completed; the caller must decide recovery policy separately.
"""
from __future__ import annotations

from .image_job_store import ImageJobStore
from .media_gallery_store import ExternalMediaSink
from .media_generation_contract import ArtifactSinkUnavailable
from .media_gallery_catalog import GalleryUnavailable, _index


def inspect_generation_consistency(jobs: ImageJobStore, sink: ExternalMediaSink) -> list[dict]:
    """Return deterministic diagnostic findings without modifying either store."""
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
                # Legacy random-ID publication needs its own indexed-file check;
                # deterministic receipt absence cannot establish a missing file.
                entry = indexed.get(recorded) if isinstance(recorded, str) else None
                if entry is None:
                    status = "completed_legacy_not_indexed"
                else:
                    extension = ".mp4" if entry["kind"] == "video" else (".png" if entry["mime_type"] == "image/png" else None)
                    if extension is None:
                        status = "completed_legacy_unsupported_media_type"
                    else:
                        import stat
                        path = root / (recorded + extension)
                        try:
                            info = path.lstat()
                        except FileNotFoundError:
                            status = "completed_legacy_missing_file"
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
            status = "no_job_artifact"
        elif state == "running":
            status = ("running_with_indexed_artifact" if receipt["indexed"]
                      else "running_with_unindexed_artifact")
        else:
            status = ("failed_with_indexed_artifact" if receipt["indexed"]
                      else "failed_with_unindexed_artifact")
        findings.append({"job_id": job_id, "state": state, "status": status,
                         "asset_id": receipt["asset_id"] if receipt else None})
    return findings
