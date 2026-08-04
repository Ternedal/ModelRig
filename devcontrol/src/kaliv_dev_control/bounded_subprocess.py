"""Streaming bounded subprocess execution with process-tree termination.

This module is intentionally transport-agnostic.  It starts one no-shell child,
drains stdout and stderr concurrently, hashes and counts every byte while the
child is running, retains only bounded per-stream prefixes, and terminates the
entire process tree immediately on timeout or combined-output budget breach.
"""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping, Sequence

_CHUNK_BYTES = 64 * 1024
_MAX_TIMEOUT_SECONDS = 3600
_MAX_OUTPUT_BYTES = 256 * 1024 * 1024


class BoundedSubprocessError(RuntimeError):
    """The bounded subprocess could not be started, drained or terminated."""


@dataclass(frozen=True, slots=True)
class BoundedStreamEvidence:
    prefix: bytes
    total_bytes: int
    sha256: str
    truncated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.prefix, bytes):
            raise BoundedSubprocessError("stream prefix must be bytes")
        if (
            isinstance(self.total_bytes, bool)
            or not isinstance(self.total_bytes, int)
            or self.total_bytes < len(self.prefix)
        ):
            raise BoundedSubprocessError("stream byte count is invalid")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.sha256)
        ):
            raise BoundedSubprocessError("stream hash is invalid")
        if self.truncated is not (self.total_bytes > len(self.prefix)):
            raise BoundedSubprocessError("stream truncation flag is inconsistent")


@dataclass(frozen=True, slots=True)
class BoundedSubprocessResult:
    args: tuple[str, ...]
    returncode: int
    stdout: BoundedStreamEvidence
    stderr: BoundedStreamEvidence
    total_output_bytes: int
    output_limit_exceeded: bool
    timed_out: bool
    process_tree_terminated: bool

    def __post_init__(self) -> None:
        if not self.args or any(
            not isinstance(item, str) or not item for item in self.args
        ):
            raise BoundedSubprocessError("result arguments are invalid")
        if isinstance(self.returncode, bool) or not isinstance(self.returncode, int):
            raise BoundedSubprocessError("result return code is invalid")
        if self.total_output_bytes != (
            self.stdout.total_bytes + self.stderr.total_bytes
        ):
            raise BoundedSubprocessError(
                "combined output byte count is inconsistent"
            )
        if not isinstance(self.output_limit_exceeded, bool):
            raise BoundedSubprocessError("output-limit flag is invalid")
        if not isinstance(self.timed_out, bool):
            raise BoundedSubprocessError("timeout flag is invalid")
        if not isinstance(self.process_tree_terminated, bool):
            raise BoundedSubprocessError("process-tree flag is invalid")
        if (
            self.output_limit_exceeded or self.timed_out
        ) and not self.process_tree_terminated:
            raise BoundedSubprocessError(
                "bounded failure must prove process-tree termination"
            )


