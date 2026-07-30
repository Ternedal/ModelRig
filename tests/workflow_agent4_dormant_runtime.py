#!/usr/bin/env python3
"""ADR-A4-003: dvalende runtime -- ingen applikationsstyrede polling-loops.

Invarianten hed oprindeligt "ingen polling". Den formulering holdt ikke ved
maaling, og praeciseringen er selv et resultat af gennemgangen 30/07-2026:

    Paa POSIX blokerer `fcntl.flock(fd, LOCK_EX)` aegte i kernen.
    Paa Windows ser `msvcrt.locking(fd, LK_LOCK, n)` blokerende ud, men
    forsoeger internt igen hvert sekund op til ti gange. Polling forsvinder
    ikke -- den flytter ned i C-runtimen, hvor den hverken kan ses i et
    review eller maales af en gate.

Et forbud mod al ventning ville altsaa have skubbet loekken derhen hvor ingen
kunne se den. Reglen rammer derfor det, der faktisk er problemet: **loekker
vores egen kode styrer.**

  FORBUDT   `while True` (eller `while 1`) med et `sleep`-kald i kroppen
  FORBUDT   traade, timere og pools: Thread(), Timer(), .start(), daemon=
  TILLADT   kernel-blokering: fcntl.flock uden LOCK_NB
  TILLADT   platformsspecifikke OS-primitiver, fx Win32 LockFileEx
  UNDTAGELSE kraever en eksplicit arkitekturbeslutning -- ikke en kommentar

Detektionen er AST-baseret, ikke tekstsoegning: en fil maa gerne indeholde
baade en `while True` og et `sleep` hver for sig. Det er kombinationen i
SAMME loekkekrop, der er ventemekanismen.

**`worker/app/agent4/` findes ikke paa main endnu**, saa repo-scanningen
passerer tomt i dag. Derfor koeres hver detektor ogsaa mod overtraedende
proever nedenfor -- en test der kun kan bestaa, er ingen test (samme moenster
som tests/workflow_agent3_dormant.py).

Run: python3 tests/workflow_agent4_dormant_runtime.py
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT4 = ROOT / "worker" / "app" / "agent4"

_SLEEP_NAMES = frozenset({"sleep"})
_THREAD_NAMES = frozenset({"Thread", "Timer", "ThreadPoolExecutor",
                           "ProcessPoolExecutor"})

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


def _called_name(node: ast.AST) -> str | None:
    """Navnet der kaldes, uanset om det er `sleep()` eller `time.sleep()`."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_forever(test: ast.expr) -> bool:
    """`while True:` og `while 1:` -- begge former for en uendelig loekke."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    return False


def polling_loops(source: str) -> list[int]:
    """Linjenumre paa uendelige loekker der venter med sleep i kroppen."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.While) or not _is_forever(node.test):
            continue
        for inner in ast.walk(node):
            if _called_name(inner) in _SLEEP_NAMES:
                hits.append(node.lineno)
                break
    return sorted(set(hits))


def thread_starts(source: str) -> list[str]:
    """Traade, timere og pools -- uanset importform."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        name = _called_name(node)
        if name in _THREAD_NAMES:
            found.append(f"{name}()")
        elif isinstance(node, ast.Call) and name == "start":
            found.append(".start()")
        if isinstance(node, ast.keyword) and node.arg == "daemon":
            found.append("daemon=")
    return sorted(set(found))


def violations(name: str, source: str) -> list[str]:
    """ADR-A4-003 anvendt paa een modulkilde. Tom liste = i orden."""
    problems: list[str] = []
    loops = polling_loops(source)
    if loops:
        problems.append(
            f"{name}: applikationsstyret polling-loop (linje "
            f"{', '.join(str(line) for line in loops)})"
        )
    threads = thread_starts(source)
    if threads:
        problems.append(f"{name}: baggrundsudfoerelse ({', '.join(threads)})")
    return problems


# --- Del 1: detektoren virker -- proevet mod OVERTRAEDENDE kilder ----------

_POLL_LOOP = '''
"""Formen fra #267: non-blocking laas plus venteloekke."""
import time


