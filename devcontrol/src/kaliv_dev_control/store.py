"""Atomic, locked compare-and-swap persistence for development campaigns."""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .campaign import DevelopmentCampaign

_CAMPAIGN_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")


class CampaignStoreError(RuntimeError):
    """Campaign persistence failed or detected stale/tampered state."""


class CampaignStore:
    """Persist one canonical JSON object per campaign under a controlled root."""

    def __init__(self, root: Path) -> None:
        self.configured_root = root.absolute()
        self.root = root.resolve()

    def _prepare_root(self) -> None:
        if self.configured_root.is_symlink():
            raise CampaignStoreError("campaign store root must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise CampaignStoreError("campaign store root is not a regular directory")

    def path(self, campaign_id: str) -> Path:
        if not isinstance(campaign_id, str) or _CAMPAIGN_ID.fullmatch(campaign_id) is None:
            raise CampaignStoreError("campaign id cannot be used as a filename")
        target = self.root / f"{campaign_id}.json"
        if target.parent != self.root:
            raise CampaignStoreError("campaign path escaped store root")
        return target

    def _lock_path(self, campaign_id: str) -> Path:
        return self.root / f".{campaign_id}.lock"

    @contextmanager
    def _exclusive_lock(self, campaign_id: str) -> Iterator[None]:
        lock = self._lock_path(campaign_id)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(lock, flags, 0o600)
        except FileExistsError as exc:
            raise CampaignStoreError("campaign is locked by another operation") from exc
        except OSError as exc:
            raise CampaignStoreError("campaign lock could not be acquired") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(f"pid={os.getpid()}\n".encode("ascii"))
                handle.flush()
                os.fsync(handle.fileno())
            yield
        finally:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise CampaignStoreError("campaign lock could not be released") from exc

    def _read(self, path: Path) -> DevelopmentCampaign:
        if path.is_symlink() or not path.is_file():
            raise CampaignStoreError("campaign record is missing or irregular")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CampaignStoreError("campaign record cannot be read") from exc
        if len(raw) > 8_000_000 or b"\x00" in raw:
            raise CampaignStoreError("campaign record is outside bounds")
        try:
            payload = json.loads(raw.decode("utf-8"))
            return DevelopmentCampaign.from_mapping(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise CampaignStoreError("campaign record does not verify") from exc

    def create(self, campaign: DevelopmentCampaign) -> Path:
        campaign.verify()
        self._prepare_root()
        path = self.path(campaign.campaign_id)
        payload = (campaign.canonical_json() + "\n").encode("utf-8")
        with self._exclusive_lock(campaign.campaign_id):
            if path.exists() or path.is_symlink():
                raise CampaignStoreError("campaign already exists")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            try:
                descriptor = os.open(path, flags, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError as exc:
                raise CampaignStoreError("campaign already exists") from exc
            except OSError as exc:
                path.unlink(missing_ok=True)
                raise CampaignStoreError("campaign could not be created") from exc
        return path

    def load(self, campaign_id: str) -> DevelopmentCampaign:
        self._prepare_root()
        return self._read(self.path(campaign_id))

    def save(
        self,
        campaign: DevelopmentCampaign,
        *,
        expected_previous_event_sha256: str,
    ) -> Path:
        """Append one event only if the persisted head matches the caller."""

        campaign.verify()
        self._prepare_root()
        path = self.path(campaign.campaign_id)
        payload = (campaign.canonical_json() + "\n").encode("utf-8")
        with self._exclusive_lock(campaign.campaign_id):
            current = self._read(path)
            current_head = current.events[-1].event_sha256
            if current_head != expected_previous_event_sha256:
                raise CampaignStoreError("campaign compare-and-swap precondition failed")
            if (
                campaign.campaign_id != current.campaign_id
                or campaign.task_id != current.task_id
                or campaign.task_sha256 != current.task_sha256
                or campaign.base_sha != current.base_sha
                or len(campaign.events) != len(current.events) + 1
                or campaign.events[:-1] != current.events
                or campaign.events[-1].previous_event_sha256 != current_head
            ):
                raise CampaignStoreError("campaign update is not one valid append")

            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=self.root,
                    prefix=f".{campaign.campaign_id}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary = Path(handle.name)
                temporary.replace(path)
                temporary = None
            except OSError as exc:
                raise CampaignStoreError("campaign update could not be committed") from exc
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return path
