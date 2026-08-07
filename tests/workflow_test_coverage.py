"""Contract test: every repository and landed DevControl test is reached by CI.

Run: python3 tests/workflow_test_coverage.py
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
workflow = (root / ".github/workflows/_tests.yml").read_text(encoding="utf-8")
sys.path.insert(0, str(root / "devcontrol/src"))

import kaliv_dev_control.commands as commands_module
import kaliv_dev_control.github_read as github_read_module
from kaliv_dev_control.catalog import (
    CatalogError,
    ProjectCommandSpec,
    TaskBoundCommandRegistry,
    modelrig_command_catalog,
)
from kaliv_dev_control.commands import CommandExecutor, CommandTemplate
from kaliv_dev_control.contract import (
    DevelopmentTask,
    MergeAuthority,
    Risk,
    TaskBudget,
)
from kaliv_dev_control.github_read import GitHubReadError

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


m = re.search(r"for f in ([^;]+); do", workflow)
check(m is not None, "the workflow still runs repository tests through a readable glob loop")
if m is None:
    print("\n===== TEST COVERAGE: cannot verify -- workflow shape changed =====")
    raise SystemExit(1)

patterns = m.group(1).split()
check(len(patterns) >= 2, f"glob patterns found: {' '.join(patterns)}")

files = sorted(p.relative_to(root).as_posix() for p in (root / "tests").glob("*.py"))
check(len(files) > 10, f"{len(files)} repository test files on disk")

missed = [f for f in files if not any(fnmatch.fnmatch(f, g) for g in patterns)]
check(
    not missed,
    "every repository test file matches a CI pattern"
    if not missed
    else f"UNREACHED BY CI: {', '.join(missed)} -- rename them or widen the glob",
)

fake = ["tests/agent_smoke.py", "tests/worker_unit.py"]
fake_missed = [f for f in fake if not any(fnmatch.fnmatch(f, g) for g in patterns)]
check(
    fake_missed == ["tests/agent_smoke.py"],
    "self-test: a repository file outside the patterns is detected",
)

discovery_command = (
    "PYTHONPATH=devcontrol/src python3 -m unittest discover "
    "-s devcontrol/tests -p 'test_*.py' -v"
)
check(
    discovery_command in workflow,
    "the workflow runs the exact DevControl unittest discovery command",
)

devcontrol_tests = sorted((root / "devcontrol/tests").glob("test_*.py"))
expected = {
    "test_bounded_subprocess.py",
    "test_campaign_review.py",
    "test_durable_publication.py",
    "test_foundation.py",
    "test_proposal_reload.py",
    "test_review_reload.py",
    "test_slice2.py",
    "test_slice5.py",
    "test_store_proposal.py",
}
observed = {path.name for path in devcontrol_tests}
check(
    observed == expected,
    f"the nine DC-L01–L03 test modules are present: {sorted(observed)}",
)
check(
    all(path.is_file() for path in devcontrol_tests),
    "every DevControl test matched by unittest discovery is a regular file",
)

receipt_schema = json.loads(
    (
        root
        / "devcontrol/schemas/development-github-read-receipt-v1.schema.json"
    ).read_text(encoding="utf-8")
)
repository_pattern = re.compile(
    receipt_schema["properties"]["repository"]["pattern"]
)
check(
    repository_pattern.fullmatch("Ternedal/ModelRig") is not None,
    "the GitHub receipt schema accepts the canonical ModelRig repository",
)
invalid_repositories = (
    "./ModelRig",
    "Ternedal/..",
    "Ternedal/Model Rig",
    "Ternedal/\x00ModelRig",
)
check(
    all(repository_pattern.fullmatch(value) is None for value in invalid_repositories),
    "the GitHub receipt schema rejects dot segments, whitespace and NUL authority",
)

blocked_environment = True
for key, value in (
    ("GOROOT", "."),
    ("PYTHONUSERBASE", "."),
    ("GOTOOLCHAIN", "auto"),
    ("PATH", "/attacker/bin"),
):
    try:
        ProjectCommandSpec(
            "modelrig.contract.probe",
            "python",
            ("-V",),
            ".",
            10,
            {key: value},
        )
    except CatalogError:
        continue
    blocked_environment = False
catalog_path = modelrig_command_catalog().resolve(
    "modelrig.devcontrol.tests"
).env.get("PATH")
injected_path = ProjectCommandSpec(
    "modelrig.contract.default-path",
    "python",
    ("-V",),
    ".",
    10,
    {},
).env.get("PATH")
check(
    blocked_environment
    and catalog_path == "/usr/bin:/bin"
    and injected_path == "/usr/bin:/bin",
    "every accepted catalog entry receives the fixed child-tool PATH",
)

snapshot_task = DevelopmentTask(
    task_id="DC-L03-SNAPSHOT",
    repository="Ternedal/ModelRig",
    base_sha="a" * 40,
    goal="Prove one private execution task snapshot.",
    acceptance_criteria=("Execution remains bound to task A.",),
    risk=Risk.LOW,
    allowed_paths=("devcontrol/**",),
    protected_paths=(".github/**",),
    allowed_command_ids=("modelrig.snapshot.probe",),
    required_tests=("snapshot execution regression",),
    budget=TaskBudget(
        max_changed_files=1,
        max_added_lines=1,
        max_deleted_lines=0,
        max_attempts=1,
        max_runtime_seconds=37,
        max_output_bytes=4096,
    ),
    merge_authority=MergeAuthority.HUMAN,
)
expected_snapshot_json = snapshot_task.canonical_json()
expected_snapshot_sha = hashlib.sha256(
    expected_snapshot_json.encode("utf-8")
).hexdigest()
snapshot_registry = TaskBoundCommandRegistry(
    (
        CommandTemplate(
            "modelrig.snapshot.probe",
            ("/bin/true",),
            ".",
            50,
            {"PATH": "/usr/bin:/bin"},
        ),
    ),
    snapshot_task,
    object(),
    "/trusted/python3",
)


class _MutatingRunner:
    def __init__(self, caller_task: DevelopmentTask) -> None:
        self.caller_task = caller_task
        self.timeout_seconds = None
        self.max_output_bytes = None

    def run(
        self,
        argv,
        *,
        cwd,
        timeout_seconds,
        max_output_bytes,
        env=None,
        stdin_data=None,
    ):
        del argv, cwd, env, stdin_data
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        object.__setattr__(self.caller_task, "task_id", "MUTATED")
        object.__setattr__(self.caller_task, "base_sha", "b" * 40)
        object.__setattr__(
            self.caller_task,
            "budget",
            TaskBudget(
                max_changed_files=2,
                max_added_lines=2,
                max_deleted_lines=1,
                max_attempts=2,
                max_runtime_seconds=999,
                max_output_bytes=999_999,
            ),
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class _SnapshotSandbox:
    observed_task = None

    def __init__(self, executor, task, source) -> None:
        self.executor = executor
        self.task = task
        self.source = source
        self.root = source
        self.repository = source
        type(self).observed_task = task

    def create(self):
        return "stable", "stable"

    def environment(self, template_env, cwd):
        del cwd
        return dict(template_env)

    def metadata_fingerprint(self):
        return "stable"

    def cleanup(self) -> None:
        return None


class _SnapshotExecutor(CommandExecutor):
    def __init__(self, registry, runner) -> None:
        super().__init__(registry=registry, runner=runner)
        self.observed_tasks = []

    def _verify_source_clean(
        self,
        task,
        workspace,
        expected_fingerprint=None,
    ):
        del workspace, expected_fingerprint
        self.observed_tasks.append(task)
        return "source"

    def _verify_head(self, task, workspace) -> None:
        del workspace
        self.observed_tasks.append(task)

    def _snapshot(self, workspace):
        del workspace
        return "stable", True

    @staticmethod
    def _cwd(workspace, relative):
        del relative
        return workspace

    @staticmethod
    def _confined_argv(sandbox_root, cwd, argv, bootstrap_executable):
        del sandbox_root, cwd
        if bootstrap_executable != "/trusted/python3":
            raise AssertionError("executor did not use the pinned sandbox bootstrap")
        return argv


snapshot_runner = _MutatingRunner(snapshot_task)
snapshot_executor = _SnapshotExecutor(snapshot_registry, snapshot_runner)
with patch.object(commands_module, "_CommandSandbox", _SnapshotSandbox):
    snapshot_receipt = snapshot_executor.execute(
        snapshot_task,
        root,
        "modelrig.snapshot.probe",
    )
private_execution_task = _SnapshotSandbox.observed_task
check(
    snapshot_task.task_id == "MUTATED"
    and snapshot_task.base_sha == "b" * 40
    and private_execution_task is not None
    and private_execution_task is not snapshot_task
    and private_execution_task.canonical_json() == expected_snapshot_json
    and all(
        observed is private_execution_task
        for observed in snapshot_executor.observed_tasks
    )
    and snapshot_runner.timeout_seconds == 37
    and snapshot_runner.max_output_bytes == 4096
    and snapshot_receipt.task_id == "DC-L03-SNAPSHOT"
    and snapshot_receipt.base_sha == "a" * 40
    and snapshot_receipt.task_sha256 == expected_snapshot_sha,
    "executor sandbox, budgets, verification and receipt use one private task snapshot",
)


class _DeadlineSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []
        self.aborted = threading.Event()

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)

    def shutdown(self, how: int) -> None:
        del how
        self.aborted.set()

    def close(self) -> None:
        self.aborted.set()


class _BlockingChunkResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self) -> None:
        self.socket = _DeadlineSocket()
        self.fp = SimpleNamespace(
            raw=SimpleNamespace(_sock=self.socket)
        )
        self.closed = False

    def read1(self, amount: int) -> bytes:
        del amount
        self.socket.aborted.wait(5)
        return b""

    def close(self) -> None:
        self.closed = True
        self.socket.aborted.set()


slow_response = _BlockingChunkResponse()
body_deadline_rejected = False
started = time.monotonic()
try:
    github_read_module._read_response_body(
        slow_response,
        max_bytes=100,
        deadline=time.monotonic() + 0.05,
    )
except GitHubReadError as exc:
    body_deadline_rejected = "wall-clock deadline" in str(exc)
body_elapsed = time.monotonic() - started
check(
    body_deadline_rejected
    and body_elapsed < 0.5
    and slow_response.closed
    and slow_response.socket.aborted.is_set()
    and bool(slow_response.socket.timeouts),
    "blocking chunk framing is cancelled by the monotonic wall-clock deadline",
)


class _BlockingConnectConnection:
    def __init__(self) -> None:
        self.sock = None
        self.timeout = None
        self.auto_open = 1
        self.release_connect = threading.Event()
        self.worker_finished = threading.Event()
        self.close_count = 0
        self.requested = False

    def connect(self) -> None:
        self.release_connect.wait(5)
        self.sock = _DeadlineSocket()

    def request(self, method: str, target: str, *, headers) -> None:
        del method, target, headers
        self.requested = True

    def getresponse(self):
        raise AssertionError("getresponse must not run after setup timeout")

    def close(self) -> None:
        self.close_count += 1
        if self.sock is not None:
            self.sock.close()
        if self.close_count >= 2:
            self.worker_finished.set()


blocked_connect = _BlockingConnectConnection()
connect_deadline_rejected = False
started = time.monotonic()
try:
    github_read_module._request_with_deadline(
        blocked_connect,
        "/repos/Ternedal/ModelRig/commits/" + "a" * 40,
        headers={"Authorization": "Bearer secret"},
        max_bytes=100,
        deadline=time.monotonic() + 0.05,
    )
except GitHubReadError as exc:
    connect_deadline_rejected = "wall-clock deadline" in str(exc)
connect_elapsed = time.monotonic() - started
second_setup_rejected = False
try:
    github_read_module._request_with_deadline(
        _BlockingConnectConnection(),
        "/repos/Ternedal/ModelRig/commits/" + "a" * 40,
        headers={},
        max_bytes=100,
        deadline=time.monotonic() + 0.5,
    )
except GitHubReadError as exc:
    second_setup_rejected = "already pending" in str(exc)
blocked_connect.release_connect.set()
blocked_connect.worker_finished.wait(0.5)
check(
    connect_deadline_rejected
    and connect_elapsed < 0.5
    and second_setup_rejected
    and blocked_connect.auto_open == 0
    and not blocked_connect.requested
    and blocked_connect.worker_finished.is_set(),
    "blocked setup cannot send after timeout, reconnect, or accumulate workers",
)


class _ReconnectRaceConnection:
    def __init__(self) -> None:
        self.sock = None
        self.timeout = None
        self.auto_open = 1
        self.connect_count = 0
        self.request_entered = threading.Event()
        self.release_request = threading.Event()
        self.worker_finished = threading.Event()
        self.close_count = 0
        self.requested = False

    def connect(self) -> None:
        self.connect_count += 1
        self.sock = _DeadlineSocket()

    def request(self, method: str, target: str, *, headers) -> None:
        del method, target, headers
        self.request_entered.set()
        self.release_request.wait(5)
        if self.sock is None:
            if self.auto_open:
                self.connect()
            else:
                raise OSError("automatic reconnect disabled")
        self.requested = True

    def getresponse(self):
        raise AssertionError("getresponse must not run after request-send timeout")

    def close(self) -> None:
        self.close_count += 1
        if self.sock is not None:
            self.sock.close()
        self.sock = None
        if self.close_count >= 2:
            self.worker_finished.set()


reconnect_race = _ReconnectRaceConnection()
reconnect_result: list[Exception] = []


def run_reconnect_race() -> None:
    try:
        github_read_module._request_with_deadline(
            reconnect_race,
            "/repos/Ternedal/ModelRig/commits/" + "a" * 40,
            headers={"Authorization": "Bearer secret"},
            max_bytes=100,
            deadline=time.monotonic() + 0.05,
        )
    except Exception as exc:
        reconnect_result.append(exc)


race_caller = threading.Thread(target=run_reconnect_race)
race_caller.start()
reconnect_race.request_entered.wait(0.5)
race_caller.join(0.5)
reconnect_race.release_request.set()
reconnect_race.worker_finished.wait(0.5)
check(
    len(reconnect_result) == 1
    and isinstance(reconnect_result[0], GitHubReadError)
    and "wall-clock deadline" in str(reconnect_result[0])
    and reconnect_race.auto_open == 0
    and reconnect_race.connect_count == 1
    and not reconnect_race.requested
    and reconnect_race.worker_finished.is_set(),
    "a socket-close race cannot trigger automatic reconnect or an auth send",
)


class _BlockingHeaderConnection:
    def __init__(self) -> None:
        self.sock = _DeadlineSocket()
        self.timeout = None
        self.auto_open = 1
        self.closed = False
        self.requested = False

    def connect(self) -> None:
        return None

    def request(self, method: str, target: str, *, headers) -> None:
        self.requested = (
            self.auto_open == 0
            and method == "GET"
            and target.startswith("/")
            and isinstance(headers, dict)
        )

    def getresponse(self):
        self.sock.aborted.wait(5)
        raise OSError("connection cancelled")

    def close(self) -> None:
        self.closed = True
        self.sock.aborted.set()


header_connection = _BlockingHeaderConnection()
header_deadline_rejected = False
started = time.monotonic()
try:
    github_read_module._request_with_deadline(
        header_connection,
        "/repos/Ternedal/ModelRig/commits/" + "a" * 40,
        headers={},
        max_bytes=100,
        deadline=time.monotonic() + 0.05,
    )
except GitHubReadError as exc:
    header_deadline_rejected = "wall-clock deadline" in str(exc)
header_elapsed = time.monotonic() - started
check(
    header_deadline_rejected
    and header_elapsed < 0.5
    and header_connection.requested
    and header_connection.closed
    and header_connection.sock.aborted.is_set()
    and bool(header_connection.sock.timeouts),
    "blocking HTTP status/header framing is cancelled at the absolute deadline",
)

print(f"\n===== TEST COVERAGE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
