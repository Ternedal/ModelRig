#!/usr/bin/env python3
"""Per-kilde til/fra for Viden — kontrakttests.

Hullet der lukkes: man kunne slette en kilde, men ikke SLUKKE for den. Det
gjorde "hvad ved Kaliv om mig lige nu" til et alt-eller-intet-spørgsmål.

Egenskaberne der skal holde:
  1. En slukket kilde kan ikke nå modellen gennem RAG.
  2. Intet slettes — tallene og teksten er der stadig, og kontakten kan
     tændes igen.
  3. Databaser fra FØR tabellen fandtes virker uændret (alt er tændt).
  4. Slukket tilstand OVERLEVER en ny ingest af samme kilde. Det modsatte
     ville stille tænde en kilde brugeren har slukket.
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "worker"))
import os
os.chdir(pathlib.Path(__file__).resolve().parents[1] / "worker")

from app.store import DocStore  # noqa: E402

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


def fresh() -> tuple[DocStore, str]:
    d = tempfile.mkdtemp(prefix="kaliv-toggle-")
    path = str(pathlib.Path(d) / "rag.db")
    st = DocStore(path)
    st.add("noter om katten", source="noter.md", chunk_index=0, embedding=[1.0, 0.0])
    st.add("regnskab 2026", source="regnskab.pdf", chunk_index=0, embedding=[0.0, 1.0])
    return st, path


def main() -> int:
    st, path = fresh()

    check("alt er tændt som udgangspunkt", st.disabled_sources() == set())
    check("begge kilder hentes", len(st.all(include_disabled=False)) == 2)

    st.set_source_enabled("regnskab.pdf", False)
    rows = st.all(include_disabled=False)
    check("slukket kilde hentes IKKE", [r[2] for r in rows] == ["noter.md"],
          f"-- fik {[r[2] for r in rows]}")
    check("intet er slettet", len(st.all(include_disabled=True)) == 2)
    check("tallene er urørte", dict((s, n) for s, n, _ in st.sources())["regnskab.pdf"] == 1)

    st.set_source_enabled("regnskab.pdf", True)
    check("kontakten kan tændes igen", len(st.all(include_disabled=False)) == 2)

    # Slukket tilstand skal overleve en ny ingest af samme kilde.
    st.set_source_enabled("regnskab.pdf", False)
    st.apply_ingest(["regnskab.pdf"], [("regnskab 2027", [0.0, 1.0], "regnskab.pdf", 0)])
    check("ny ingest tænder IKKE en slukket kilde",
          "regnskab.pdf" in st.disabled_sources())
    check("og den nye tekst hentes heller ikke",
          all(r[2] != "regnskab.pdf" for r in st.all(include_disabled=False)))

    # NULL-kilden hedder '(none)' overalt og skal kunne slukkes under det navn.
    st.add("løs tekst", source=None, chunk_index=0, embedding=[0.5, 0.5])
    st.set_source_enabled("(none)", False)
    check("NULL-kilden kan slukkes som '(none)'",
          all((r[2] or "(none)") != "(none)" for r in st.all(include_disabled=False)))
    st.close()

    # En database fra FØR tabellen fandtes: alt skal virke, alt er tændt.
    d = tempfile.mkdtemp(prefix="kaliv-legacy-")
    legacy = str(pathlib.Path(d) / "old.db")
    conn = sqlite3.connect(legacy)
    conn.execute(
        "CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, "
        "source TEXT, chunk_index INTEGER NOT NULL DEFAULT 0, embedding TEXT NOT NULL, "
        "created_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO documents (text, source, chunk_index, embedding, created_at) "
        "VALUES ('gammel', 'gammel.md', 0, '[1.0, 0.0]', 1.0)"
    )
    conn.commit()
    conn.close()
    old = DocStore(legacy)
    check("gammel database migrerer uden tab", len(old.all(include_disabled=False)) == 1)
    check("og alt er tændt i den", old.disabled_sources() == set())
    old.set_source_enabled("gammel.md", False)
    check("kontakten virker også der", old.all(include_disabled=False) == [])
    old.close()

    # --- og det vigtigste: at RETRIEVAL faktisk bruger kontakten ------------
    # Sabotagetjek afslørede at mine første tests kun målte lageret: fjernede
    # jeg include_disabled=False i query(), forblev alt grønt. En regel man kan
    # slette uden at noget bliver rødt, er ikke en regel — så her drives den
    # rigtige query() med en stub-embedder.
    import asyncio

    import app.rag as rag_mod
    import app.ollama_client as oc_mod

    st2, _ = fresh()

    async def fake_embed(text: str) -> list[float]:
        # Ligner "noter"-vektoren, så begge kilder ville score højt nok.
        return [0.7, 0.7]

    real_embed = oc_mod.embed
    oc_mod.embed = fake_embed
    rag_mod.oc.embed = fake_embed
    try:
        st2.set_source_enabled("regnskab.pdf", False)
        res = asyncio.run(rag_mod.query(st2, "hvad ved du", synthesize=False, min_score=0.0))
        srcs = {m.get("source") for m in res.get("matches", [])}
        check("query() henter IKKE fra en slukket kilde", "regnskab.pdf" not in srcs,
              f"-- fik {srcs}")
        check("query() henter stadig fra de taendte", "noter.md" in srcs, f"-- fik {srcs}")
        st2.set_source_enabled("regnskab.pdf", True)
        res2 = asyncio.run(rag_mod.query(st2, "hvad ved du", synthesize=False, min_score=0.0))
        srcs2 = {m.get("source") for m in res2.get("matches", [])}
        check("og igen naar kilden taendes", "regnskab.pdf" in srcs2, f"-- fik {srcs2}")
    finally:
        oc_mod.embed = real_embed
        rag_mod.oc.embed = real_embed
        st2.close()

    print(f"\n===== RAG SOURCE TOGGLE: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
