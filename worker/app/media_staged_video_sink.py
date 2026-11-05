"""Staged, job-keyed video publication on the external media volume (#2296; seam 6494148463,
job key 6633945476; interface and ownership 6667142387). Default-off: nothing constructs it yet,
and the executor entry point still refuses video profiles (exit 78) until G1 (the production
VerifiedMediaVolume), #2339 and a physical rig test are in.

The generator writes into a handle; it never sees a path or a descriptor:

    with sink.staged(".mp4") as output:                        # exclusive temp file on the volume
        mime = adapter.render_to(request, output)
        asset_id = sink.adopt_for_job(output, mime, job_key)   # promote + register, or nothing

This class composes ChatGPT's storage code without changing it: ExternalMediaSink._root() for
the volume/root check, ExternalMediaSink.job_asset_id() for the same deterministic id images
get, and media_gallery_index_writer.register_asset() for the gallery index.

Rules (tests/worker_media_staged_video_sink.py, plus the seam's conformance suite):
- staged(".mp4") verifies the root, then creates ".kaliv-<16 hex>.tmp" in the media root with
  O_EXCL | O_NOFOLLOW, mode 0600 -- the naming ExternalMediaSink.publish() uses for its own
  temporaries, so its read-only temp inventories already list a crash leftover.
- The handle offers write() and flush() only. Bytes beyond max_bytes are not written (adoption
  then refuses), so a runaway render cannot fill the volume through this handle.
- adopt_for_job()/adopt(): one attempt per live handle of this sink, "video/mp4" only,
  12 <= size <= max_bytes with "ftyp" at bytes 4..8; fsync; the root is re-verified; the staged
  name must still be the file this sink created (dev/ino) at the written size. Then:
    * a sibling ".png" under the same job id is a conflict;
    * an existing destination with identical bytes is an idempotent retry (same id);
      different bytes, or anything that is not a regular file, is a conflict;
    * otherwise os.link() -- atomic, never overwrites -- and the new name must be our file;
    * register_asset(); if it fails, the link THIS call created is removed (identity-checked)
      and nothing is reported as published.
  On success the descriptor is closed at once (the published file shares its inode) and the
  staged name is removed.
- Leaving the context always removes the staged name if it is still this sink's file; with the
  volume no longer verified it touches nothing.
- No logging at all: no prompt, path or job key ever leaves this module except in exceptions
  with fixed codes.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import secrets
import stat
from pathlib import Path

from .media_gallery_catalog import GalleryUnavailable, _index
from .media_gallery_index_writer import register_asset
from .media_gallery_store import ExternalMediaSink
from .media_generation_contract import ArtifactSinkUnavailable, MAX_ARTIFACT_BYTES

MIME_TYPE = "video/mp4"
EXTENSION = ".mp4"
_MIN_BYTES = 12  # an ISO-BMFF box header plus "ftyp"
_CHUNK = 1024 * 1024


class _Ticket:
    __slots__ = ("path", "fd", "dev", "ino", "written", "head", "attempted", "adopted")

    def __init__(self, path: Path, fd: int, dev: int, ino: int):
        self.path, self.fd, self.dev, self.ino = path, fd, dev, ino
        self.written, self.head = 0, b""
        self.attempted = self.adopted = False


class _StagedVideoWriter:
    """Write-only handle: no name, no fileno, so the generator never learns the path."""

    __slots__ = ("_sink", "_ticket")

    def __init__(self, sink: "ExternalStagedVideoSink", ticket: _Ticket):
        self._sink, self._ticket = sink, ticket

    def write(self, data) -> int:
        ticket = self._ticket
        if ticket.fd is None or ticket.attempted:
            raise ValueError("staged video handle is closed")
        view = memoryview(data).cast("B")
        size = len(view)
        room = self._sink.max_bytes + 1 - ticket.written  # one byte over is enough to refuse later
        if len(ticket.head) < _MIN_BYTES:
            ticket.head += bytes(view[:_MIN_BYTES - len(ticket.head)])
        chunk = view[:max(0, room)]
        while chunk:
            chunk = chunk[os.write(ticket.fd, chunk):]
        ticket.written += size
        return size

    def flush(self) -> None:
        return None  # os.write is unbuffered; adoption fsyncs


class ExternalStagedVideoSink:
    """StagedFileArtifactSink + JobKeyedStagedSink on the verified external media volume."""

    def __init__(self, media_root: str | Path, verified_volume_root: str | Path, *,
                 max_bytes: int = MAX_ARTIFACT_BYTES):
        if type(max_bytes) is not int or not _MIN_BYTES <= max_bytes <= MAX_ARTIFACT_BYTES:
            raise ValueError("invalid_max_bytes")
        self._media = ExternalMediaSink(media_root, verified_volume_root)
        self.max_bytes = max_bytes
        self._live: dict[int, _Ticket] = {}

    # --- staging ----------------------------------------------------------------------------
    @contextlib.contextmanager
    def staged(self, extension: str):
        if extension != EXTENSION:
            raise ValueError("only .mp4 is staged")
        root = self._media._root()  # ArtifactSinkUnavailable: nothing is created
        path = root / f".kaliv-{secrets.token_hex(8)}.tmp"
        flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0))
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as exc:
            raise ArtifactSinkUnavailable("staged_video_create_failed") from exc
        try:
            created = os.fstat(fd)
            named = os.lstat(path)
            if not stat.S_ISREG(named.st_mode) or (named.st_dev, named.st_ino) != (created.st_dev, created.st_ino):
                raise ArtifactSinkUnavailable("staged_video_replaced")
        except BaseException:
            os.close(fd)
            raise  # the name is not provably ours: leave it
        ticket = _Ticket(path, fd, created.st_dev, created.st_ino)
        writer = _StagedVideoWriter(self, ticket)
        self._live[id(writer)] = ticket
        try:
            yield writer
        finally:
            self._live.pop(id(writer), None)
            ticket.attempted = True  # no adoption after the context
            self._close(ticket)
            self._remove_if_ours(ticket.path, ticket.dev, ticket.ino)

    # --- adoption ---------------------------------------------------------------------------
    def adopt_for_job(self, handle, mime_type: str, job_key: str) -> str:
        ticket = self._claim(handle, mime_type)
        asset_id = self._media.job_asset_id(job_key)  # ValueError on a malformed key
        return self._adopt(ticket, asset_id)

    def adopt(self, handle, mime_type: str) -> str:
        ticket = self._claim(handle, mime_type)
        return self._adopt(ticket, secrets.token_hex(16))

    def _claim(self, handle, mime_type: str) -> _Ticket:
        ticket = self._live.get(id(handle)) if isinstance(handle, _StagedVideoWriter) else None
        if ticket is None or handle._ticket is not ticket or ticket.attempted or ticket.fd is None:
            raise ValueError("not a live staged handle of this sink")
        ticket.attempted = True  # one adoption attempt per handle, successful or not
        if mime_type != MIME_TYPE:
            raise ValueError("only video/mp4 is adopted")
        if not _MIN_BYTES <= ticket.written <= self.max_bytes:
            raise ValueError("staged video size out of bounds")
        if ticket.head[4:8] != b"ftyp":
            raise ValueError("staged video is not an MP4")
        return ticket

    def _adopt(self, ticket: _Ticket, asset_id: str) -> str:
        try:
            os.fsync(ticket.fd)
            root = self._media._root()
            named = os.lstat(ticket.path)
            on_disk = os.fstat(ticket.fd)
        except ArtifactSinkUnavailable:
            raise
        except OSError as exc:
            raise ArtifactSinkUnavailable("staged_video_unavailable") from exc
        if (not stat.S_ISREG(named.st_mode) or (named.st_dev, named.st_ino) != (ticket.dev, ticket.ino)
                or named.st_size != ticket.written or on_disk.st_size != ticket.written):
            raise ArtifactSinkUnavailable("staged_video_changed")
        destination = root / (asset_id + EXTENSION)
        sibling = root / (asset_id + ".png")
        if sibling.exists() or sibling.is_symlink():
            raise ArtifactSinkUnavailable("asset_job_conflict")
        created = False
        if destination.exists() or destination.is_symlink():
            if not self._same_content(destination, ticket):
                raise ArtifactSinkUnavailable("asset_job_conflict")
        else:
            try:
                self._media._root()  # right before the link
                os.link(ticket.path, destination, follow_symlinks=False)
                created = True
            except FileExistsError:
                if not self._same_content(destination, ticket):
                    raise ArtifactSinkUnavailable("asset_job_conflict") from None
            except OSError as exc:
                raise ArtifactSinkUnavailable("external_media_write_failed") from exc
            if created:
                try:
                    linked = os.lstat(destination)
                except OSError as exc:
                    raise ArtifactSinkUnavailable("external_media_write_failed") from exc
                if (linked.st_dev, linked.st_ino) != (ticket.dev, ticket.ino):
                    raise ArtifactSinkUnavailable("asset_job_conflict")  # not ours: never touched
                self._sync_directory(root)
        try:
            register_asset(self._media.media_root, self._media.volume_root, asset_id, EXTENSION, ticket.written)
        except (GalleryUnavailable, OSError, ValueError) as exc:
            # Close first: on Windows an open descriptor without delete sharing blocks the
            # removal of every name of that file, the new link included (#2347 review 4485110252).
            self._close(ticket)
            # The writer can fail AFTER it committed the index (e.g. removing its lock), so the
            # exception alone does not say whether the row exists (#2347 review 4485170944).
            state = self._index_state(asset_id, ticket.written)
            if state is True:  # durably registered: the asset is published, keep and report it
                ticket.adopted = True
                self._remove_if_ours(ticket.path, ticket.dev, ticket.ino)
                return asset_id
            if state is None:  # unknowable: never delete what may be indexed; reconcile instead
                raise ArtifactSinkUnavailable("gallery_registration_unknown_asset_kept") from exc
            if created and not self._remove_if_ours(destination, ticket.dev, ticket.ino):
                # The rollback did not happen: an unindexed asset is left for the read-only
                # inventory (ExternalMediaSink.inspect_unindexed_assets) -- say so, never succeed.
                raise ArtifactSinkUnavailable("gallery_registration_failed_asset_left_unindexed") from exc
            raise ArtifactSinkUnavailable("gallery_registration_failed") from exc
        ticket.adopted = True
        self._close(ticket)  # the published file shares this inode: no write may follow
        self._remove_if_ours(ticket.path, ticket.dev, ticket.ino)
        return asset_id

    # --- helpers ----------------------------------------------------------------------------
    def _index_state(self, asset_id: str, size: int):
        """True if the gallery index holds exactly this video row, False if it holds no row for
        the id, None if that cannot be established (unreadable index, conflicting row, no volume)."""
        try:
            root = self._media._root()
            index = root / "gallery-index.json"
            entries = _index(root) if index.exists() or index.is_symlink() else []
        except (ArtifactSinkUnavailable, GalleryUnavailable, OSError, ValueError):
            return None
        row = next((item for item in entries if item.get("id") == asset_id), None)
        if row is None:
            return False
        if (row.get("kind"), row.get("mime_type"), row.get("size_bytes")) == ("video", MIME_TYPE, size):
            return True
        return None

    def _same_content(self, destination: Path, ticket: _Ticket) -> bool:
        """An idempotent retry: the existing destination is a regular file with our exact bytes."""
        if destination.is_symlink():
            return False
        try:
            fd = os.open(destination, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        except OSError:
            return False
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size != ticket.written:
                return False
            return hmac.compare_digest(self._digest(fd), self._digest(ticket.fd))
        except OSError:
            return False
        finally:
            os.close(fd)

    @staticmethod
    def _digest(fd: int) -> bytes:
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while chunk := os.read(fd, _CHUNK):
            digest.update(chunk)
        return digest.digest()

    @staticmethod
    def _sync_directory(root: Path) -> None:
        """Make the new name durable where the platform allows a directory fsync (not Windows)."""
        if os.name == "nt":
            return
        try:
            fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    @staticmethod
    def _close(ticket: _Ticket) -> None:
        if ticket.fd is not None:
            fd, ticket.fd = ticket.fd, None
            os.close(fd)

    def _remove_if_ours(self, path: Path, dev: int, ino: int) -> bool:
        """Unlink path only if it is still the given file, on the still verified volume.
        True when that file no longer has this name; False when it was left in place."""
        try:
            self._media._root()
        except ArtifactSinkUnavailable:
            return False  # unmounted or replaced: touch nothing on whatever is there now
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (dev, ino):
            return True  # the name is another file now: ours is not there, and theirs is kept
        try:
            os.unlink(path)
        except OSError:
            return False  # left for the read-only inventories; never reported as published
        return True
