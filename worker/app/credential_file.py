"""Read a small credential file only if nobody else can read it (step 3 of the ACL design).

docs/T038_WINDOWS_TOKEN_ACL_DESIGN.md, KalivNexus #1. The three bearer loaders
(Home Assistant, RigGate, GitHub connector) share this helper, so one rule
applies to all of them.

- **POSIX:** behaviour is unchanged: a regular file (symlinks are followed, as
  before), a bounded size, and no group/other permission bits. The checks now
  run on the opened descriptor (``fstat``), not on the name, so the file that is
  judged is the file that is read. A name check first refuses a device or FIFO
  without opening it; if one is swapped in afterwards, ``O_NONBLOCK`` keeps the
  open from blocking and ``fstat`` refuses it as not regular.
- **Windows:** ``credential_acl_windows.read_private_credential_windows`` opens
  one handle, judges its attributes and DACL, and reads the bytes from that same
  handle. A symlink or junction is refused, not followed.
- **Anything else:** refused. There is no way to tell who can read the file.

Every refusal is a ``CredentialFileRefused`` with a ``kind``; the loaders turn
the kind into their own existing error message. Refusal is already safe: each
caller reports the provider as ``unknown`` / unavailable.
"""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

KINDS = frozenset({"unavailable", "not_regular", "size", "permissions", "unverifiable", "read"})
_READ_CHUNK = 4_096


class CredentialFileRefused(Exception):
    """The credential file was not read. ``kind`` says why; it never carries the secret."""

    def __init__(self, kind: str, detail: str = "") -> None:
        if kind not in KINDS:
            raise ValueError(f"unknown refusal kind {kind!r}")
        super().__init__(kind if not detail else f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def _read_posix(path: Path, max_bytes: int) -> bytes:
    # Cheap pre-check so a device or FIFO named by mistake is never even opened
    # (the old loaders never opened one either). fstat below stays authoritative.
    try:
        named = os.stat(path)
    except OSError as exc:
        raise CredentialFileRefused("unavailable") from exc
    if not stat.S_ISREG(named.st_mode):
        raise CredentialFileRefused("not_regular")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except PermissionError as exc:
        raise CredentialFileRefused("read") from exc
    except OSError as exc:
        raise CredentialFileRefused("unavailable") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise CredentialFileRefused("not_regular")
        if info.st_size < 1 or info.st_size > max_bytes:
            raise CredentialFileRefused("size")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise CredentialFileRefused("permissions")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            try:
                chunk = os.read(fd, min(_READ_CHUNK, max_bytes + 1 - total))
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise CredentialFileRefused("read") from exc
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    if not 1 <= len(raw) <= max_bytes:
        # The file grew or shrank between fstat and the read.
        raise CredentialFileRefused("size")
    return raw


def _reader_for(os_name: str):
    if os_name == "posix":
        return _read_posix
    if os_name == "nt":
        from .credential_acl_windows import read_private_credential_windows

        return read_private_credential_windows
    return None


def read_private_credential(path: str | os.PathLike[str], *, max_bytes: int) -> bytes:
    """Return the file's bytes, or raise ``CredentialFileRefused``.

    ``max_bytes`` bounds both the size on disk and the bytes actually read.
    """
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 1024 * 1024:
        raise ValueError("max_bytes must be an int between 1 and 1 MiB")
    reader = _reader_for(os.name)
    if reader is None:
        raise CredentialFileRefused("unverifiable", f"no permission check for os.name={os.name}")
    return reader(Path(path), max_bytes)
