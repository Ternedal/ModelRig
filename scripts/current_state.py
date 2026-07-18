#!/usr/bin/env python3
"""Generate CURRENT_STATE.md from the repo -- never by hand.

F-209: the authoritative docs disagreed with each other and with main. The
root cause is not laziness, it is the design: README promised that "STATUS.md
line 3 is always the current one-liner", which required every session to
remember. Line 3 spent 55 releases claiming 1.58.2. A convention that depends
on memory is a convention that is already dead; it just has not been noticed.

So this file is derived from the things that cannot lie -- VERSION, the tool
registry, the env switches in the source, the test glob -- and CI regenerates
it and fails if the committed copy differs (tests/workflow_current_state.py).
Drift becomes a red build instead of a wrong answer six weeks later.

Deliberately NO dates and no prose-by-hand: a timestamp would make the check
fail every midnight, and a hand-written sentence is exactly the thing that
rots. If a fact belongs here, teach the generator to read it.

Run: python3 scripts/current_state.py [--check]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "CURRENT_STATE.md"


def _tools() -> list[tuple[str, str, str]]:
    """Ask the registry itself. A doc that lists tools by hand lists them wrong."""
    tmp = tempfile.mkdtemp(prefix="kaliv-state-")
    env = dict(os.environ)
    env.update({
        "KALIV_AUDIT_DB": os.path.join(tmp, "a.db"),
        "KALIV_TOOLS_STATE": os.path.join(tmp, "s.json"),
        "KALIV_JOBS_DB": os.path.join(tmp, "j.db"),
        "KALIV_TOOLS_DIR": tmp,
        "PYTHONPATH": str(ROOT / "worker"),
    })
    # Emit every axis the registry owns (F-718). The page showed risk,
    # sensitivity and isolation, and hid impact, schedulable, cancellation and
    # idempotent -- so the authoritative state could not say what may run
    # unattended or be replayed, which is the whole point of those axes.
    #
    # The axis names live in ONE list, in the subprocess and in the header
    # below, because hand-listing fields in two places is how retry dropped
    # idempotent this morning (F-715). Add an axis to _AXES and both ends learn
    # it.
    code = (
        "from app.tools import REGISTRY\n"
        "_AXES = ('risk','sensitivity','isolate','impact','schedulable',"
        "'cancellation','idempotent')\n"
        "def _cell(v):\n"
        "    if isinstance(v, bool): return '1' if v else '0'\n"
        "    return str(getattr(v, 'value', v))\n"
        "for n, t in sorted(REGISTRY.items()):\n"
        "    print(n + '|' + '|'.join(_cell(getattr(t, a)) for a in _AXES))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=env, cwd=str(ROOT / "worker"), timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"cannot read the tool registry:\n{out.stderr[-800:]}")
    rows = []
    for line in out.stdout.strip().splitlines():
        parts = line.split("|")
        name, rest = parts[0], parts[1:]
        rows.append((name, rest))
    return rows


def _switches() -> list[tuple[str, str]]:
    """Every env switch this SYSTEM reads, with its default.

    It used to say "the worker" and scan worker/**/*.py, which meant
    KALIV_SCHEDULER_API -- the Go switch deciding whether the schedule admin
    surface is reachable remotely at all -- was absent from the page whose
    promise is that it cannot be wrong (F-613). The system is Go and Python; a
    scan of one language's directory measures my search path, not the system.
    """
    found: dict[str, str] = {}
    pat = re.compile(r'getenv\(\s*"(KALIV_[A-Z0-9_]+)"\s*(?:,\s*"([^"]*)")?')
    for py in sorted((ROOT / "worker").rglob("*.py")):
        for m in pat.finditer(py.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(m.group(1), m.group(2) if m.group(2) is not None else "(unset)")
    # os.Getenv("X") == "1" is unambiguous: off unless someone sets it to 1.
    # Only that pattern is listed -- a key or a path read from the Go
    # environment is a setting, and padding a switch table with settings is how
    # a table stops being read.
    go = re.compile(r'os\.Getenv\(\s*"((?:KALIV|MODELRIG)_[A-Z0-9_]+)"\s*\)\s*==\s*"1"')
    for src in sorted((ROOT / "backend").rglob("*.go")):
        if src.name.endswith("_test.go"):
            continue
        for m in go.finditer(src.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(m.group(1), "0")
    return sorted(found.items())


def _desktop_credentials() -> list[tuple[str, str]]:
    """Read the desktop credential contract from implementation and CI.

    This deliberately does not trust SECURITY.md. If encryption, migration or
    the Windows proof disappears from code, CURRENT_STATE changes and the
    generated-file gate goes red.
    """
    data_dir = ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin" / \
        "dk" / "ternedal" / "modelrig" / "desktop" / "data"
    db = (data_dir / "DesktopChatDb.kt").read_text(encoding="utf-8", errors="replace")
    protector = (data_dir / "CredentialProtector.kt").read_text(encoding="utf-8", errors="replace")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8", errors="replace")

    keys = re.search(r'CREDENTIAL_SETTING_KEYS\s*=\s*setOf\(([^)]*)\)', db)
    key_names = sorted(re.findall(r'"([^"]+)"', keys.group(1))) if keys else []
    dpapi = (
        "WindowsDpapiCredentialProtector" in db
        and "Crypt32Util.cryptProtectData" in protector
        and "Crypt32Util.cryptUnprotectData" in protector
        and "CRYPTPROTECT_UI_FORBIDDEN" in protector
    )
    migration = "putRawSetting(key, protectCredential(raw))" in db
    fail_closed = (
        "CREDENTIAL_ENVELOPE_FAMILY_PREFIX" in db
        and "Unsupported desktop credential envelope" in db
        and "Credential protector returned an invalid envelope" in db
    )
    windows_proof = (
        "desktop-dpapi-windows:" in ci
        and "WindowsDpapiCredentialProtectorTest.kt" in " ".join(
            p.name for p in (ROOT / "desktop" / "composeApp" / "src" / "test").rglob("*.kt")
        )
    )

    return [
        ("Beskyttede settings", ", ".join(f"`{name}`" for name in key_names) or "ingen"),
        ("At-rest-beskyttelse", "Windows DPAPI (current-user)" if dpapi else "INGEN"),
        ("Legacy-klartekst migreres før udlevering", "ja" if migration else "nej"),
        ("Korrupt/ukendt envelope fejler lukket", "ja" if fail_closed else "nej"),
        ("Ægte DPAPI bevist på Windows-runner", "ja" if windows_proof else "nej"),
    ]


def _suites() -> list[str]:
    return sorted(p.name for p in (ROOT / "tests").glob("*.py"))


def _designs() -> list[tuple[str, str]]:
    """Design docs and the STATUS line each one declares about itself."""
    rows = []
    for p in sorted(ROOT.glob("*.md")):
        if not (p.name.endswith("_DESIGN.md") or p.name.startswith("VALIDATION-")):
            continue
        status = "(no status header)"
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
            if line.startswith("**Status:**"):
                status = line[len("**Status:**"):].strip()
                break
        rows.append((p.name, status))
    return rows


def render() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    L: list[str] = []
    L.append("# CURRENT_STATE.md")
    L.append("")
    L.append("> **GENERATED — do not edit.** `python3 scripts/current_state.py`")
    L.append("> regenerates this; CI fails if the committed copy has drifted")
    L.append("> (`tests/workflow_current_state.py`). Everything here is read out of the")
    L.append("> code, so it cannot quietly become untrue. If a fact belongs here, teach")
    L.append("> the generator to read it -- do not type it in.")
    L.append("")
    L.append(f"**Version:** {version}")
    L.append("")
    L.append("## Tools the model can see")
    L.append("")
    L.append("Every column is a registry-owned axis (F-718). `risk` gates what a tool")
    L.append("may DO and `impact` how bad it is if it goes wrong; `sensitivity` gates")
    L.append("where its ANSWER may travel; `sched` is whether it may run unattended;")
    L.append("`stop` is what cancellation does; `replay` is whether running it twice is")
    L.append("safe. Read out of the code, so the page cannot claim one thing while the")
    L.append("gate enforces another.")
    L.append("")
    # Same axis order as the subprocess. One list, two ends (F-715): the header
    # and the emitter must not drift, so they share the order by construction.
    L.append("| Tool | risk | impact | sensitivity | isolated | sched | stop | replay |")
    L.append("|---|---|---|---|---|---|---|---|")
    for name, axes in _tools():
        risk, sens, iso, impact, sched, stop, replay = axes
        L.append(
            f"| `{name}` | {risk} | {impact} | {sens} | "
            f"{'yes' if iso == '1' else 'no'} | "
            f"{'yes' if sched == '1' else 'no'} | {stop} | "
            f"{'yes' if replay == '1' else 'no'} |"
        )
    L.append("")
    L.append("## Switches (default = what a rig does today)")
    L.append("")
    L.append("| Env | Default |")
    L.append("|---|---|")
    for k, v in _switches():
        L.append(f"| `{k}` | `{v}` |")
    L.append("")
    L.append("## Desktop credential storage")
    L.append("")
    L.append("| Property | Current implementation |")
    L.append("|---|---|")
    for name, value in _desktop_credentials():
        L.append(f"| {name} | {value} |")
    L.append("")
    L.append("## Design docs and what they claim about themselves")
    L.append("")
    L.append("| Doc | Status |")
    L.append("|---|---|")
    for name, status in _designs():
        L.append(f"| `{name}` | {status} |")
    L.append("")
    L.append("## Test suites in CI")
    L.append("")
    L.append("Run by glob, so a file that matches is a file that runs")
    L.append("(`tests/workflow_test_coverage.py` proves none can hide).")
    L.append("")
    for name in _suites():
        L.append(f"- `tests/{name}`")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("CURRENT_STATE.md is stale. Run: python3 scripts/current_state.py")
            raise SystemExit(1)
        print("CURRENT_STATE.md is current")
        raise SystemExit(0)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
