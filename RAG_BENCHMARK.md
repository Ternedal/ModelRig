# RAG benchmark — fysisk rig-runbook

Denne runbook afslutter den fysiske del af backlog-task **T-043**. Harness,
datasæt, scoring, cleanup og regressionsbeviser ligger allerede i repositoryet;
kun målingen mod riggens lokale Ollama-embeddingmodel kræver maskinen.

## Sikkerhedsgrænse

`scripts/rag_benchmark.py`:

- åbner en ny midlertidig SQLite-database;
- åbner aldrig ModelRigs normale RAG-database;
- kræver intet device-token;
- kalder den rigtige `app.rag` chunk/embed/store/cosine-pipeline;
- kører altid retrieval med `synthesize=False`;
- bruger et hashbundet benchmark-source-namespace pr. skala;
- sletter namespace og kræver en tom benchmarkdatabase efter hver skala;
- skriver rapporten atomisk, også ved en uventet harness-fejl.

## Forudsætninger

1. Kør fra repositoryets rod på ModelRig.
2. Ollama skal svare på den lokale URL, normalt `http://127.0.0.1:11434`.
3. Embeddingmodellen skal være installeret, normalt `nomic-embed-text`.
4. Brug den samme commit, som rapportens `build.git_sha` senere viser.
5. Luk tunge GPU-programmer, hvis målingen skal kunne sammenlignes over tid.

Kontrollér modellen:

```powershell
ollama list
```

## Autoritativ baseline-kørsel

```powershell
python scripts/rag_benchmark.py `
  --scales 1000,10000 `
  --queries 40 `
  --repetitions 2 `
  --embedding-model nomic-embed-text `
  --report validation/rag-benchmark-latest.json
```

Harnesset bruger som standard en recall@5-gate på **0,95**. Query-latency bliver
målt, men er ikke en hård gate, før den første fysiske baseline har fastlagt en
forsvarlig grænse.

Et andet Ollama-endpoint kan angives eksplicit:

```powershell
python scripts/rag_benchmark.py `
  --ollama-url http://127.0.0.1:11434 `
  --embedding-model nomic-embed-text `
  --scales 1000,10000 `
  --queries 40 `
  --repetitions 2 `
  --report validation/rag-benchmark-latest.json
```

## Exit codes

| Exit | Betydning |
|---:|---|
| `0` | Alle skalaer, queries, quality-gate og cleanup bestod. |
| `1` | Harnesset kørte, men quality-/latency-gaten eller en skala fejlede. |
| `2` | Miljø- eller harness-fejl, eksempelvis utilgængelig Ollama/model. Rapporten skrives stadig med `gate.passed=false`. |

En warmup-fejl, eksempelvis en manglende embeddingmodel, skriver stadig den
fulde evidenskontrakt med build-SHA, isolation, konfiguration, Ollama-model,
tom `scales`-liste, fejldetalje og eksplicit fejlet gate. Det gør rapporten
validerbar uden adgang til riggens konsol.

## Rapporten skal kontrolleres

Åbn `validation/rag-benchmark-latest.json` og kontrollér:

- `schema` er `kaliv-rag-benchmark/v1`;
- `dataset_version` og hvert `dataset.sha256` er udfyldt;
- `build.git_sha` matcher den testede commit;
- `ollama.embedding_model` er den forventede model;
- både 1.000- og 10.000-chunk-skalaen findes;
- `quality.recall.at_5` er mindst `0.95`;
- `quality.errors` er `0`;
- `cleanup.clean` er `true` og `remaining_chunks` er `0` for begge skalaer;
- p50/p95, ingest-throughput, RSS og GPU baseline/peak/delta er udfyldt, hvor platformen understøtter målingen;
- topniveauets `gate.passed` er `true`.

`nvidia-smi` viser samlet GPU-forbrug på enheden, ikke præcis
procesallokering. Derfor rapporteres både baseline, peak og delta; deltaen er den
mest sammenlignelige værdi, når andre GPU-programmer er lukket.

## Gem baselinebeviset

Når rapporten er godkendt, kopieres den til en dateret evidensfil, eksempelvis:

```powershell
Copy-Item `
  validation/rag-benchmark-latest.json `
  validation/rag-benchmark-2026-07-XX.json
```

Den daterede fil må først committes efter manuel kontrol af commit-SHA, model,
cleanup og gate-resultat. `latest` er en lokal arbejdsrapport; den daterede fil
er det permanente bevis.

## Efter første baseline

Brug 10k-resultatets query-p95 som udgangspunkt for en senere `--max-p95-ms`
gate med rimelig støjmargen. Kalibrér derefter `min_score`, `top_k` og eventuelt
chunkstørrelse mod faktiske danske dokumenter som beskrevet i `RAG_DESIGN.md`.
Der må ikke sættes en hård latencygrænse ud fra CI eller gæt.
