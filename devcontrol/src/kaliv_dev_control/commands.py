"""Allowlisted development commands and deterministic execution receipts.

Command arguments come from the registry, never from a model or task payload.
Each command runs at the exact task SHA in a disposable local Git sandbox. A
Linux Landlock domain confines persistent filesystem writes to that sandbox,
while an inherited seccomp filter denies alternate metadata mutation entrypoints
that Landlock cannot mediate, before positive evidence can be issued.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contract import DevelopmentTask
from .workspace import Runner, SubprocessRunner, WorkspaceError

_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
RECEIPT_SCHEMA = "kaliv-development-command-receipt/v1"
_SANDBOX_MAX_FILES = 250_000
_SANDBOX_MAX_BYTES = 1_000_000_000
_RESERVED_ENV = {"HOME", "XDG_CONFIG_HOME", "TMPDIR", "PWD"}

_LANDLOCK_SANDBOX_BOOTSTRAP = r"""
import ctypes
import errno
import os
import sys

SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_ERRNO = 0x00050000
SECCOMP_RET_ALLOW = 0x7FFF0000
BPF_LD_W_ABS = 0x20
BPF_JMP_JEQ_K = 0x15
BPF_JMP_JSET_K = 0x45
BPF_RET_K = 0x06
X32_SYSCALL_BIT = 0x40000000

LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

class RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]

class PathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int),
    ]

class SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]

class SockFprog(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ushort),
        ("filter", ctypes.POINTER(SockFilter)),
    ]

libc = ctypes.CDLL(None, use_errno=True)

def fail(name):
    error = ctypes.get_errno()
    raise OSError(error, f"{name}: {os.strerror(error)}")

def syscall(number, *args):
    result = libc.syscall(ctypes.c_long(number), *args)
    if result < 0:
        fail("syscall")
    return int(result)

def install_metadata_seccomp():
    machine = os.uname().machine.lower()
    common_modern = (425, 426, 427, 452, 463, 466, 469)
    profiles = {
        "x86_64": (
            0xC000003E,
            (
                16,
                90, 91, 92, 93, 94, 132,
                188, 189, 190, 197, 198, 199,
                235, 260, 261, 268, 280,
                *common_modern,
            ),
            True,
        ),
        "amd64": (
            0xC000003E,
            (
                16,
                90, 91, 92, 93, 94, 132,
                188, 189, 190, 197, 198, 199,
                235, 260, 261, 268, 280,
                *common_modern,
            ),
            True,
        ),
        "aarch64": (
            0xC00000B7,
            (
                5, 6, 7, 14, 15, 16, 29,
                52, 53, 54, 55, 88,
                *common_modern,
            ),
            False,
        ),
        "arm64": (
            0xC00000B7,
            (
                5, 6, 7, 14, 15, 16, 29,
                52, 53, 54, 55, 88,
                *common_modern,
            ),
            False,
        ),
    }
    try:
        audit_arch, denied_syscalls, reject_x32 = profiles[machine]
    except KeyError as exc:
        raise RuntimeError(f"unsupported seccomp architecture: {machine}") from exc

    instructions = [
        SockFilter(BPF_LD_W_ABS, 0, 0, 4),
        SockFilter(BPF_JMP_JEQ_K, 1, 0, audit_arch),
        SockFilter(BPF_RET_K, 0, 0, SECCOMP_RET_KILL_PROCESS),
        SockFilter(BPF_LD_W_ABS, 0, 0, 0),
    ]
    if reject_x32:
        instructions.extend(
            (
                SockFilter(BPF_JMP_JSET_K, 0, 1, X32_SYSCALL_BIT),
                SockFilter(
                    BPF_RET_K,
                    0,
                    0,
                    SECCOMP_RET_ERRNO | errno.EPERM,
                ),
            )
        )
    for number in sorted(set(denied_syscalls)):
        instructions.extend(
            (
                SockFilter(BPF_JMP_JEQ_K, 0, 1, number),
                SockFilter(
                    BPF_RET_K,
                    0,
                    0,
                    SECCOMP_RET_ERRNO | errno.EPERM,
                ),
            )
        )
    instructions.append(SockFilter(BPF_RET_K, 0, 0, SECCOMP_RET_ALLOW))
    filters = (SockFilter * len(instructions))(*instructions)
    program = SockFprog(
        len(instructions),
        ctypes.cast(filters, ctypes.POINTER(SockFilter)),
    )
    if libc.prctl(
        PR_SET_SECCOMP,
        SECCOMP_MODE_FILTER,
        ctypes.byref(program),
        0,
        0,
    ) != 0:
        fail("seccomp")

