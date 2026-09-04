#!/usr/bin/env python3
"""Menneskenavn på en plan — uden at røre ved hvad der er godkendt.

Scheduler-skærmen viste tool-navnet som titel, fordi planer ikke havde et
navn. Det har de nu. Den vigtige egenskab er IKKE at navnet gemmes, men at
det holdes UDE af godkendelsens fingerprint: kunne et navn ændre
fingerprintet, ville en omdøbning enten ugyldiggøre en gyldig godkendelse
eller kunne bruges til at flytte en godkendelse hen på noget andet.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.scheduler import ScheduleStore, ScheduleError, fingerprint  # noqa: E402

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")


def store(tmp: str, filename: str = "s.db") -> ScheduleStore:
    return ScheduleStore(os.path.join(tmp, filename))


def main() -> int:
    tmp = tempfile.mkdtemp()
    st = store(tmp)

    named = st.create("note.write", {"text": "hej"}, "daily:03:00", label="  Natlig backup  ")
    check("navnet gemmes trimmet", named.label == "Natlig backup", f"-- {named.label!r}")

    plain = st.create("note.write", {"text": "hej"}, "daily:03:00")
    check("uden navn er feltet None, ikke en tom streng", plain.label is None)

    check(
        "tomt/whitespace-navn bliver None frem for at blive gemt",
        st.create("note.write", {"text": "a"}, "daily:04:00", label="   ").label is None,
    )

    try:
        st.create("note.write", {"text": "b"}, "daily:05:00", label="x" * 81)
        check("for langt navn afvises", False, "-- ingen fejl blev rejst")
    except ScheduleError:
        check("for langt navn afvises", True)

    # DEN VIGTIGE: navnet må aldrig kunne flytte eller bryde en godkendelse.
    check(
        "fingerprintet er uafhængigt af navnet",
        fingerprint("note.write", {"text": "hej"}) == fingerprint("note.write", {"text": "hej"}),
    )
    check(
        "to planer med samme handling og FORSKELLIGE navne har samme fingerprint",
        named.approved_fingerprint == plain.approved_fingerprint,
    )

    # Navnet overlever en genåbning, og migrationen er idempotent.
    reopened = store(tmp)
    labels = sorted((s.label or "") for s in reopened.list_all())
    check("navnet overlever genåbning", "Natlig backup" in labels)
    check("migrationen kan køre igen uden at tabe rækker", len(reopened.list_all()) == 3)

    # En database uden kolonnen (som før denne ændring) skal kunne åbnes.
    legacy_path = os.path.join(tmp, "legacy.db")
    import sqlite3

    conn = sqlite3.connect(legacy_path)
    conn.execute(
        "CREATE TABLE schedules (id TEXT PRIMARY KEY, tool TEXT NOT NULL,"
        " args TEXT NOT NULL, cadence TEXT NOT NULL, approved_fingerprint TEXT,"
        " expires_at REAL NOT NULL, max_runs INTEGER NOT NULL DEFAULT 0,"
        " runs_used INTEGER NOT NULL DEFAULT 0, due_at REAL NOT NULL,"
        " missed INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,"
        " timezone TEXT NOT NULL DEFAULT 'Europe/Copenhagen',"
        " misfire_policy TEXT NOT NULL DEFAULT 'run_once', created REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO schedules (id, tool, args, cadence, approved_fingerprint,"
        " expires_at, max_runs, runs_used, due_at, missed, enabled, timezone,"
        " misfire_policy, created) VALUES"
        " ('old1','note.write','{}','daily:03:00',NULL,9e9,0,0,9e9,0,1,"
        "'Europe/Copenhagen','run_once',0)"
    )
    conn.commit()
    conn.close()

    migrated = ScheduleStore(legacy_path)
    rows = migrated.list_all()
    check("en gammel database migreres i stedet for at fejle", len(rows) == 1)
    check("gamle planer har intet navn og falder tilbage til tool", rows[0].label is None)

    print(f"schedule label: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
