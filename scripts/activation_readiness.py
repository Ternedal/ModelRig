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
import logging
import os
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
    # The Go backend is part of this system too (F-613). Scanning only
    # worker/**/*.py meant KALIV_SCHEDULER_API -- the switch that decides whether
    # the schedule admin surface is reachable REMOTELY at all -- appeared nowhere
    # on the page whose whole promise is that it cannot be wrong. A page that
    # says "0 of 12 switches are on" after reading one language's directory is
    # not measuring the system; it is measuring my search path. Same mistake as
    # the entrypoint scan that only walked the folders I thought of.
    #
    # `os.Getenv("X") == "1"` is unambiguous: off unless someone sets it to 1.
    # Anything else read from the Go environment is a setting, not a decision,
    # and is reported as such rather than guessed at.
    go_switches: set[str] = set()
    go_settings: set[str] = set()
    go_switch = re.compile(r'os\.Getenv\(\s*"((?:KALIV|MODELRIG)_[A-Z0-9_]+)"\s*\)\s*==\s*"1"')
    go_any = re.compile(r'os\.Getenv\(\s*"((?:KALIV|MODELRIG)_[A-Z0-9_]+)"\s*\)')
    for go in sorted((ROOT / "backend").rglob("*.go")):
        if go.name.endswith("_test.go"):
            continue
        text = go.read_text(encoding="utf-8", errors="replace")
        for m in go_switch.finditer(text):
            found.setdefault(m.group(1), "0")
            go_switches.add(m.group(1))
        for m in go_any.finditer(text):
            # A key, a path or a claim limit read from the environment is a
            # SETTING. Widening the scan made eight of them appear as "switches
            # that are off", which dilutes the count the page exists to state --
            # the same way calling a cache TTL an ACTIVE switch would. Only the
            # ones whose code says == "1" get to be decisions.
            if m.group(1) not in go_switches:
                found.setdefault(m.group(1), "(unset)")
                go_settings.add(m.group(1))

    # A switch and a setting are not the same thing, and calling a 10-second
    # cache TTL an "ACTIVE switch" is how a readiness page teaches you to skim
    # it. Only booleans can be on; a number is a value, not a decision.
    BOOLISH = {"", "0", "1", "true", "false", "on", "off", "(unset)"}
    rows = []
    for name, default in sorted(found.items()):
        if name in go_settings:
            kind = "indstilling"
        elif default not in BOOLISH:
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


def _try_to_mint_a_standing_grant() -> bool | None:
    """Try the loopback bypass against a worker that has only a public key.

    True means an unauthenticated local caller minted a standing write. False
    means a forged token was refused, a real backend-signed token worked once,
    and replay was refused. None means the probe itself could not establish the
    contract, which remains a blocker rather than a guessed pass.
    """
    import base64  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    try:
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415
        from fastapi import FastAPI  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from app.schedule_admin import (  # noqa: PLC0415
            APPROVAL_TOKEN_AUDIENCE,
            APPROVAL_TOKEN_PREFIX,
            APPROVAL_TOKEN_VERSION,
            ScheduleAdmin,
            ScheduleAdminStore,
        )
        from app.schedule_api import build_schedule_router  # noqa: PLC0415

        tmp = tempfile.mkdtemp()
        os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(tmp, "a.db"))
        os.environ.setdefault("KALIV_TOOLS_STATE", os.path.join(tmp, "st.json"))
        os.environ.setdefault("KALIV_TOOLS_DIR", tmp)
        db = os.path.join(tmp, "s.db")
        now = 1_900_000_000.0
        legitimate = Ed25519PrivateKey.generate()
        public = legitimate.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        class ProbeTool:
            risk = "write"
            sensitivity = "private"
            schedulable = True
            params = {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            }

            @staticmethod
            def human_summary(args):
                return "append note: " + str(args.get("text", ""))

        admin = ScheduleAdmin(
            store_factory=lambda: ScheduleAdminStore(db),
            registry_factory=lambda: {"note_append": ProbeTool()},
            clock=lambda: now,
            approval_public_key=base64.b64encode(public).decode("ascii"),
        )
        app = FastAPI()
        app.include_router(build_schedule_router(admin))
        client = TestClient(app, client=("127.0.0.1", 51234))

        body = {"tool": "note_append", "args": {"text": "probe"},
                "cadence": "daily:03:00"}
        pv = client.post("/schedules/preview", json=body)
        if pv.status_code != 200:
            return None
        binding = (pv.json().get("preview") or {}).get("approval_binding")
        if not isinstance(binding, str):
            return None

        def token(key, nonce):
            claims = {"v": APPROVAL_TOKEN_VERSION,
                      "aud": APPROVAL_TOKEN_AUDIENCE,
                      "binding": binding, "exp": int(now + 300),
                      "nonce": nonce}
            raw = json.dumps(claims, separators=(",", ":")).encode()
            enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
            return f"{APPROVAL_TOKEN_PREFIX}.{enc(raw)}.{enc(key.sign(raw))}"

        forged = token(Ed25519PrivateKey.generate(), "forged-readiness-012345")
        refused = client.post("/schedules", json={**body, "approval_token": forged})
        if refused.status_code in (200, 201):
            return True
        if refused.status_code != 409:
            return None

        valid = token(legitimate, "valid-readiness-0123456")
        created = client.post("/schedules", json={**body, "approval_token": valid})
        replay = client.post("/schedules", json={**body, "approval_token": valid})
        if created.status_code not in (200, 201) or replay.status_code != 409:
            return None
        return False
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "kunne ikke afprøve schedule-godkendelsen: %r", exc
        )
        return None


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
    """Prove a scheduled write needs backend-held consent, not a known digest."""
    try:
        sys.path.insert(0, str(ROOT / "worker"))
        from app.schedule_api import CreateScheduleReq  # noqa: PLC0415

        fields = getattr(CreateScheduleReq, "model_fields", {})
        if "approved_fingerprint" in fields or "approval_token" not in fields:
            return False, (
                "schedule-API'et accepterer stadig en klientberegnelig "
                "godkendelse i stedet for et udstedt token"
            )
        opened = _try_to_mint_a_standing_grant()
        if opened is True:
            return False, (
                "en lokal proces uden backendens private nøgle kunne stadig "
                "oprette et standing grant"
            )
        if opened is None:
            return False, (
                "**Kunne ikke afprøve scheduler-godkendelsen.** Gaten nægter at "
                "gætte, når den ikke kan bevise både gyldig signatur og replay-stop"
            )
        return True, (
            "godkendelsen udstedes først efter paired bearer-auth af backendens "
            "Ed25519-private nøgle; workeren har kun public key, tokenet er "
            "kortlivet, bundet til hele standing grantet og kan kun bruges én gang"
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
        f"- **Godkendelsesbevis:** {approval_note}",
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