try:
    if len(sys.argv) < 4:
        raise RuntimeError("missing sandbox root, command cwd or command")
    sandbox_root = os.path.realpath(sys.argv[1])
    command_cwd = os.path.realpath(sys.argv[2])
    command = sys.argv[3:]
    if os.path.commonpath((sandbox_root, command_cwd)) != sandbox_root:
        raise RuntimeError("command cwd escaped sandbox root")

    abi = syscall(
        SYS_LANDLOCK_CREATE_RULESET,
        ctypes.c_void_p(),
        ctypes.c_size_t(0),
        ctypes.c_uint(LANDLOCK_CREATE_RULESET_VERSION),
    )
    if abi < 3:
        raise RuntimeError("Landlock ABI 3 or newer is required")
    handled = (
        LANDLOCK_ACCESS_FS_WRITE_FILE
        | LANDLOCK_ACCESS_FS_REMOVE_DIR
        | LANDLOCK_ACCESS_FS_REMOVE_FILE
        | LANDLOCK_ACCESS_FS_MAKE_CHAR
        | LANDLOCK_ACCESS_FS_MAKE_DIR
        | LANDLOCK_ACCESS_FS_MAKE_REG
        | LANDLOCK_ACCESS_FS_MAKE_SOCK
        | LANDLOCK_ACCESS_FS_MAKE_FIFO
        | LANDLOCK_ACCESS_FS_MAKE_BLOCK
        | LANDLOCK_ACCESS_FS_MAKE_SYM
        | LANDLOCK_ACCESS_FS_REFER
        | LANDLOCK_ACCESS_FS_TRUNCATE
    )

    ruleset_attr = RulesetAttr(handled)
    ruleset_fd = syscall(
        SYS_LANDLOCK_CREATE_RULESET,
        ctypes.byref(ruleset_attr),
        ctypes.c_size_t(ctypes.sizeof(ruleset_attr)),
        ctypes.c_uint(0),
    )
    root_fd = os.open(
        sandbox_root,
        os.O_PATH | os.O_CLOEXEC | os.O_DIRECTORY,
    )
    try:
        path_attr = PathBeneathAttr(handled, root_fd)
        syscall(
            SYS_LANDLOCK_ADD_RULE,
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
            ctypes.byref(path_attr),
            ctypes.c_uint(0),
        )
    finally:
        os.close(root_fd)

    null_access = LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_TRUNCATE
    null_fd = os.open("/dev/null", os.O_PATH | os.O_CLOEXEC)
    try:
        null_attr = PathBeneathAttr(null_access, null_fd)
        syscall(
            SYS_LANDLOCK_ADD_RULE,
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
            ctypes.byref(null_attr),
            ctypes.c_uint(0),
        )
    finally:
        os.close(null_fd)

    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        fail("no_new_privs")
    syscall(
        SYS_LANDLOCK_RESTRICT_SELF,
        ctypes.c_int(ruleset_fd),
        ctypes.c_uint(0),
    )
    os.close(ruleset_fd)
    install_metadata_seccomp()
    os.chdir(command_cwd)
    os.execvpe(command[0], command, os.environ)
except BaseException as exc:
    print(f"kaliv filesystem sandbox failed: {exc}", file=sys.stderr)
    raise SystemExit(126)
