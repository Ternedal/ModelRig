"""ADR-A4-005: Agent 4-PR'er skal dokumentere ADR, referencearkitektur og afhængigheder.

Beslutningen er truffet (ADR-A4-005, Konsekvens-afsnittet): enhver fremtidig
Agent 4-PR skal angive hvilken ADR den implementerer, hvilken
referencearkitektur den bygger på, og hvilke PR'er den afhænger af. ADR'ens
ærlighedsnote markerede den maskinelle håndhævelse som en åben mulighed —
denne gate er dén mulighed, bygget efter at konvergensen er afsluttet.

Adfærd:
- Selvtests køres ALTID (en gate, der kun kan bestå, er ikke en gate).
- I CI på en pull_request-event: hvis diffen rører ``worker/app/agent4/``,
  skal PR-beskrivelsen matche alle tre krav; ellers fejler gaten lukket.
- Uden pull_request-event (main-push, lokal kørsel) evalueres kun selvtests.

Fail-closed: kan fillisten ikke afgøres i CI, fejler gaten med en klar
besked frem for at gætte.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

REQUIREMENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("implementeret ADR (ADR-A4-XXX)", re.compile(r"ADR-A4-\d{3}", re.I)),
    (
        "referencearkitektur",
        re.compile(r"referencearkitektur|reference\s+architecture", re.I),
    ),
    (
        "afhængigheder",
        re.compile(r"afh[æa]ng|depends|dependenc", re.I),
    ),
)

AGENT4_PREFIX = "worker/app/agent4/"

PASS_BODY = """**Formål:** én slice.
**Implementerer:** ADR-A4-006 · **Referencearkitektur:** B ·
**Afhængigheder:** #258, #281."""

FAIL_BODIES: tuple[tuple[str, str], ...] = (
    ("mangler ADR", "Referencearkitektur: B. Afhængigheder: ingen."),
    ("mangler referencearkitektur", "Implementerer ADR-A4-006. Depends on #281."),
    ("mangler afhængigheder", "ADR-A4-006 på B-referencearkitekturen."),
)


def missing_requirements(body: str) -> list[str]:
    return [name for name, rx in REQUIREMENTS if not rx.search(body or "")]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def changed_files(base_sha: str, base_ref: str) -> list[str] | None:
    """Return PR-changed files, fetching the base if the checkout is shallow."""
    if _run("git", "cat-file", "-e", f"{base_sha}^{{commit}}").returncode != 0:
        _run("git", "fetch", "--depth=1", "origin", base_sha)
    if _run("git", "cat-file", "-e", f"{base_sha}^{{commit}}").returncode != 0 and base_ref:
        _run("git", "fetch", "--depth=1", "origin", base_ref)
    diff = _run("git", "diff", "--name-only", f"{base_sha}...HEAD")
    if diff.returncode != 0:
        return None
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def evaluate_event() -> tuple[bool, str]:
    """Evaluate the live pull_request event; (ok, message)."""
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not os.path.exists(path):
        return True, "ingen event-fil — kun selvtests"
    with open(path, encoding="utf-8") as handle:
        event = json.load(handle)
    pull = event.get("pull_request")
    if not pull:
        return True, "ikke en pull_request-event — kun selvtests"
    base = pull.get("base") or {}
    files = changed_files(base.get("sha", ""), base.get("ref", ""))
    if files is None:
        return False, "fillisten kunne ikke afgøres — fail-closed"
    touched = sorted(f for f in files if f.startswith(AGENT4_PREFIX))
    if not touched:
        return True, "diffen rører ikke worker/app/agent4/ — kravet gælder ikke"
    missing = missing_requirements(pull.get("body") or "")
    if missing:
        return False, (
            "PR'en rører "
            + ", ".join(touched[:3])
            + (" m.fl." if len(touched) > 3 else "")
            + " men beskrivelsen mangler: "
            + "; ".join(missing)
            + " (ADR-A4-005)"
        )
    return True, f"beskrivelsen opfylder ADR-A4-005 ({len(touched)} agent4-filer)"


def main() -> int:
    passed = 0
    failed = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"  PASS: {label}")
        else:
            failed += 1
            print(f"  FAIL: {label} {detail}".rstrip())

    check("god beskrivelse accepteres", not missing_requirements(PASS_BODY))
    for label, body in FAIL_BODIES:
        gaps = missing_requirements(body)
        check(f"sabotage fældes: {label}", len(gaps) == 1, f"(fandt: {gaps})")
    check("tom beskrivelse fælder alle tre", len(missing_requirements("")) == 3)

    ok, message = evaluate_event()
    check(f"live event: {message}", ok)

    print(
        f"\n===== ADR-A4-005 PR-DOKUMENTATION: {passed} passed, {failed} failed ====="
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
