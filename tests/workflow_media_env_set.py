#!/usr/bin/env python3
"""scripts/media_env_set.py: set keys in the rig's env file without disturbing the rest.

#2479 review (P2): the runbook rewrote modelrig.env with ``Set-Content -Encoding ascii`` (every
non-ASCII byte lost) and backed it up under a fixed name (overwritten by the second run).

Run: python3 tests/workflow_media_env_set.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import media_env_set as tool  # noqa: E402

passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


tmp = Path(tempfile.mkdtemp())
try:
    env = tmp / "modelrig.env"
    PAIRS = ["KALIV_MEDIA_PROFILES_ENABLED=a,b,c", "KALIV_COMFY_HOST_MEMORY_GIB=40"]

    # 1. Non-ASCII content survives, in whatever encoding the file is in.
    for label, raw in (
        ("ANSI (cp1252)", "# Blåbærgrød på riggen\r\nNAVN=Søren Ærø\r\nKALIV_COMFY_HOST_MEMORY_GIB=64\r\nX=1\r\n".encode("cp1252")),
        ("UTF-8", "# Blåbærgrød på riggen\nNAVN=Søren Ærø\nKALIV_COMFY_HOST_MEMORY_GIB=64\nX=1\n".encode("utf-8")),
        ("UTF-8 with BOM", b"\xef\xbb\xbf" + "# æøå\r\nKALIV_COMFY_HOST_MEMORY_GIB=64\r\nX=1\r\n".encode("utf-8")),
        ("UTF-16 LE with BOM", b"\xff\xfe" + "# æøå €\r\nKALIV_COMFY_HOST_MEMORY_GIB=64\r\nX=1\r\n".encode("utf-16-le")),
    ):
        for old in tmp.glob("modelrig.env*"):
            old.unlink()
        env.write_bytes(raw)
        code = tool.main(["--file", str(env), *PAIRS])
        after = env.read_bytes()
        untouched = [line for line in raw.split(b"\n") if b"HOST_MEMORY" not in line.replace(b"\x00", b"")]
        check(code == 0, f"{label}: exit 0")
        check(all(line in after for line in untouched if line.strip(b"\r\x00")), f"{label}: every other line keeps its exact bytes")
        check(after[:3] == raw[:3], f"{label}: the byte-order mark (or its absence) is kept")
        codec = "utf-16" if label.startswith("UTF-16") else ("cp1252" if "ANSI" in label else "utf-8-sig")
        lines = after.decode(codec).splitlines()
        check(lines.count("KALIV_COMFY_HOST_MEMORY_GIB=40") == 1 and "KALIV_COMFY_HOST_MEMORY_GIB=64" not in lines
              and lines.count("KALIV_MEDIA_PROFILES_ENABLED=a,b,c") == 1, f"{label}: each key exactly once, with the new value")
        check("X=1" in lines and any("æ" in line or "å" in line for line in lines), f"{label}: the Danish letters are still Danish letters")
        backups = sorted(tmp.glob("modelrig.env.bak-*"))
        check(len(backups) == 1 and backups[0].read_bytes() == raw, f"{label}: one backup, byte-identical to the original")
        check(("\r\n" in after.decode(codec)) == ("\r\n" in raw.decode(codec)), f"{label}: the file's own line ending is used")

    # 2. Run again and again: the first backup is never overwritten.
    for old in tmp.glob("modelrig.env*"):
        old.unlink()
    original = "# første version æøå\r\nKALIV_COMFY_HOST_MEMORY_GIB=64\r\n".encode("cp1252")
    env.write_bytes(original)
    backup1, changed1 = tool.apply(env, tool.parse_pairs(["KALIV_COMFY_HOST_MEMORY_GIB=40"]), stamp="20261122-150000")
    second = env.read_bytes()
    backup2, changed2 = tool.apply(env, tool.parse_pairs(["KALIV_COMFY_HOST_MEMORY_GIB=48"]), stamp="20261122-150000")
    check(changed1 and changed2 and backup1 != backup2, "two runs in the same second get two backup names")
    check(backup1.read_bytes() == original, "the first backup is still the original after the second run")
    check(backup2.read_bytes() == second, "the second backup is the state before the second run")
    backup3, changed3 = tool.apply(env, tool.parse_pairs(["KALIV_COMFY_HOST_MEMORY_GIB=48"]), stamp="20261122-150000")
    check(changed3 is False and backup3 is None and len(list(tmp.glob("modelrig.env.bak-*"))) == 2,
          "asking for what the file already says changes nothing and makes no backup")
    check(not list(tmp.glob("*.tmp-*")), "no temporary file is left behind")

    # 3. Only real KEY= lines are replaced.
    env.write_bytes(b"#KALIV_X=commented\nKALIV_XY=other\n  KALIV_X=indented\nKALIV_X=1\nKALIV_X=2\nLAST=no newline")
    tool.apply(env, tool.parse_pairs(["KALIV_X=9"]), stamp="s")
    check(env.read_bytes() == b"#KALIV_X=commented\nKALIV_XY=other\nLAST=no newline\nKALIV_X=9\n",
          "a commented line and a longer key are left alone; duplicates collapse; a missing final newline is supplied")

    # 4. Refusals leave the file alone.
    env.write_bytes(original)
    for bad in (["lower=1"], ["KEY"], ["KEY=a\nb"], ["KEY=æ"], ["KEY= spaced"], ["A=1", "A=2"], ["KEY=" + "x" * 2001]):
        check(tool.main(["--file", str(env), *bad]) == 2 and env.read_bytes() == original, f"refused, file untouched: {bad[0][:20]!r}")
    check(tool.main(["--file", str(tmp / "missing.env"), "A=1"]) == 2, "a missing file is refused, not created")
    wide = tmp / "wide.env"
    wide.write_bytes("A=1\r\n".encode("utf-16-le"))
    check(tool.main(["--file", str(wide), "A=2"]) == 2 and wide.read_bytes() == "A=1\r\n".encode("utf-16-le"),
          "UTF-16 without a byte-order mark is refused rather than guessed at")
    if hasattr(os, "symlink"):
        link = tmp / "link.env"
        try:
            os.symlink(env, link)
            check(tool.main(["--file", str(link), "A=1"]) == 2, "a symlink is refused")
        except OSError:
            pass

    # 5. A failure before the swap leaves the original in place.
    env.write_bytes(original)
    real_replace = os.replace

    def boom(*_args):
        raise OSError("disk says no")
    os.replace = boom
    try:
        code = tool.main(["--file", str(env), "KALIV_COMFY_HOST_MEMORY_GIB=40"])
    finally:
        os.replace = real_replace
    check(code == 1 and env.read_bytes() == original and not list(tmp.glob("*.tmp-*")),
          "a failed swap: exit 1, original untouched, no temporary file left")

    # 5b. #2479 review (Codex P2): the env file can hold secrets. A backup or a replacement with
    # default permissions would expose what the original's permissions protected.
    if os.name != "nt":
        for old in tmp.glob("modelrig.env*"):
            old.unlink()
        previous = os.umask(0o022)
        try:
            for mode in (0o600, 0o640, 0o400):
                for old in tmp.glob("modelrig.env*"):
                    os.chmod(old, 0o600)
                    old.unlink()
                env.write_bytes(original)
                os.chmod(env, mode)
                if mode == 0o400:
                    os.chmod(env, 0o600); os.chmod(env, mode)
                backup, changed = tool.apply(env, tool.parse_pairs(["KALIV_COMFY_HOST_MEMORY_GIB=40"]), stamp="perm")
                check(changed and (os.stat(env).st_mode & 0o7777) == mode, f"mode {mode:o}: the replaced file keeps the original's mode under umask 022")
                check((os.stat(backup).st_mode & 0o7777) == mode, f"mode {mode:o}: the backup has the original's mode, not the default")
            # never wider than the original, not even for a moment: the file is created 0600 first
            seen = []
            real_open = os.open

            def watching(path, flags, mode=0o777, **kw):
                if flags & os.O_CREAT:
                    seen.append(mode)
                return real_open(path, flags, mode, **kw)
            env.unlink() if env.exists() else None
            env.write_bytes(original); os.chmod(env, 0o600)
            os.open = watching
            try:
                tool.apply(env, tool.parse_pairs(["KALIV_COMFY_HOST_MEMORY_GIB=41"]), stamp="perm2")
            finally:
                os.open = real_open
            check(seen and all(mode == 0o600 for mode in seen), "the backup and the replacement are created owner-only before they are given the original's mode")
        finally:
            os.umask(previous)

    # 6. The runbook uses the tool instead of rewriting the file from the shell.
    plan = (ROOT / "docs" / "RIGDAG_MEDIE_I_CHAT.md").read_text(encoding="utf-8")
    section = plan[plan.index("## 6. Video med lyd"):]
    section = section[:section.index("\n## ", 5)]
    check("scripts\\media_env_set.py" in section, "the sound section sets the env keys with the tool")
    check("Set-Content" not in section and "-Encoding ascii" not in section, "the sound section no longer rewrites the env file from the shell")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n===== MEDIA ENV SET: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