"""


class CommandPolicyError(ValueError):
    """A command template or requested command grants ambiguous authority."""


class CommandExecutionError(RuntimeError):
    """A command could not complete while preserving workspace integrity."""


@dataclass(frozen=True, slots=True)
class CommandTemplate:
    command_id: str
    argv: tuple[str, ...]
    cwd: str = "."
    max_timeout_seconds: int = 900
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _COMMAND_ID.fullmatch(self.command_id) is None:
            raise CommandPolicyError("invalid command id")
        if isinstance(self.argv, (str, bytes)) or not isinstance(self.argv, Sequence):
            raise CommandPolicyError("argv must be a sequence of strings")
        immutable_argv = tuple(self.argv)
        if not immutable_argv or any(
            not isinstance(item, str) or not item or "\x00" in item
            for item in immutable_argv
        ):
            raise CommandPolicyError("argv must contain canonical non-empty strings")
        object.__setattr__(self, "argv", immutable_argv)

        if not isinstance(self.cwd, str) or not self.cwd or "\x00" in self.cwd:
            raise CommandPolicyError("command cwd must be repository-relative")
        if self.cwd != ".":
            raw_parts = self.cwd.split("/")
            path = PurePosixPath(self.cwd)
            if (
                self.cwd.startswith("/")
                or "\\" in self.cwd
                or any(part in {"", ".", ".."} for part in raw_parts)
                or path.as_posix() != self.cwd
            ):
                raise CommandPolicyError(
                    "command cwd must be canonical and repository-relative"
                )
        if not 1 <= self.max_timeout_seconds <= 86_400:
            raise CommandPolicyError("command timeout is outside bounds")

        immutable_env: dict[str, str] = {}
        for key, value in self.env.items():
            if (
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or "\x00" in key + value
            ):
                raise CommandPolicyError("command environment is invalid")
            if key.startswith("GIT_") or key in _RESERVED_ENV:
                raise CommandPolicyError(
                    "command environment cannot override Git isolation"
                )
            immutable_env[key] = value
        object.__setattr__(self, "env", MappingProxyType(immutable_env))


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    task_id: str
    task_sha256: str
    base_sha: str
    command_id: str
    argv_sha256: str
    cwd: str
    returncode: int
    stdout_sha256: str
    stderr_sha256: str
    output_bytes: int
    duration_ms: int
    workspace_before_sha256: str
    workspace_after_sha256: str
    workspace_unchanged: bool
    workspace_reset: bool
    passed: bool
    schema: str = RECEIPT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "command_id": self.command_id,
            "argv_sha256": self.argv_sha256,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "output_bytes": self.output_bytes,
            "duration_ms": self.duration_ms,
            "workspace_before_sha256": self.workspace_before_sha256,
            "workspace_after_sha256": self.workspace_after_sha256,
            "workspace_unchanged": self.workspace_unchanged,
            "workspace_reset": self.workspace_reset,
            "passed": self.passed,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


class CommandRegistry:
    """Resolve fixed command templates by immutable command id."""

    def __init__(self, templates: Sequence[CommandTemplate]) -> None:
        values: dict[str, CommandTemplate] = {}
        for template in templates:
            if template.command_id in values:
                raise CommandPolicyError(f"duplicate command id: {template.command_id}")
            values[template.command_id] = template
        self._templates = MappingProxyType(values)

    def resolve(self, task: DevelopmentTask, command_id: str) -> CommandTemplate:
        if command_id not in task.allowed_command_ids:
            raise CommandPolicyError("command is not allowed by the task contract")
        try:
            return self._templates[command_id]
        except KeyError as exc:
            raise CommandPolicyError("command id is not registered") from exc


def default_registry() -> CommandRegistry:
    """Return an empty registry until templates are separately reviewed."""

    return CommandRegistry(())


class _CommandSandbox:
    """Build and destroy an independent exact-HEAD Git repository."""

    def __init__(self, executor: "CommandExecutor", task: DevelopmentTask, source: Path) -> None:
        self.executor = executor
        self.task = task
        self.source = source
        self.root: Path | None = None
        self.repository: Path | None = None
        self.home: Path | None = None
        self.xdg: Path | None = None
        self.tmp: Path | None = None
        self.disabled_hooks: Path | None = None

    @staticmethod
    def _chmod_for_removal(path: Path) -> None:
        try:
            if not path.is_symlink():
                path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            pass

    def cleanup(self) -> None:
        if self.root is None or not self.root.exists():
            return
        for path in sorted(
            self.root.rglob("*"), key=lambda item: len(item.parts), reverse=True
        ):
            self._chmod_for_removal(path)
        self._chmod_for_removal(self.root)
        try:
            shutil.rmtree(self.root)
        except OSError as exc:
            raise CommandExecutionError("command sandbox could not be destroyed") from exc
        finally:
            self.root = None
            self.repository = None

    @staticmethod
    def _bounded_fingerprint(root: Path) -> str:
        if root.is_symlink() or not root.is_dir():
            raise CommandExecutionError("sandbox Git metadata is missing or unsafe")
        digest = hashlib.sha256()
        files = 0
        total = 0
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            if path.is_symlink():
                raise CommandExecutionError("command created a Git metadata symlink")
            if path.is_dir():
                digest.update(b"D\0" + relative + b"\0")
                continue
            if not path.is_file():
                raise CommandExecutionError("command created unsupported Git metadata")
            file_stat = path.stat()
            files += 1
            total += file_stat.st_size
            if files > _SANDBOX_MAX_FILES or total > _SANDBOX_MAX_BYTES:
                raise CommandExecutionError("command exceeded Git metadata bounds")
            digest.update(b"F\0" + relative + b"\0")
            digest.update(str(stat.S_IMODE(file_stat.st_mode)).encode("ascii") + b"\0")
            with path.open("rb") as handle:
                while chunk := handle.read(131_072):
                    digest.update(chunk)
            digest.update(b"\0")
        return digest.hexdigest()

    def _assert_no_source_disclosure(self) -> None:
        if self.repository is None or self.root is None:
            raise CommandExecutionError("command sandbox is not prepared")
        needles = (
            str(self.source).encode("utf-8"),
            str(self.root / "source.bundle").encode("utf-8"),
        )
        candidates = [self.repository / ".git" / "config"]
        logs = self.repository / ".git" / "logs"
        if logs.exists():
            candidates.extend(path for path in logs.rglob("*") if path.is_file())
        for candidate in candidates:
            data = candidate.read_bytes()
            if any(needle in data for needle in needles):
                raise CommandExecutionError(
                    "command sandbox disclosed the source repository path"
                )
        alternates = self.repository / ".git" / "objects" / "info" / "alternates"
        if alternates.exists():
            raise CommandExecutionError("command sandbox must not use object alternates")

    def create(self) -> tuple[str, str]:
        self.root = Path(tempfile.mkdtemp(prefix=".kaliv-command-sandbox-")).resolve()
        if self.root.is_symlink():
            raise CommandExecutionError("command sandbox root is unsafe")
        self.repository = self.root / "repository"
        bundle = self.root / "source.bundle"
        self.home = self.root / "home"
        self.xdg = self.root / "xdg"
        self.tmp = self.root / "tmp"
        self.disabled_hooks = self.root / "disabled-hooks"
        for directory in (self.home, self.xdg, self.tmp, self.disabled_hooks):
            directory.mkdir()
        (self.root / "empty-git-config").touch()

        try:
            self.executor._run_git(
                self.source,
                "bundle", "create", str(bundle), "HEAD",
                timeout_seconds=300,
                max_output_bytes=4_000_000,
            )
            if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size > _SANDBOX_MAX_BYTES:
                raise CommandExecutionError("command sandbox bundle is unsafe or too large")
            self.executor._run_git(
                self.root,
                "clone", "--no-checkout", "--no-tags", "--quiet", str(bundle), str(self.repository),
                timeout_seconds=300,
                max_output_bytes=4_000_000,
            )
            self.executor._run_git(
                self.repository,
                "checkout", "--quiet", "--detach", self.task.base_sha,
                timeout_seconds=300,
                max_output_bytes=4_000_000,
            )
            self.executor._run_git(
                self.repository, "remote", "remove", "origin", max_output_bytes=1_000_000
            )
            self.executor._run_git(
                self.repository,
                "config", "--local", "core.hooksPath", str(self.disabled_hooks),
                max_output_bytes=1_000_000,
            )
            self.executor._run_git(
                self.repository,
                "config", "--local", "core.logAllRefUpdates", "false",
                max_output_bytes=1_000_000,
            )
            self.executor._run_git(
                self.repository,
                "config", "--local", "gc.auto", "0",
                max_output_bytes=1_000_000,
            )
            logs = self.repository / ".git" / "logs"
            if logs.exists():
                shutil.rmtree(logs)
            for name in ("FETCH_HEAD", "ORIG_HEAD"):
                (self.repository / ".git" / name).unlink(missing_ok=True)
            bundle.unlink()
            self.executor._verify_head(self.task, self.repository)
            worktree, clean = self.executor._snapshot(self.repository)
            if not clean:
                raise CommandExecutionError("new command sandbox is not clean")
            metadata = self._bounded_fingerprint(self.repository / ".git")
            self._assert_no_source_disclosure()
            self.executor._verify_source_clean(self.task, self.source)
            return worktree, metadata
        except Exception:
            self.cleanup()
            raise

    def environment(self, template_env: Mapping[str, str], cwd: Path) -> dict[str, str]:
        if any(
            value is None
            for value in (self.root, self.home, self.xdg, self.tmp, self.disabled_hooks)
        ):
            raise CommandExecutionError("command sandbox is not prepared")
        environment = dict(template_env)
        environment.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.xdg),
                "TMPDIR": str(self.tmp),
                "PWD": str(cwd),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": str(self.root / "empty-git-config"),
                "GIT_CONFIG_GLOBAL": str(self.root / "empty-git-config"),
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.hooksPath",
                "GIT_CONFIG_VALUE_0": str(self.disabled_hooks),
            }
        )
        source_text = str(self.source)
        if any(source_text in value for value in environment.values()):
            raise CommandExecutionError(
                "command environment disclosed the source repository path"
            )
        return environment

    def metadata_fingerprint(self) -> str:
        if self.repository is None:
            raise CommandExecutionError("command sandbox is not prepared")
        return self._bounded_fingerprint(self.repository / ".git")


class CommandExecutor:
    """Execute a fixed command and prove it did not alter repository state."""

    def __init__(
        self,
        registry: CommandRegistry | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.registry = registry or default_registry()
        self.runner = runner or SubprocessRunner()

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _combined_fingerprint(worktree: str, metadata: str) -> str:
        return hashlib.sha256((worktree + "\x00" + metadata).encode("ascii")).hexdigest()

    def _run_git(
        self,
        workspace: Path,
        *args: str,
        max_output_bytes: int = 4_000_000,
        timeout_seconds: int = 60,
    ) -> str:
        result = self.runner.run(
            ["git", *args],
            cwd=workspace,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env={
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
            },
        )
        if result.returncode != 0:
            raise CommandExecutionError(f"git operation failed: {args[0]}")
        return result.stdout

    def _verify_head(self, task: DevelopmentTask, workspace: Path) -> None:
        head = self._run_git(workspace, "rev-parse", "HEAD").strip()
        if head != task.base_sha:
            raise CommandExecutionError("workspace HEAD does not match task base SHA")

    def _snapshot(self, workspace: Path) -> tuple[str, bool]:
        cached = self._run_git(
            workspace, "diff", "--cached", "--binary", "--no-ext-diff", "--"
        )
        unstaged = self._run_git(
            workspace, "diff", "--binary", "--no-ext-diff", "--"
        )
        untracked = self._run_git(
            workspace, "ls-files", "--others", "--exclude-standard", "-z"
        )
        ignored = self._run_git(
            workspace,
            "ls-files", "--others", "--ignored", "--exclude-standard", "-z",
        )
        fingerprint = self._sha256(cached.encode("utf-8", errors="replace"))
        return fingerprint, not bool(cached or unstaged or untracked or ignored)

    def _verify_source_clean(
        self,
        task: DevelopmentTask,
        workspace: Path,
        expected_fingerprint: str | None = None,
    ) -> str:
        self._verify_head(task, workspace)
        fingerprint, clean = self._snapshot(workspace)
        if not clean:
            raise CommandExecutionError(
                "source workspace has staged, unstaged, untracked or ignored changes"
            )
        if expected_fingerprint is not None and fingerprint != expected_fingerprint:
            raise CommandExecutionError(
                "source workspace fingerprint changed during command execution"
            )
        return fingerprint

    @staticmethod
    def _cwd(workspace: Path, relative: str) -> Path:
        root = workspace.resolve()
        target = root if relative == "." else (root / PurePosixPath(relative)).resolve()
        if not target.is_relative_to(root) or not target.is_dir():
            raise CommandExecutionError("command cwd escaped or does not exist")
        cursor = target
        while cursor != root:
            if cursor.is_symlink():
                raise CommandExecutionError("command cwd contains a symlink")
            cursor = cursor.parent
        return target

    @staticmethod
    def _confined_argv(
        sandbox_root: Path,
        cwd: Path,
        argv: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not sys.platform.startswith("linux"):
            raise CommandExecutionError(
                "filesystem-confined command execution is Linux-only in DC-L01"
            )
        return (
            sys.executable,
            "-I",
            "-c",
            _LANDLOCK_SANDBOX_BOOTSTRAP,
            str(sandbox_root),
            str(cwd),
            *argv,
        )

    def execute(
        self,
        task: DevelopmentTask,
        workspace: Path,
        command_id: str,
    ) -> CommandReceipt:
        template = self.registry.resolve(task, command_id)
        source = workspace.resolve()
        source_text = str(source)
        if any(source_text in argument for argument in template.argv):
            raise CommandPolicyError(
                "command arguments cannot disclose the source workspace"
            )
        source_before = self._verify_source_clean(task, source)
        self._cwd(source, template.cwd)

        sandbox = _CommandSandbox(self, task, source)
        result = None
        duration_ms = 0
        before_worktree = ""
        before_metadata = ""
        after_worktree = ""
        after_metadata = ""
        after_clean = False
        try:
            before_worktree, before_metadata = sandbox.create()
            if sandbox.repository is None or sandbox.root is None:
                raise CommandExecutionError("command sandbox was not created")
            cwd = self._cwd(sandbox.repository, template.cwd)
            command_env = sandbox.environment(template.env, cwd)
            confined_argv = self._confined_argv(sandbox.root, cwd, template.argv)
            started = time.monotonic()
            try:
                result = self.runner.run(
                    confined_argv,
                    cwd=cwd,
                    timeout_seconds=min(
                        task.budget.max_runtime_seconds,
                        template.max_timeout_seconds,
                    ),
                    max_output_bytes=task.budget.max_output_bytes,
                    env=command_env,
                )
            except WorkspaceError as exc:
                raise CommandExecutionError(
                    "command execution did not complete safely"
                ) from exc
            duration_ms = max(0, int((time.monotonic() - started) * 1_000))
            try:
                self._verify_head(task, sandbox.repository)
                after_worktree, after_clean = self._snapshot(sandbox.repository)
                after_metadata = sandbox.metadata_fingerprint()
            except (WorkspaceError, CommandExecutionError) as exc:
                raise CommandExecutionError(
                    "post-command workspace verification failed"
                ) from exc
        finally:
            cleanup_error: Exception | None = None
            source_error: Exception | None = None
            try:
                sandbox.cleanup()
            except Exception as exc:
                cleanup_error = exc
            try:
                self._verify_source_clean(
                    task, source, expected_fingerprint=source_before
                )
            except Exception as exc:
                source_error = exc
            if source_error is not None:
                raise CommandExecutionError(
                    "source workspace integrity could not be verified"
                ) from source_error
            if cleanup_error is not None:
                raise CommandExecutionError("command sandbox cleanup failed") from cleanup_error

        if result is None:
            raise CommandExecutionError("command returned no result")
        before_sha = self._combined_fingerprint(before_worktree, before_metadata)
        after_sha = self._combined_fingerprint(after_worktree, after_metadata)
        unchanged = before_sha == after_sha and after_clean
        reset = not unchanged

        task_sha = self._sha256(task.canonical_json().encode("utf-8"))
        stdout = result.stdout.encode("utf-8")
        stderr = result.stderr.encode("utf-8")
        argv = json.dumps(
            list(template.argv), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return CommandReceipt(
            task_id=task.task_id,
            task_sha256=task_sha,
            base_sha=task.base_sha,
            command_id=command_id,
            argv_sha256=self._sha256(argv),
            cwd=template.cwd,
            returncode=result.returncode,
            stdout_sha256=self._sha256(stdout),
            stderr_sha256=self._sha256(stderr),
            output_bytes=len(stdout) + len(stderr),
            duration_ms=duration_ms,
            workspace_before_sha256=before_sha,
            workspace_after_sha256=after_sha,
            workspace_unchanged=unchanged,
            workspace_reset=reset,
            passed=result.returncode == 0 and unchanged,
        )
