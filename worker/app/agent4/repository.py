"""Crash-safe JSON persistence for Agent 4 campaign records."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Mapping

from .domain import CampaignRecord, CampaignValidationError


class CampaignRepositoryError(RuntimeError):
    """Raised when persisted campaign data cannot be read or written safely."""


class JsonCampaignRepository:
    """Filesystem repository with atomic replacement and schema validation."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def save(self, record: CampaignRecord) -> None:
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            destination = self._path_for(record.spec.campaign_id)
            payload = json.dumps(
                record.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="\n",
                    prefix=f".{destination.name}.",
                    suffix=".tmp",
                    dir=self._root,
                    delete=False,
                ) as handle:
                    temporary_path = Path(handle.name)
                    handle.write(payload)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, destination)
                self._fsync_directory()
            except OSError as exc:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise CampaignRepositoryError(
                    f"unable to persist campaign {record.spec.campaign_id!r}"
                ) from exc

    def get(self, campaign_id: str) -> CampaignRecord | None:
        with self._lock:
            path = self._path_for(campaign_id)
            if not path.exists():
                return None
            return self._read(path, expected_campaign_id=campaign_id)

    def list(self) -> tuple[CampaignRecord, ...]:
        with self._lock:
            if not self._root.exists():
                return ()
            records = [
                self._read(path)
                for path in sorted(self._root.glob("*.campaign.json"))
            ]
            return tuple(
                sorted(
                    records,
                    key=lambda record: (
                        record.spec.created_at,
                        record.spec.campaign_id,
                    ),
                )
            )

    def delete(self, campaign_id: str) -> bool:
        with self._lock:
            path = self._path_for(campaign_id)
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise CampaignRepositoryError(
                    f"unable to delete campaign {campaign_id!r}"
                ) from exc
            self._fsync_directory()
            return True

    def _read(
        self,
        path: Path,
        *,
        expected_campaign_id: str | None = None,
    ) -> CampaignRecord:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CampaignRepositoryError(
                f"unable to read campaign record {path.name!r}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} must contain an object"
            )
        try:
            record = CampaignRecord.from_dict(raw)
        except (CampaignValidationError, KeyError, TypeError, ValueError) as exc:
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} failed validation"
            ) from exc
        if (
            expected_campaign_id is not None
            and record.spec.campaign_id != expected_campaign_id
        ):
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} does not match requested id"
            )
        if path.name != self._path_for(record.spec.campaign_id).name:
            raise CampaignRepositoryError(
                f"campaign record {path.name!r} has an invalid filename binding"
            )
        return record

    def _path_for(self, campaign_id: str) -> Path:
        if not isinstance(campaign_id, str) or not campaign_id.strip():
            raise CampaignValidationError("campaign_id must not be empty")
        digest = hashlib.sha256(campaign_id.strip().encode("utf-8")).hexdigest()
        return self._root / f"{digest}.campaign.json"

    def _fsync_directory(self) -> None:
        if os.name == "nt":
            return
        try:
            descriptor = os.open(self._root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
