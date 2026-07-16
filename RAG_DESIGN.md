# RAG_DESIGN.md — hærdning af dokumentviden (RAG)

**Status:** LIVE · replace-by-source leveret (1.58.40) · §5-kalibrering kræver rig · **Ejer:** Anders

> Autoritativt design for RAG-ingest/-retrieval, grundet i **kodelæsning**
> (rag.py, store.py, main.py's seks ingest-endpoints, rag_pdf/docx/pptx) — ikke
> i antagelser. Skelner Implementeret / Planlagt / Åbent-kræver-rig-data.

## 1. Arkitekturen som den ER (verificeret 14/7-2026)

Seks ingest-veje (text, PDF, DOCX, PPTX, HTML/URL, deck) → fælles pipeline:
`chunk_text` (sætnings-foretrukne brud, overlap) → `oc.embed` pr. chunk →
SQLite `documents` (text, source, chunk_index, embedding). Retrieval: cosine
over alle chunks (evt. source-filtreret) → **min_score-filter FØR top_k-cut**
(en forespørgsel uden reelt relevante chunks returnerer færre/nul frem for at
polstre konteksten med støj) → valgfri syntese.

## 2. Ærlig korrektion af audit-claims

Fuld-repo-auditen (mod 1.58.36) antog flere huller som **allerede er lukket**:
- Scannet PDF uden tekstlag → **422** med klar besked (ikke tavs tom indeksering).
- Krypteret/ulæselig PDF → ærlig 400; tom DOCX/PPTX/deck → 422.
- Størrelsesloft på uploads (`_reject_if_too_large`).
- Chunkeren er sætningsbevidst med overlap, ikke naiv fast-bredde.

Det **reelle** hul var et andet — se R1.

## 3. Fejlmodel → status

| # | Fejl | Konsekvens | Status |
|---|---|---|---|
| R1 | **Gen-ingest duplikerede alt.** `ingest` kaldte kun `store.add` — en opdateret PDF eller et dobbelt-tryk fordoblede kildens chunks | Retrieval fyldt med nær-identiske dubletter der fortrænger andre kilder i top_k; indekset vokser kun | ✅ **1.58.40: replace-by-source** (se §4) |
| R2 | Tekst-stien accepterede blanke dokumenter som tavs 0-chunk-succes | "Færdig" uden at noget blev indekseret — pull-buggens fætter | ✅ 1.58.40: 422, konsistent med alle andre stier |
| R3 | DOCX-tabeller kan splittes midt i en række af chunkeren | Tabelfakta spredt over chunks → dårlig retrieval på tabeldata | 🔶 Planlagt: tabel-atomiske chunks (én chunk pr. tabel op til chunk_size) — kræver læsning af rag_docx' serialisering først |
| R4 | top_k=4 / min_score=0.3 er ukalibrerede gæt | For stramt → "ved ikke" på reelt svarbare spørgsmål; for løst → støj | 🟡 **Kræver rig-data**: valideringsrundens F3/F4 + rigtige dokumenter afgør; knapperne findes allerede i API'et |
| R5 | Ingen OCR | Scannede dokumenter kan ikke indekseres | ⛔ Erklæret ikke-mål for nu (ærlig 422 er adfærden); OCR = stor dependency, egen beslutning |
| R6 | Ingen side-/afsnitscitater | Svar kan ikke pege på side N | 🔶 Planlagt: `page`-metadata fra rag_pdf videre til `documents` + `[kilde s.N]` i syntese |

## 4. Replace-by-source (Implementeret 1.58.40, testet)

**Semantik:** gen-ingest af en `source` ERSTATTER dens tidligere chunks —
sletning sker én gang pr. distinkt source pr. *kald*, så flere dokumenter der
deler source i samme request lander sammen. `None`/tom source beholder
append-semantik med vilje (ingen identitet at erstatte). Alle seks
ingest-endpoints rapporterer nu `replaced` i svaret.

**Testet** (tests/worker_rag.py, 11 nye checks, kører i CI): total stabil ved
gen-ingest · gamle chunks væk, ny tekst vinder retrieval · andre kilder urørte ·
multi-dokument samme source i ét kald bevares · blank tekst → 422.

## 5. Åbne spørgsmål der SKAL besvares på riggen (valideringsrunden)

1. Rammer min_score=0.3 rigtigt på dine faktiske dokumenter (dansk indhold,
   nomic-embed-text)? Test: stil 5 spørgsmål du VED står i dokumenterne + 3 der
   ikke gør; notér misses/støj.
2. Chunk-størrelse 800/150 mod dine typiske PDF'er — for små til tabeller?
3. Er `replaced`-tallet synligt nok i klienten, eller skal UI vise "opdateret"?

## 6. Ikke-mål
OCR (R5) · reranking-model (cosine + min_score er nok indtil rig-data siger
andet) · vektor-DB-skifte (SQLite + brute-force cosine er korrekt for én rigs
dokumentmængde; Qdrant er over-engineering her).
