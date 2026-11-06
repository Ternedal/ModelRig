"""Contract for worker/app/credential_file.py (step 3 of the Windows ACL design).

The shared credential reader behind the Home Assistant, RigGate and GitHub
bearer loaders. On POSIX it must accept exactly what the loaders accepted
before (regular file, bounded size, no group/other bits; symlinks followed),
but judge the open descriptor instead of the name. On Windows it delegates to
credential_acl_windows (covered by tests/worker_credential_acl_windows.py and,
for real, by tests/support/windows_credential_acl_contract.py). Anything else
refuses. The three loaders keep their existing error messages.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import app.credential_file as cf  # noqa: E402
from app.credential_file import CredentialFileRefused, read_private_credential  # noqa: E402
from app.github_connector_transport import FileGitHubCredentialProvider, GitHubCredentialError  # noqa: E402
from app.home_assistant_provider_transport import HomeAssistantTransportError  # noqa: E402
from app.home_assistant_provider_transport import _load_bearer as ha_load  # noqa: E402
from app.riggate_provider_transport import RigGateTransportError  # noqa: E402
from app.riggate_provider_transport import _load_bearer as rg_load  # noqa: E402

TOKEN = "fixture-" + "a" * 40
passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def refusal(fn, *args, **kwargs) -> str | None:
    try:
        fn(*args, **kwargs)
    except CredentialFileRefused as exc:
        return exc.kind
    return None


def error_of(fn, *args) -> tuple[type | None, str]:
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 - the type is what is checked
        return type(exc), str(exc)
    return None, ""


print("== argument and platform guards")
for bad in (0, -1, True, 1.5, 1024 * 1024 + 1):
    try:
        read_private_credential("/nonexistent", max_bytes=bad)
        check(False, f"max_bytes={bad!r} is rejected")
    except ValueError:
        check(True, f"max_bytes={bad!r} is rejected")
check(cf._reader_for("posix") is cf._read_posix, "POSIX uses the descriptor-based reader")
check(cf._reader_for("java") is None, "an unknown platform has no reader")
real_name = os.name
try:
    cf.os.name = "java"
    check(refusal(read_private_credential, "/x", max_bytes=10) == "unverifiable",
          "an unknown platform refuses as unverifiable")
finally:
    cf.os.name = real_name
try:
    CredentialFileRefused("nope")
    check(False, "an unknown refusal kind cannot be raised")
except ValueError:
    check(True, "an unknown refusal kind cannot be raised")

if os.name != "posix":
    check(True, f"os.name={os.name}: POSIX cases skipped; Windows is covered by the Windows contract")
else:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)

        def token_file(name: str, body: bytes, mode: int = 0o600) -> Path:
            path = root / name
            path.write_bytes(body)
            os.chmod(path, mode)
            return path

        good = token_file("good.token", TOKEN.encode() + b"\n")

        print("== POSIX: what was accepted before is still accepted")
        check(read_private_credential(good, max_bytes=100) == TOKEN.encode() + b"\n", "0600 file is read")
        check(read_private_credential(token_file("ro.token", TOKEN.encode(), 0o400), max_bytes=100) == TOKEN.encode(),
              "0400 file is read")
        link = root / "link.token"
        link.symlink_to(good)
        check(read_private_credential(link, max_bytes=100) == TOKEN.encode() + b"\n",
              "a symlink to a private file is still followed on POSIX (unchanged)")
        exact = token_file("exact.token", b"x" * 64)
        check(read_private_credential(exact, max_bytes=64) == b"x" * 64, "a file of exactly max_bytes is read")

        print("== POSIX: what was refused before is still refused, with the same kind")
        for mode in (0o644, 0o640, 0o604, 0o620, 0o602, 0o610):
            check(refusal(read_private_credential, token_file(f"m{mode:o}.token", TOKEN.encode(), mode),
                          max_bytes=100) == "permissions", f"mode {mode:o} refuses as permissions")
        check(refusal(read_private_credential, root / "missing.token", max_bytes=100) == "unavailable",
              "a missing file is unavailable")
        check(refusal(read_private_credential, root, max_bytes=100) == "not_regular", "a directory is not regular")
        check(refusal(read_private_credential, token_file("empty.token", b""), max_bytes=100) == "size",
              "an empty file refuses as size")
        check(refusal(read_private_credential, token_file("big.token", b"x" * 65), max_bytes=64) == "size",
              "max_bytes + 1 refuses as size")
        if os.geteuid() != 0:
            check(refusal(read_private_credential, token_file("noread.token", TOKEN.encode(), 0o000),
                          max_bytes=100) == "read", "an unreadable file refuses as read")
        else:
            check(True, "running as root: unreadable-file case skipped (root can read 0000)")

        print("== POSIX: a FIFO never blocks the loader")
        fifo = root / "pipe.token"
        os.mkfifo(fifo, 0o600)
        result: list[str | None] = []
        worker = threading.Thread(target=lambda: result.append(refusal(read_private_credential, fifo, max_bytes=100)),
                                  daemon=True)
        worker.start()
        worker.join(5)
        check(not worker.is_alive() and result == ["not_regular"], "a FIFO refuses as not_regular without blocking")
        real_stat = os.stat
        swap_fifo = root / "swap-fifo.token"
        os.mkfifo(swap_fifo, 0o600)
        cf.os.stat = lambda p, *a, **k: real_stat(good) if Path(p) == swap_fifo else real_stat(p, *a, **k)
        try:
            result = []
            worker = threading.Thread(
                target=lambda: result.append(refusal(read_private_credential, swap_fifo, max_bytes=100)), daemon=True)
            worker.start()
            worker.join(5)
            check(not worker.is_alive() and result == ["not_regular"],
                  "a FIFO swapped in after the name check is still refused on the descriptor, without blocking")
        finally:
            cf.os.stat = real_stat
        opened: list[str] = []
        real_open = os.open
        cf.os.open = lambda p, *a, **k: (opened.append(str(p)), real_open(p, *a, **k))[1]
        try:
            refusal(read_private_credential, fifo, max_bytes=100)
            check(opened == [], "a FIFO named directly is refused before it is opened")
        finally:
            cf.os.open = real_open

        print("== POSIX: the bytes read are the bytes judged (no stat/read race)")
        real_fstat = os.fstat
        swapped = token_file("swapped.token", TOKEN.encode())

        def fstat_then_chmod(fd):
            info = real_fstat(fd)
            os.chmod(swapped, 0o644)  # changes the name's mode after the descriptor was judged
            return info

        cf.os.fstat = fstat_then_chmod
        try:
            check(read_private_credential(swapped, max_bytes=100) == TOKEN.encode(),
                  "the judgment is of the open descriptor, so a later chmod cannot change what was read")
        finally:
            cf.os.fstat = real_fstat
        replaced = token_file("replaced.token", TOKEN.encode())
        other = token_file("other.token", b"y" * 10, 0o644)

        def fstat_then_replace(fd):
            info = real_fstat(fd)
            os.replace(other, replaced)  # the name now points at a world-readable file
            return info

        cf.os.fstat = fstat_then_replace
        try:
            check(read_private_credential(replaced, max_bytes=100) == TOKEN.encode(),
                  "a rename after the open still reads the file that was opened and judged")
        finally:
            cf.os.fstat = real_fstat

        print("== the three loaders keep their messages")
        broad = token_file("broad.token", TOKEN.encode() + b"\n", 0o644)
        cases = (
            ("Home Assistant", ha_load, HomeAssistantTransportError),
            ("RigGate", rg_load, RigGateTransportError),
        )
        for name, load, error in cases:
            check(load(good) == TOKEN, f"{name}: a private token loads")
            kind, text = error_of(load, broad)
            check(kind is error and text == f"{name} credential file permissions are too broad",
                  f"{name}: 0644 keeps its message")
            kind, text = error_of(load, root / "missing.token")
            check(kind is error and text == f"{name} credential file is unavailable", f"{name}: missing keeps its message")
            kind, text = error_of(load, root)
            check(kind is error and text == f"{name} credential path must be a regular file",
                  f"{name}: directory keeps its message")
            kind, text = error_of(load, token_file(f"{name[:2]}-big.token", b"x" * 4099))
            check(kind is error and text == f"{name} credential file size is invalid", f"{name}: oversize keeps its message")
        github = FileGitHubCredentialProvider(account="Ternedal", token_file=good)
        check(github.bearer_token() == TOKEN, "GitHub: a private token loads")
        kind, text = error_of(FileGitHubCredentialProvider(account="Ternedal", token_file=broad).bearer_token)
        check(kind is GitHubCredentialError and text == "GitHub credential file permissions are too broad",
              "GitHub: 0644 keeps its message")
        kind, text = error_of(FileGitHubCredentialProvider(account="Ternedal", token_file=root).bearer_token)
        check(kind is GitHubCredentialError and text == "GitHub credential path is not a regular file",
              "GitHub: directory keeps its message")
        kind, text = error_of(
            FileGitHubCredentialProvider(account="Ternedal", token_file=token_file("gh-big.token", b"x" * 4097)).bearer_token)
        check(kind is GitHubCredentialError and text == "GitHub credential file size is invalid",
              "GitHub: oversize keeps its message")

        print("== a refusal never carries the secret")
        real_read = cf.os.read
        cf.os.read = lambda fd, n: (_ for _ in ()).throw(OSError(5, "I/O error"))
        try:
            try:
                ha_load(good)
                check(False, "a read failure refuses")
            except HomeAssistantTransportError as exc:
                check(str(exc) == "Home Assistant credential file could not be read" and exc.__cause__ is None
                      and TOKEN not in repr(exc), "a read failure refuses with the old message and no chained detail")
        finally:
            cf.os.read = real_read

print(f"\n===== CREDENTIAL FILE (shared loader rule): {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
