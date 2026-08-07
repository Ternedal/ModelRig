"""Bounded streaming create-once publication for large immutable files."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Callable

from .durable_publication import DurablePublicationError, sync_directory

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class StreamingPublicationError(DurablePublicationError):
    """A streaming publication failed before its exact contract was proven."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def publish_stream_once(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    maximum: int,
    validate_existing: Callable[[Path], None],
    prepare_temporary: Callable[[Path], None] | None = None,
    sync_parent_on_race: bool = False,
) -> bool:
    """Stream one exact file and commit it by hard link without replacement.

    Return ``True`` only when this call created the final name. A concurrent
    winner is accepted only after ``validate_existing`` proves its exact bytes
    and any caller-specific alias or permission invariants.
    """

    source_path = Path(source)
    final_path = Path(destination)
    if (
        not source_path.is_absolute()
        or source_path.is_symlink()
        or not source_path.is_file()
        or not final_path.is_absolute()
        or not final_path.parent.is_dir()
        or not isinstance(expected_sha256, str)
        or _HEX64.fullmatch(expected_sha256) is None
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or not 1 <= expected_size <= maximum
        or not callable(validate_existing)
        or prepare_temporary is not None
        and not callable(prepare_temporary)
        or not isinstance(sync_parent_on_race, bool)
    ):
        raise StreamingPublicationError("invalid_inputs")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".kaliv-stage-",
        suffix=".tmp",
        dir=final_path.parent,
    )
    temporary = Path(temporary_name)
    published_here = False
    raced = False
    try:
        output = os.fdopen(descriptor, "wb", closefd=True)
        descriptor = -1
        with output, source_path.open("rb") as input_file:
            digest = hashlib.sha256()
            copied = 0
            while chunk := input_file.read(1024 * 1024):
                copied += len(chunk)
                if copied > maximum:
                    raise StreamingPublicationError("source_exceeds_budget")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        if copied != expected_size or digest.hexdigest() != expected_sha256:
            raise StreamingPublicationError("source_changed")
        if prepare_temporary is not None:
            prepare_temporary(temporary)

        try:
            os.link(temporary, final_path)
            published_here = True
        except FileExistsError:
            validate_existing(final_path)
            raced = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

    if published_here or raced and sync_parent_on_race:
        try:
            sync_directory(final_path.parent)
        except DurablePublicationError as exc:
            raise StreamingPublicationError("directory_sync_failed") from exc
    return published_here
