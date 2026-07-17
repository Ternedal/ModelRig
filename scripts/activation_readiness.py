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
import inspect
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from agent3_validation_paths import DEFAULT_REPORT_TEXT

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
    from app.build_identity import code_fingerprint  # noqa: PLC0415
    from app.agent3.validation_gate import assess_report  # noqa: PLC0415

    # Relative, because an absolute path bakes THIS machine into a file that is
    # committed and compared byte-for-byte on someone else's.
    path = os.getenv(REPORT_ENV) or DEFAULT_REPORT_TEXT
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
    # THE comparison that matters (F-508). The collector compares the rig to
    # itself, which is theatre by construction. Here the question is real and
    # can answer no: did the evidence describe the software we are about to
    # switch on? A report from a rig running different code is not stale
    # evidence, it is evidence about something else.
    a = assess_report(report, current_version=version(),
                      current_code=code_fingerprint(),
                      report_sha256=hashlib.sha256(raw).hexdigest())
    a["present"] = True
    a["path"] = path
    a["ready"] = bool(a.get("ready") or a.get("promotable"))
    return a


def plan_authority() -> tuple[bool, str]:
    """Prove production run creation cannot accept a client-authored plan."""
    try:
        sys.path.insert(0, str(ROOT / "worker"))
        from app.agent3.api import StartReq, build_router  # noqa: PLC0415
        from app.agent3.planner import build_planner_router  # noqa: PLC0415, F401

        client_plan = "plan" in getattr(StartReq, "model_fields", {})
        fixture_default = inspect.signature(build_router).parameters[
            "allow_client_plans"
        ].default
        if client_plan:
            return False, "run-requesten accepterer stadig en plan fra klienten"
        if fixture_default is not False:
            return False, "test-fixturen for klientplaner er aktiv som standard"
        return True, (
            "planen bygges og gemmes på serveren; klienten kan kun starte den "
            "via et kortlivet single-use plan-id, mens retry kloner den gemte plan"
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"kunne ikke læse plan-autoriteten: {exc}"

def schedule_approval_authority() -> tuple[bool, str]:
    """Does a scheduled write's approval prove a human, or just knowledge? (F-503/F-504)

    The scheduler's whole premise is that Anders approves a standing grant ONCE,
    at creation, and the tool gate later honours it without a card because there
    is nobody awake at 03:00 to show one to. That trade is only sound if the
    approval is evidence that a human decided.

    It is not. The approval travelling to the gate is fingerprint(tool, args) --
    a SHA-256 of two things the caller already knows. It is not a secret, it is
    not issued by anything, and it can be computed in one line by any process
    that can reach loopback. /schedules is loopback-checked and holds no token,
    so "Anders approved this write" currently means "someone knew the tool name
    and the arguments".

    Latent today: none of the nine tools can make a local HTTP request, so
    nothing on the rig can walk through this door. It becomes live the day a
    shell, http, MCP or file-with-network tool lands -- which is exactly the day
    a prompt-injected model would find it. Same shape as a desktop action
    classified as a READ: harmless until the capability it waits for arrives.

    Deliberately computed here rather than patched in the API: Anders owns
    schedule_api.py and is building the human control surface right now, and the
    real fix -- server-issued, single-use, expiring tokens bound to a UI
    confirmation behind an authenticated operator session -- belongs with that
    work, not bolted on underneath it by someone else at the same time.
    """
    try:
        sys.path.insert(0, str(ROOT / "worker"))
        from app.schedule_api import CreateScheduleReq  # noqa: PLC0415

        fields = getattr(CreateScheduleReq, "model_fields", {})
        if "approved_fingerprint" not in fields:
            return True, "godkendelsen kommer ikke fra klienten"

        src = (ROOT / "worker" / "app" / "schedule_api.py").read_text(encoding="utf-8")
        has_auth = any(t in src for t in ("Bearer", "Depends(", "operator_session",
                                          "approval_token", "consume_approval"))
        if has_auth:
            return True, "schedule-administration kræver mere end loopback"
        return False, (
            "**En planlagt skrivnings godkendelse beviser kendskab, ikke samtykke.** "
            "`approved_fingerprint` er `sha256(tool + args)` — ikke en hemmelighed, "
            "ikke udstedt af noget, beregnelig på én linje af enhver proces der kan "
            "nå loopback. `/schedules` har ingen token. Latent i dag, fordi ingen af "
            "de ni tools kan lave et lokalt HTTP-kald — live den dag et shell-, "
            "http-, MCP- eller filværktøj med netværk lander, hvilket er præcis den "
            "dag en prompt-injiceret model ville finde døren. Kræver serverudstedte, "
            "engangs, kortlivede tokens bundet til en faktisk UI-bekræftelse"
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"kunne ikke læse schedule-godkendelsen: {exc}"


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
    server_plans, plan_note = plan_authority()
    approval_ok, approval_note = schedule_approval_authority()
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
    if not server_plans:
        blockers.append(plan_note)


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
        f"## Kan scheduleren aktiveres nu? **{'NEJ' if not approval_ok else verdict}**",
        "",
        # A separate verdict on purpose. The scheduler and Agent 3 fail for
        # different reasons, and a page that pools their blockers tells a reader
        # that Agent 3 is held up by something that has nothing to do with it --
        # which is how a page earns the right to be skimmed.
        (approval_note if not approval_ok
         else "Ingen blokerende fund specifikke for scheduleren."),
        "",
        f"- **Beviser en godkendelse et menneske:** {'ja' if approval_ok else 'NEJ'}",
        "- **Fysisk validering gælder også her:** scheduleren kører på den samme "
        "rig, så rapporten er en forudsætning for begge.",
        "",
        "---",
        "",
        "## Planautoritet (Agent 3)",
        "",
        f"- **Serverbygget plan:** {'ja' if server_plans else 'NEJ'}",
        f"- **Detalje:** {plan_note}",
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