def acquire(self, campaign_id):
    deadline = time.monotonic() + self._timeout_seconds
    while True:
        if _try_lock(self._stream):
            return lease
        if time.monotonic() >= deadline:
            raise TimeoutError
        time.sleep(self._poll_interval_seconds)
'''

_POLL_LOOP_BARE_IMPORT = '''
"""Samme fejl, importeret navn -- en gate der kun kender `time.sleep` er blind."""
from time import sleep


def wait(self):
    while 1:
        if self._ready():
            return
        sleep(0.1)
'''

_BACKGROUND_THREAD = '''
"""En baggrundstraad er ikke polling, men bryder samme invariant."""
import threading


def start(self):
    worker = threading.Thread(target=self._run, daemon=True)
    worker.start()
'''

_KERNEL_BLOCKING = '''
"""TILLADT: kernen venter, ikke vores kode."""
import fcntl


def acquire(self, stream):
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    return stream
'''

_OS_PRIMITIVE = '''
"""TILLADT: platformsspecifik OS-primitiv."""
import ctypes


def acquire(self, handle):
    ctypes.windll.kernel32.LockFileEx(
        handle, LOCKFILE_EXCLUSIVE_LOCK, 0, 1, 0, ctypes.byref(overlapped)
    )
'''

_SLEEP_WITHOUT_LOOP = '''
"""TILLADT: en fil maa indeholde baade en loekke og et sleep hver for sig."""
import time


def backoff_once(self):
    time.sleep(self._interval)


def drain(self, items):
    while True:
        item = items.pop()
        if item is None:
            return
        self._handle(item)
'''

found = violations("poll.py", _POLL_LOOP)
check(any("polling-loop" in item for item in found),
      f"detektor: #267's form (while True + time.sleep) faelder ({found})")

found = violations("poll_bare.py", _POLL_LOOP_BARE_IMPORT)
check(any("polling-loop" in item for item in found),
      "detektor: ogsaa `from time import sleep` og `while 1` fanges -- en "
      "tekstsoegning efter 'time.sleep' ville have overset begge")

found = violations("thread.py", _BACKGROUND_THREAD)
check(any("baggrundsudfoerelse" in item for item in found),
      f"detektor: baggrundstraad faelder ({found})")

check(violations("kernel.py", _KERNEL_BLOCKING) == [],
      "TILLADT: fcntl.flock uden LOCK_NB -- kernen venter, ikke vores kode")

check(violations("win32.py", _OS_PRIMITIVE) == [],
      "TILLADT: Win32 LockFileEx -- en ren OS-primitiv er at foretraekke "
      "frem for en skjult retry i C-runtimen")

check(violations("separate.py", _SLEEP_WITHOUT_LOOP) == [],
      "praecision: en loekke UDEN sleep i kroppen og et sleep uden for "
      "loekken er ikke en ventemekanisme -- ingen falsk positiv")

# --- Del 2: reglen anvendt paa repoet --------------------------------------

if not AGENT4.is_dir():
    check(True,
          "worker/app/agent4/ findes ikke paa main endnu -- scanningen "
          "passerer tomt, og gaten er armeret til den dag laget lander")
else:
    repo_problems: list[str] = []
    scanned = 0
    for path in sorted(AGENT4.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        scanned += 1
        repo_problems.extend(
            violations(
                str(path.relative_to(ROOT)),
                path.read_text(encoding="utf-8"),
            )
        )
    check(not repo_problems,
          f"ADR-A4-003 holder i worker/app/agent4/ ({scanned} moduler scannet) "
          f"{repo_problems if repo_problems else ''}")

print(f"\n===== ADR-A4-003 DORMANT RUNTIME: {PASSED} passed, "
      f"{FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