class _StreamAccumulator:
    def __init__(self, prefix_limit: int) -> None:
        self.prefix_limit = prefix_limit
        self.prefix = bytearray()
        self.total_bytes = 0
        self.digest = hashlib.sha256()

    def add(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        self.digest.update(chunk)
        remaining = self.prefix_limit - len(self.prefix)
        if remaining > 0:
            self.prefix.extend(chunk[:remaining])

    def evidence(self) -> BoundedStreamEvidence:
        prefix = bytes(self.prefix)
        return BoundedStreamEvidence(
            prefix=prefix,
            total_bytes=self.total_bytes,
            sha256=self.digest.hexdigest(),
            truncated=self.total_bytes > len(prefix),
        )


def _validate(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    max_output_bytes: int,
    stdout_prefix_bytes: int,
    stderr_prefix_bytes: int,
) -> tuple[tuple[str, ...], Path, dict[str, str]]:
    args = tuple(command)
    if (
        not args
        or any(
            not isinstance(item, str) or not item or "\x00" in item
            for item in args
        )
    ):
        raise BoundedSubprocessError("command arguments are invalid")
    root = Path(cwd)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise BoundedSubprocessError(
            "subprocess cwd must be an absolute directory"
        )
    if (
        isinstance(timeout_seconds, bool)
        or not 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
    ):
        raise BoundedSubprocessError("subprocess timeout is invalid")
    if (
        isinstance(max_output_bytes, bool)
        or not 1 <= max_output_bytes <= _MAX_OUTPUT_BYTES
    ):
        raise BoundedSubprocessError("subprocess output budget is invalid")
    for value, name in (
        (stdout_prefix_bytes, "stdout prefix"),
        (stderr_prefix_bytes, "stderr prefix"),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= max_output_bytes
        ):
            raise BoundedSubprocessError(f"{name} bound is invalid")
    if not isinstance(env, Mapping):
        raise BoundedSubprocessError("subprocess environment is invalid")
    clean_env: dict[str, str] = {}
    for name, value in env.items():
        if (
            not isinstance(name, str)
            or not name
            or "=" in name
            or "\x00" in name
            or not isinstance(value, str)
            or "\x00" in value
        ):
            raise BoundedSubprocessError(
                "subprocess environment field is invalid"
            )
        clean_env[name] = value
    return args, root, clean_env


def _spawn(
    args: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    stdin: int,
) -> subprocess.Popen[bytes]:
    common = {
        "cwd": cwd,
        "stdin": stdin,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
        "shell": False,
        "text": False,
        "bufsize": 0,
    }
    if os.name == "nt":
        try:
            from app.windows_job import JobLimits, spawn_in_job
        except (ImportError, AttributeError) as exc:
            raise BoundedSubprocessError(
                "Windows process-tree Job Object boundary is unavailable"
            ) from exc

        def factory(
            command: list[str], **kwargs: object
        ) -> subprocess.Popen[bytes]:
            return subprocess.Popen(command, cwd=cwd, **kwargs)

        try:
            return spawn_in_job(
                list(args),
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                limits=JobLimits(
                    process_memory_bytes=512 * 1024 * 1024,
                    active_process_limit=16,
                    ui_restrictions=0,
                ),
                popen_factory=factory,
            )
        except Exception as exc:
            raise BoundedSubprocessError(
                "Windows process tree could not be started in a Job Object"
            ) from exc
    try:
        return subprocess.Popen(
            list(args),
            **common,
            start_new_session=True,
        )
    except OSError as exc:
        raise BoundedSubprocessError(
            "subprocess could not be started"
        ) from exc


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    # The process-group or Job Object can still contain descendants after the
    # original child exits. Never use leader exit as proof that the tree is gone.
    if os.name == "nt":
        try:
            from app.windows_job import terminate_attached_job
        except (ImportError, AttributeError) as exc:
            raise BoundedSubprocessError(
                "Windows process-tree termination boundary is unavailable"
            ) from exc
        try:
            if not terminate_attached_job(process, exit_code=1):
                raise BoundedSubprocessError(
                    "Windows process was not attached to a Job Object"
                )
        except Exception as exc:
            if isinstance(exc, BoundedSubprocessError):
                raise
            raise BoundedSubprocessError(
                "Windows Job Object termination failed"
            ) from exc
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise BoundedSubprocessError(
            "POSIX process-group termination failed"
        ) from exc


def _close_tree_boundary(process: subprocess.Popen[bytes]) -> None:
    if os.name != "nt":
        return
    try:
        from app.windows_job import close_attached_job
    except (ImportError, AttributeError) as exc:
        raise BoundedSubprocessError(
            "Windows process-tree close boundary is unavailable"
        ) from exc
    try:
        close_attached_job(process)
    except Exception as exc:
        raise BoundedSubprocessError(
            "Windows Job Object close failed"
        ) from exc


def _drain(
    stream: BinaryIO,
    accumulator: _StreamAccumulator,
    *,
    condition: threading.Condition,
    state: dict[str, object],
) -> None:
    try:
        while True:
            chunk = stream.read(_CHUNK_BYTES)
            if not chunk:
                return
            with condition:
                accumulator.add(chunk)
                state["total"] = int(state["total"]) + len(chunk)
                if int(state["total"]) > int(state["limit"]):
                    state["limit_exceeded"] = True
                    condition.notify_all()
                    return
                condition.notify_all()
    except BaseException as exc:
        with condition:
            if state["reader_error"] is None:
                state["reader_error"] = exc
            condition.notify_all()
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _write_stdin(
    stream: BinaryIO,
    payload: bytes,
    *,
    condition: threading.Condition,
    state: dict[str, object],
) -> None:
    try:
        stream.write(payload)
        stream.flush()
    except (BrokenPipeError, OSError):
        # A child may deliberately close stdin after consuming only the portion it
        # needs. The process return code remains the authoritative outcome.
        pass
    except BaseException as exc:
        with condition:
            if state["writer_error"] is None:
                state["writer_error"] = exc
            condition.notify_all()
    finally:
        try:
            stream.close()
        except OSError:
            pass


def run_bounded_subprocess(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdin_bytes: bytes | None = None,
    timeout_seconds: int,
    max_output_bytes: int,
    stdout_prefix_bytes: int | None = None,
    stderr_prefix_bytes: int | None = None,
) -> BoundedSubprocessResult:
    """Run one child while enforcing a combined stdout/stderr budget in flight."""

    if stdin_bytes is not None and not isinstance(stdin_bytes, bytes):
        raise BoundedSubprocessError(
            "subprocess stdin must be bytes or absent"
        )
    stdout_limit = (
        max_output_bytes
        if stdout_prefix_bytes is None
        else stdout_prefix_bytes
    )
    stderr_limit = (
        max_output_bytes
        if stderr_prefix_bytes is None
        else stderr_prefix_bytes
    )
    args, root, clean_env = _validate(
        command,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        stdout_prefix_bytes=stdout_limit,
        stderr_prefix_bytes=stderr_limit,
    )
    process = _spawn(
        args,
        cwd=root,
        env=clean_env,
        stdin=(
            subprocess.PIPE
            if stdin_bytes is not None
            else subprocess.DEVNULL
        ),
    )
    stdout_accumulator = _StreamAccumulator(stdout_limit)
    stderr_accumulator = _StreamAccumulator(stderr_limit)
    condition = threading.Condition()
    state: dict[str, object] = {
        "total": 0,
        "limit": max_output_bytes,
        "limit_exceeded": False,
        "reader_error": None,
        "writer_error": None,
    }
    assert process.stdout is not None
    assert process.stderr is not None
    readers = (
        threading.Thread(
            target=_drain,
            args=(process.stdout, stdout_accumulator),
            kwargs={"condition": condition, "state": state},
            name="kaliv-stdout-drain",
            daemon=True,
        ),
        threading.Thread(
            target=_drain,
            args=(process.stderr, stderr_accumulator),
            kwargs={"condition": condition, "state": state},
            name="kaliv-stderr-drain",
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()
    writer: threading.Thread | None = None
    if stdin_bytes is not None:
        assert process.stdin is not None
        writer = threading.Thread(
            target=_write_stdin,
            args=(process.stdin, stdin_bytes),
            kwargs={"condition": condition, "state": state},
            name="kaliv-stdin-writer",
            daemon=True,
        )
        writer.start()

    deadline = time.monotonic() + timeout_seconds
    limit_exceeded = False
    timed_out = False
    terminated = False
    failure: BaseException | None = None
    try:
        while True:
            process_done = process.poll() is not None
            readers_done = all(not reader.is_alive() for reader in readers)
            writer_done = writer is None or not writer.is_alive()
            if process_done and readers_done and writer_done:
                break
            with condition:
                if bool(state["limit_exceeded"]):
                    limit_exceeded = True
                    break
                if state["reader_error"] is not None:
                    failure = state["reader_error"]  # type: ignore[assignment]
                    break
                if state["writer_error"] is not None:
                    failure = state["writer_error"]  # type: ignore[assignment]
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                condition.wait(timeout=min(remaining, 0.05))
        if limit_exceeded or timed_out or failure is not None:
            _terminate_tree(process)
            terminated = True
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if not terminated:
                _terminate_tree(process)
                terminated = True
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired as exc:
                raise BoundedSubprocessError(
                    "terminated process tree did not become quiescent"
                ) from exc
        for reader in readers:
            reader.join(timeout=10)
        if writer is not None:
            writer.join(timeout=10)
        if any(reader.is_alive() for reader in readers):
            raise BoundedSubprocessError(
                "subprocess output readers did not finish"
            )
        if writer is not None and writer.is_alive():
            raise BoundedSubprocessError(
                "subprocess stdin writer did not finish"
            )
        if state["reader_error"] is not None and failure is None:
            failure = state["reader_error"]  # type: ignore[assignment]
        if state["writer_error"] is not None and failure is None:
            failure = state["writer_error"]  # type: ignore[assignment]
        if failure is not None:
            raise BoundedSubprocessError(
                "subprocess output drain failed"
            ) from failure
        if int(state["total"]) > max_output_bytes:
            limit_exceeded = True
            if not terminated:
                # A descendant can keep inherited pipe handles alive after the
                # leader exits. Terminate the group/job even in that race.
                _terminate_tree(process)
                terminated = True
        return BoundedSubprocessResult(
            args=args,
            returncode=int(process.returncode),
            stdout=stdout_accumulator.evidence(),
            stderr=stderr_accumulator.evidence(),
            total_output_bytes=int(state["total"]),
            output_limit_exceeded=limit_exceeded,
            timed_out=timed_out,
            process_tree_terminated=terminated,
        )
    finally:
        tree_may_be_live = (
            process.poll() is None
            or any(reader.is_alive() for reader in readers)
            or (writer is not None and writer.is_alive())
        )
        if tree_may_be_live:
            try:
                _terminate_tree(process)
            finally:
                try:
                    process.wait(timeout=10)
                except Exception:
                    pass
        _close_tree_boundary(process)
