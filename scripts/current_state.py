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


def _tools() -> list[tuple[str, list[str]]]:
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
        "from app.capability_schema import descriptors_from_registry\n"
        "from app.tools import REGISTRY\n"
        "def _cell(v):\n"
        "    if isinstance(v, bool): return '1' if v else '0'\n"
        "    return str(getattr(v, 'value', v))\n"
        "for d in descriptors_from_registry(REGISTRY):\n"
        "    values = (d.schema_id, d.access, d.impact, d.data_class, "
        "d.isolation.mode == 'process', d.scheduling.allowed, d.network.mode, "
        "d.termination.mode, d.replay.idempotent)\n"
        "    print(d.capability_id + '|' + '|'.join(_cell(v) for v in values))\n"
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

    Python configuration may be read directly from os.environ or from an
    injected Mapping in deterministic evaluators. Both are implementation, and
    hiding the latter would make a testable readiness switch invisible here.
    """
    found: dict[str, str] = {}
    python_patterns = (
        re.compile(r'getenv\(\s*"(KALIV_[A-Z0-9_]+)"\s*(?:,\s*"([^"]*)")?'),
        re.compile(
            r'\b(?:env|environ)\.get\(\s*"(KALIV_[A-Z0-9_]+)"'
            r'\s*(?:,\s*"([^"]*)")?'
        ),
    )
    for py in sorted((ROOT / "worker").rglob("*.py")):
        text = py.read_text(encoding="utf-8", errors="replace")
        for pattern in python_patterns:
            for m in pattern.finditer(text):
                found.setdefault(
                    m.group(1),
                    m.group(2) if m.group(2) is not None else "(unset)",
                )
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
    # A test that is DEFINED and wired into CI is not a test that PASSED on this
    # commit (F-813). This generator runs offline -- it reads the filesystem, not
    # the GitHub status API -- so it can see the job in the workflow and the test
    # file on disk, and it cannot see whether the run went green on the current
    # head. Claiming "bevist" (proven) from a job name and a filename is the same
    # overclaim as a readiness page attesting to the door it happened to read: a
    # workflow can fail or never run, and the page would still say proven.
    #
    # So report what is actually true. The test is defined and wired; whether it
    # passed on THIS commit is a CI-status question the offline generator cannot
    # answer, and the honest page says so rather than asserting the stronger
    # claim it cannot support.
    dpapi_test_defined = (
        "desktop-dpapi-windows:" in ci
        and "runs-on: windows-latest" in ci
        and "WindowsDpapiCredentialProtectorTest.kt" in " ".join(
            p.name for p in (ROOT / "desktop" / "composeApp" / "src" / "test").rglob("*.kt")
        )
    )

    return [
        ("Beskyttede settings", ", ".join(f"`{name}`" for name in key_names) or "ingen"),
        ("At-rest-beskyttelse", "Windows DPAPI (current-user)" if dpapi else "INGEN"),
        ("Legacy-klartekst migreres før udlevering", "ja" if migration else "nej"),
        ("Korrupt/ukendt envelope fejler lukket", "ja" if fail_closed else "nej"),
        # Two separate claims, because they are two separate facts and conflating
        # them is F-813. "Defined" is filesystem-checkable and true; "passed on
        # this head" needs the CI status this offline generator does not have.
        ("DPAPI-test defineret og koblet i CI (windows-latest)",
         "ja" if dpapi_test_defined else "nej"),
        ("Bestået på denne commit",
         "kan ikke verificeres offline — se CI-status for headen"),
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
    L.append("Every row is generated from the strict `kaliv-capability/v2` descriptor,")
    L.append("not from a parallel documentation projection. `access` gates what a tool")
    L.append("may do; `impact` describes the consequence; `data class` governs where")
    L.append("results may travel; scheduling, network, termination and replay semantics")
    L.append("are the same versioned values validated by worker, backend and clients.")
    L.append("")
    L.append("| Capability | schema | access | impact | data class | isolated | sched | network | stop | replay |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for capability_id, axes in _tools():
        schema, access, impact, data_class, iso, sched, network, stop, replay = axes
        L.append(
            f"| `{capability_id}` | `{schema}` | {access} | {impact} | {data_class} | "
            f"{'yes' if iso == '1' else 'no'} | "
            f"{'yes' if sched == '1' else 'no'} | {network} | {stop} | "
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
