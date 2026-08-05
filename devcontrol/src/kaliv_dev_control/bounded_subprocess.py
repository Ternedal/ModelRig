"""Fail-closed streaming subprocess containment for the DC-L01 foundation.

DC-L01 contains commands on Linux with a subreaper supervisor. Windows support
fails closed until the native Job Object boundary lands in DC-L05.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping, Sequence

_CHUNK_BYTES = 64 * 1024
_MAX_TIMEOUT_SECONDS = 3600
_MAX_OUTPUT_BYTES = 256 * 1024 * 1024
_SUPERVISOR_FLAG = "--kaliv-linux-supervisor-v1"
_PR_SET_CHILD_SUBREAPER = 36


class BoundedSubprocessError(RuntimeError):
    """The bounded subprocess could not be proven safe."""


@dataclass(frozen=True, slots=True)
class BoundedStreamEvidence:
    prefix: bytes
    total_bytes: int
    sha256: str
    truncated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.prefix, bytes):
            raise BoundedSubprocessError("stream prefix must be bytes")
        if not isinstance(self.total_bytes, int) or isinstance(self.total_bytes, bool):
            raise BoundedSubprocessError("stream byte count is invalid")
        if self.total_bytes < len(self.prefix):
            raise BoundedSubprocessError("stream byte count is inconsistent")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise BoundedSubprocessError("stream hash is invalid")
        if self.truncated != (self.total_bytes > len(self.prefix)):
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
        if not self.args or any(not isinstance(arg, str) or not arg for arg in self.args):
            raise BoundedSubprocessError("result arguments are invalid")
        if not isinstance(self.returncode, int) or isinstance(self.returncode, bool):
            raise BoundedSubprocessError("result return code is invalid")
        if self.total_output_bytes != self.stdout.total_bytes + self.stderr.total_bytes:
            raise BoundedSubprocessError("combined output count is inconsistent")
        flags = (self.output_limit_exceeded, self.timed_out, self.process_tree_terminated)
        if any(not isinstance(flag, bool) for flag in flags):
            raise BoundedSubprocessError("result flag is invalid")
        if (self.output_limit_exceeded or self.timed_out) and not self.process_tree_terminated:
            raise BoundedSubprocessError("bounded failure lacks termination proof")


class _Accumulator:
    def __init__(self, prefix_limit: int) -> None:
        self.prefix_limit = prefix_limit
        self.prefix = bytearray()
        self.total = 0
        self.digest = hashlib.sha256()

    def add(self, chunk: bytes) -> None:
        self.total += len(chunk)
        self.digest.update(chunk)
        remaining = self.prefix_limit - len(self.prefix)
        if remaining > 0:
            self.prefix.extend(chunk[:remaining])

    def evidence(self) -> BoundedStreamEvidence:
        prefix = bytes(self.prefix)
        return BoundedStreamEvidence(
            prefix=prefix,
            total_bytes=self.total,
            sha256=self.digest.hexdigest(),
            truncated=self.total > len(prefix),
        )


def _validate(
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    max_output_bytes: int,
    stdout_prefix_bytes: int,
    stderr_prefix_bytes: int,
) -> tuple[tuple[str, ...], Path, dict[str, str]]:
    args = tuple(command)
    if not args or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in args):
        raise BoundedSubprocessError("command arguments are invalid")
    root = Path(cwd)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise BoundedSubprocessError("subprocess cwd must be an absolute directory")
    if isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        raise BoundedSubprocessError("subprocess timeout is invalid")
    if isinstance(max_output_bytes, bool) or not 1 <= max_output_bytes <= _MAX_OUTPUT_BYTES:
        raise BoundedSubprocessError("subprocess output budget is invalid")
    for value in (stdout_prefix_bytes, stderr_prefix_bytes):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= max_output_bytes:
            raise BoundedSubprocessError("stream prefix bound is invalid")
    if not isinstance(env, Mapping):
        raise BoundedSubprocessError("subprocess environment is invalid")
    clean: dict[str, str] = {}
    for key, value in env.items():
        if (
            not isinstance(key, str)
            or not key
            or "=" in key
            or "\0" in key
            or not isinstance(value, str)
            or "\0" in value
        ):
            raise BoundedSubprocessError("subprocess environment field is invalid")
        clean[key] = value
    return args, root, clean


def _linux_parent_map() -> dict[int, int]:
    parents: dict[int, int] = {}
    try:
        entries = os.scandir("/proc")
    except OSError as exc:
        raise BoundedSubprocessError("Linux /proc boundary is unavailable") from exc
    with entries:
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            try:
                tail = Path(entry.path, "stat").read_text(encoding="ascii").rpartition(") ")[2]
                fields = tail.split()
                if len(fields) >= 2:
                    parents[int(entry.name)] = int(fields[1])
            except (OSError, UnicodeError, ValueError):
                continue
    return parents


def _linux_descendants(root_pid: int) -> set[int]:
    parents = _linux_parent_map()
    descendants: set[int] = set()
    frontier = {root_pid}
    while frontier:
        found = {
            pid for pid, parent in parents.items()
            if parent in frontier and pid not in descendants
        }
        descendants.update(found)
        frontier = found
    return descendants


def _enable_subreaper() -> None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
    except (AttributeError, OSError) as exc:
        raise BoundedSubprocessError("Linux subreaper is unavailable") from exc
    if result != 0:
        raise BoundedSubprocessError(f"Linux subreaper failed with errno {ctypes.get_errno()}")


def _reap_adopted(root_pid: int) -> None:
    for pid, parent in _linux_parent_map().items():
        if parent == os.getpid() and pid != root_pid:
            try:
                os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, ProcessLookupError):
                pass


def _kill_supervised_tree(child: subprocess.Popen[bytes]) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        for pid in _linux_descendants(os.getpid()):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        child.poll()
        _reap_adopted(child.pid)
        if not _linux_descendants(os.getpid()):
            return True
        time.sleep(0.01)
    return False


def _supervisor_main(encoded: str) -> int:
    if not sys.platform.startswith("linux"):
        return 126
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeError):
        return 126
    if not isinstance(payload, list) or not payload or any(
        not isinstance(arg, str) or not arg or "\0" in arg for arg in payload
    ):
        return 126
    try:
        _enable_subreaper()
        child = subprocess.Popen(
            payload,
            stdin=sys.stdin.buffer,
            stdout=sys.stdout.buffer,
            stderr=sys.stderr.buffer,
            env=os.environ.copy(),
            shell=False,
            text=False,
            bufsize=0,
            close_fds=False,
        )
    except (BoundedSubprocessError, OSError):
        return 126
    stop = False

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    root_code: int | None = None
    while True:
        code = child.poll()
        if code is not None:
            root_code = int(code)
        _reap_adopted(child.pid)
        descendants = _linux_descendants(os.getpid())
        if stop:
            return 128 + signal.SIGTERM if _kill_supervised_tree(child) else 125
        if root_code is not None and not descendants:
            return root_code if root_code >= 0 else 128 - root_code
        time.sleep(0.02)


def _spawn(
    args: tuple[str, ...], cwd: Path, env: dict[str, str], stdin: int
) -> subprocess.Popen[bytes]:
    if os.name == "nt":
        raise BoundedSubprocessError(
            "Windows containment is deferred to DC-L05 and fails closed in DC-L01"
        )
    if not sys.platform.startswith("linux"):
        raise BoundedSubprocessError("DC-L01 subprocess containment requires Linux")
    encoded = base64.urlsafe_b64encode(
        json.dumps(list(args), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    try:
        return subprocess.Popen(
            (sys.executable, str(Path(__file__).resolve()), _SUPERVISOR_FLAG, encoded),
            cwd=cwd,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            shell=False,
            text=False,
            bufsize=0,
            start_new_session=True,
        )
    except OSError as exc:
        raise BoundedSubprocessError("subprocess supervisor could not start") from exc


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        os.kill(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise BoundedSubprocessError("Linux supervisor termination failed") from exc
    deadline = time.monotonic() + 6
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise BoundedSubprocessError("Linux supervisor fallback failed") from exc


def _drain(
    stream: BinaryIO,
    accumulator: _Accumulator,
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
            state["reader_error"] = state["reader_error"] or exc
            condition.notify_all()
    finally:
        stream.close()


def _write_stdin(
    stream: BinaryIO,
    payload: bytes,
    condition: threading.Condition,
    state: dict[str, object],
) -> None:
    try:
        stream.write(payload)
        stream.flush()
    except (BrokenPipeError, OSError):
        pass
    except BaseException as exc:
        with condition:
            state["writer_error"] = state["writer_error"] or exc
            condition.notify_all()
    finally:
        stream.close()


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
    """Run one command behind the DC-L01 Linux containment boundary."""
    if stdin_bytes is not None and not isinstance(stdin_bytes, bytes):
        raise BoundedSubprocessError("subprocess stdin must be bytes or absent")
    stdout_limit = max_output_bytes if stdout_prefix_bytes is None else stdout_prefix_bytes
    stderr_limit = max_output_bytes if stderr_prefix_bytes is None else stderr_prefix_bytes
    args, root, clean_env = _validate(
        command, cwd, env, timeout_seconds, max_output_bytes, stdout_limit, stderr_limit
    )
    process = _spawn(
        args, root, clean_env,
        subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
    )
    stdout_acc = _Accumulator(stdout_limit)
    stderr_acc = _Accumulator(stderr_limit)
    condition = threading.Condition()
    state: dict[str, object] = {
        "total": 0,
        "limit": max_output_bytes,
        "limit_exceeded": False,
        "reader_error": None,
        "writer_error": None,
    }
    assert process.stdout is not None and process.stderr is not None
    readers = (
        threading.Thread(target=_drain, args=(process.stdout, stdout_acc, condition, state), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr_acc, condition, state), daemon=True),
    )
    for reader in readers:
        reader.start()
    writer: threading.Thread | None = None
    if stdin_bytes is not None:
        assert process.stdin is not None
        writer = threading.Thread(
            target=_write_stdin,
            args=(process.stdin, stdin_bytes, condition, state),
            daemon=True,
        )
        writer.start()
    deadline = time.monotonic() + timeout_seconds
    limit_exceeded = timed_out = terminated = False
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
                failure = state["reader_error"] or state["writer_error"]  # type: ignore[assignment]
                if failure is not None:
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
        except subprocess.TimeoutExpired as exc:
            if not terminated:
                _terminate_tree(process)
                terminated = True
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                raise BoundedSubprocessError("process tree did not quiesce") from exc
        for reader in readers:
            reader.join(timeout=10)
        if writer is not None:
            writer.join(timeout=10)
        if any(reader.is_alive() for reader in readers):
            raise BoundedSubprocessError("output reader did not finish")
        if writer is not None and writer.is_alive():
            raise BoundedSubprocessError("stdin writer did not finish")
        failure = failure or state["reader_error"] or state["writer_error"]  # type: ignore[assignment]
        if failure is not None:
            raise BoundedSubprocessError("subprocess stream handling failed") from failure
        if int(state["total"]) > max_output_bytes:
            limit_exceeded = True
            if not terminated:
                _terminate_tree(process)
                terminated = True
        return BoundedSubprocessResult(
            args=args,
            returncode=int(process.returncode),
            stdout=stdout_acc.evidence(),
            stderr=stderr_acc.evidence(),
            total_output_bytes=int(state["total"]),
            output_limit_exceeded=limit_exceeded,
            timed_out=timed_out,
            process_tree_terminated=terminated,
        )
    finally:
        if process.poll() is None or any(r.is_alive() for r in readers) or (
            writer is not None and writer.is_alive()
        ):
            try:
                _terminate_tree(process)
            finally:
                try:
                    process.wait(timeout=10)
                except Exception:
                    pass


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != _SUPERVISOR_FLAG:
        raise SystemExit(126)
    raise SystemExit(_supervisor_main(sys.argv[2]))
