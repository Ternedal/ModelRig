#!/usr/bin/env python3
"""Generate ACTIVATION_READINESS.md -- the one page that answers "can this be
switched on right now, and if not, what exactly is missing".

Written because the documents that answer that question had all drifted at once
(analysis F-306): ROADMAP described a pre-Agent-3 repo, HANDOFF said 1.58.52
while main was 60 releases past it, the Agent 3 document listed delivered
features as missing, and the validation instructions pointed at a branch that
had already merged. Every one of those was written by someone who believed it
when they wrote it. That is the whole problem with prose about state.

Doc drift is cosmetic when it describes a feature. It is a safety failure when
it describes READINESS, because that is the document a person reads at the exact
moment they decide to flip a flag that lets software act on its own.

So this file computes the answer instead of remembering it. It fails closed: no
validation report means NOT READY, not "probably fine". Nothing here is a
promise -- every line is read from the code, the flags, or the report on disk.

Run: python3 scripts/activation_readiness.py [--check]
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ACTIVATION_READINESS.md"
REPORT_ENV = "KALIV_AGENT3_VALIDATION_REPORT"


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def flag_defaults() -> list[tuple[str, str, str]]:
    """Every KALIV_* switch the worker reads, and what it does when unset.

    Read from the source, because a flag list maintained by hand is a flag list
    that is wrong the first time someone adds a flag in a hurry.
    """
    pat = re.compile(r'os\.getenv\(\s*"(KALIV_[A-Z0-9_]+)"\s*(?:,\s*("[^"]*"|\'[^\']*\'))?')
    found: dict[str, str] = {}
    for py in sorted((ROOT / "worker").rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        for m in pat.finditer(py.read_text(encoding="utf-8", errors="replace")):
            name, default = m.group(1), m.group(2)
            found.setdefault(name, (default or "(unset)").strip("\"'"))
    # A switch and a setting are not the same thing, and calling a 10-second
    # cache TTL an "ACTIVE switch" is how a readiness page teaches you to skim
    # it. Only booleans can be on; a number is a value, not a decision.
    BOOLISH = {"", "0", "1", "true", "false", "on", "off", "(unset)"}
    rows = []
    for name, default in sorted(found.items()):
        if default not in BOOLISH:
            kind = "indstilling"
        elif default in ("1", "true", "on"):
            kind = "**AKTIV**"
        else:
            kind = "slukket"
        rows.append((name, default or "(tom)", kind))
    return rows


def validation() -> dict:
    """The on-rig report, assessed by the gate that already knows the rules.

    Absent is the normal case and the honest one: this repo has never had a
    physical validation run recorded for the version on main.
    """
    import os

    sys.path.insert(0, str(ROOT / "worker"))
    from app.agent3.validation_gate import assess_report  # noqa: PLC0415

    # Relative, because an absolute path bakes THIS machine into a file that is
    # committed and compared byte-for-byte on someone else's.
    path = os.getenv(REPORT_ENV) or "agent3-validation-latest.json"
    p = Path(path) if Path(path).is_absolute() else (ROOT / path)
    if not p.exists():
        return {"present": False, "path": path, "ready": False,
                "reason": "ingen rapport på disken — fysisk validering er ikke kørt"}
    raw = p.read_bytes()
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"present": True, "path": path, "ready": False,
                "reason": f"rapporten kan ikke læses: {e}"}
    a = assess_report(report, current_version=version(),
                      report_sha256=hashlib.sha256(raw).hexdigest())
    a["present"] = True
    a["path"] = path
    a["ready"] = bool(a.get("ready") or a.get("promotable"))
    return a


def dormancy() -> tuple[bool, str]:
    """Run the CI gate that proves Agent 3 is asleep, and report what it said."""
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "workflow_agent3_dormant.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    tail = [ln for ln in r.stdout.splitlines() if "=====" in ln]
    return r.returncode == 0, (tail[-1].strip() if tail else "no output")


def render() -> str:
    v = version()
    val = validation()
    dormant_ok, dormant_line = dormancy()
    flags = flag_defaults()
    switches = [f for f in flags if f[2] != "indstilling"]
    active = [f for f in switches if f[2] == "**AKTIV**"]

    blockers: list[str] = []
    if not val["ready"]:
        blockers.append(
            f"**Fysisk rig-validering:** {val.get('reason') or 'rapporten er ikke godkendt'}"
        )
    if not dormant_ok:
        blockers.append("**Dormans-gaten fejler** — koden er ikke i den tilstand den påstår")

    verdict = "NEJ" if blockers else "JA"

    lines = [
        "# Aktiverings-readiness",
        "",
        "> **Genereret af `scripts/activation_readiness.py`. Ret ikke i hånden.**",
        "> Den her side findes fordi de dokumenter der plejede at svare på "
        "spørgsmålet alle var driftet på én gang, og det er den side et menneske "
        "læser i præcis det øjeblik hvor de beslutter at give software lov til at "
        "handle selv. Den fejler lukket: ingen rapport = ikke klar.",
        "",
        f"**Version på main:** `{v}`  ",
        f"**Genereret:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "---",
        "",
        f"## Kan Agent 3 aktiveres nu? **{verdict}**",
        "",
    ]

    if blockers:
        lines.append("Blokerende:")
        lines.append("")
        for b in blockers:
            lines.append(f"- {b}")
        lines += [
            "",
            "Indtil ovenstående er lukket, er `KALIV_AGENT3_ENABLED=1` en beslutning "
            "truffet uden evidens. Koden kan være korrekt i tests og fejle på "
            "Windows, Ollama, Tailscale eller en Pixel 6a — det er dét fysisk "
            "validering er til for, og det er ikke noget CI kan gøre for dig.",
        ]
    else:
        lines.append("Ingen blokerende fund. Evidensen nedenfor er frisk og "
                     "version-bundet til denne main.")

    lines += [
        "",
        "---",
        "",
        "## Fysisk validering",
        "",
        f"- **Rapport til stede:** {'ja' if val.get('present') else 'NEJ'}",
        f"- **Sti:** `{val.get('path')}`",
    ]
    if val.get("present"):
        lines += [
            f"- **Valideret version:** `{val.get('validated_version')}` "
            f"(main er `{v}`)",
            f"- **Version matcher:** {'ja' if val.get('version_match') else 'NEJ'}",
            f"- **Rapport-SHA256:** `{(val.get('report_sha256') or '')[:16]}…`",
        ]
        if val.get("blockers"):
            lines.append(f"- **Gatens blockers:** {', '.join(val['blockers'])}")
    else:
        lines.append(f"- **Hvorfor ikke klar:** {val.get('reason')}")
    lines += [
        "",
        f"Sæt `{REPORT_ENV}` hvis rapporten ligger et andet sted.",
        "",
        "---",
        "",
        "## Dormans",
        "",
        f"- **CI-gaten siger:** `{dormant_line}`",
        f"- **Status:** {'Agent 3 sover' if dormant_ok else 'GATEN FEJLER'}",
        "",
        "---",
        "",
        "## Switches (læst fra koden, ikke fra hukommelsen)",
        "",
        f"**{len(active)} af {len(switches)} feature-switches er tændt som default.** "
        f"({len(flags) - len(switches)} af posterne nedenfor er indstillinger — "
        "tal og stier, ikke beslutninger.)",
        "",
        "| Switch | Default | Tilstand |",
        "|---|---|---|",
    ]
    for name, default, state in flags:
        lines.append(f"| `{name}` | `{default}` | {state} |")

    lines += [
        "",
        "---",
        "",
        "*En readiness-side der skrives i hånden er forkert første gang nogen har "
        "travlt. Derfor regner den her side svaret ud.*",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists():
            print("ACTIVATION_READINESS.md mangler — kør scripts/activation_readiness.py")
            return 1
        cur = OUT.read_text(encoding="utf-8")
        # The timestamp is expected to move; nothing else may.
        strip = lambda s: re.sub(r"\*\*Genereret:\*\*.*", "", s)  # noqa: E731
        if strip(cur) != strip(text):
            print("ACTIVATION_READINESS.md er driftet fra koden — kør generatoren")
            return 1
        print("ACTIVATION_READINESS.md matcher koden")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"skrev {OUT.relative_to(ROOT)} ({len(text.splitlines())} linjer)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
