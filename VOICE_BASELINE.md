# Voice baseline — fysisk rig- og Pixel-runbook

Denne runbook afslutter den fysiske del af **T-040**. Manifest, scorer,
stream-protokoltest, cancellation-prober og rapportformat ligger i repositoryet;
ASR/TTS/LLM-latency og telefonens reelle stop/barge-in kræver riggen og Pixel 6a.

## Hvad harnesset måler

`scripts/voice_baseline.py` bruger den eksisterende worker direkte over loopback:

- `GET /healthz`, `/voice/asr/status` og `/voice/tts/status`;
- `POST /voice/converse/stream` med 20 faste danske WAV-optagelser;
- transcript-, første-audio- og done-latency set fra klienten;
- workerens egne pipeline-TTFA/total-målinger;
- WER og CER mod det versionsbundne reference-manifest;
- eventrækkefølge, contiguous chunk-indeks og terminal `done`/`error`;
- connection-cancellation efter transcript og første audio-chunk;
- worker-health og fjernelse af nye `alva_voice_*` tempmapper efter cancellation;
- cold probe, når operatøren eksplicit bekræfter en frisk modelstart;
- fem manuelle Pixel-trials for stop og barge-in.

Harnesset åbner kun en `http://localhost`, `127.0.0.1` eller `::1` worker-URL.
IPv6-loopback skrives canonical som `http://[::1]:8099`. Det accepterer ingen
device-token eller cloud-nøgle. Rapporten indeholder hashes, format, timings og
tekstscore — ikke rå inputlyd eller det fulde modelsvar.

## 1. Opret de 20 WAV-fixtures

Referencefraserne ligger i:

```text
eval/voice_baseline_manifest.v1.json
```

Optag hver frase én gang med samme mikrofonafstand og normalt taletempo. Gem dem
som:

```text
validation/voice-fixtures/turn-01.wav
...
validation/voice-fixtures/turn-20.wav
```

Krav pr. fil:

- PCM WAV;
- mono;
- 16-bit;
- 16.000 Hz;
- 0,25–30 sekunder;
- ingen musik, normalisering eller syntetisk tale.

En eksisterende optagelse kan konverteres med FFmpeg:

```powershell
ffmpeg -i input.m4a -ac 1 -ar 16000 -c:a pcm_s16le `
  validation\voice-fixtures\turn-01.wav
```

Kontrollér hele fixture-sættet uden at kontakte worker:

```powershell
python scripts\voice_baseline.py `
  --validate-only `
  --report validation\voice-baseline-fixture-check.json
```

Exit `0` kræver alle 20 filer og korrekt WAV-format. Rapporten binder hver fil
med SHA-256 og varighed, så en senere optagelse ikke kan forveksles med baseline.

## 2. Forbered manuel stop/barge-in-matrix

Kopiér skabelonen:

```powershell
Copy-Item `
  eval\voice_manual_observations.example.json `
  validation\voice-manual-observations.json
```

Udfyld device/app-version. Kør de fem beskrevne trials på Pixel 6a og udfyld:

- `recognized`: blev stop/barge-in registreret?
- `playback_stopped`: stoppede afspilningen faktisk?
- `stale_audio_resumed`: kom gammel audio tilbage? Skal være `false`.
- `ui_terminal_state`: `cancelled` eller `idle`.
- `stop_latency_ms`: observeret latency fra trigger til stoppet audio.

Skabelonens `pending`/`false`-værdier kan ikke bestå en required-manual gate.

## 3. Cold-start-forudsætning

Cold-proben er kun sand, hvis ASR-, TTS- og den valgte lokale LLM-model ikke
allerede er varm. Før baseline:

1. genstart ModelRig-appliance efter den gældende validation-runbook;
2. kontrollér at worker er ready;
3. kør ikke en voice-request først;
4. brug kun `--cold-start-confirmed`, når ovenstående er sandt.

Flaget er en operatørerklæring, ikke noget harnesset kan gætte fra processtatus.
Cold-proben bruger `turn-01`; de efterfølgende 40 runs er warm-suite (20 turns ×
2 gentagelser).

## 4. Autoritativ baseline-kørsel

Fra repositoryets rod på riggen:

```powershell
python scripts\voice_baseline.py `
  --worker-url http://127.0.0.1:8099 `
  --model gemma3:12b `
  --repetitions 2 `
  --cold-start-confirmed `
  --cancellation-probes 4 `
  --manual-observations validation\voice-manual-observations.json `
  --require-manual `
  --report validation\voice-baseline-latest.json
```

Erstat modelnavnet med den model, der faktisk skal være baseline. Den rapporterede
`pipeline.model`, worker-status, version og commit-SHA skal efterfølgende matche.

Den første baseline **rapporterer** WER og latency uden at opfinde en hård
grænse. Når baseline er accepteret, kan en senere sammenligningskørsel bruge:

```powershell
--max-wer 0.15 --max-warm-first-audio-ms 3500
```

Grænserne skal komme fra den accepterede fysiske baseline med en dokumenteret
støjmargen — ikke fra CI eller et gæt.

## 5. Exit codes

| Exit | Betydning |
|---:|---|
| `0` | Stream/protokol, alle turns, cancellation-cleanup og eventuel required-manual gate bestod. |
| `1` | Harnesset kørte, men en quality/latency/manual gate eller et turn fejlede. |
| `2` | Fixture-, worker-, manifest- eller harnessmiljøet kunne ikke give en gyldig kørsel. Rapporten skrives stadig. |

## 6. Rapport-review

Kontrollér `validation/voice-baseline-latest.json`:

- `schema` er `kaliv-voice-baseline/v1`;
- manifest-version og SHA-256 er udfyldt;
- `build.git_sha` matcher den testede commit;
- alle 20 fixture-hashes og formater er dokumenteret;
- ASR- og TTS-status viser de forventede modeller/enheder;
- cold-proben er completed, hvis `cold_start_confirmed=true`;
- warm-suite har 40 completed runs og `errors=0`;
- WER/CER og transcript/first-audio/done p50/p95 er udfyldt;
- workerens pipeline-TTFA/total er udfyldt;
- alle cancellation-prober har `aborted=true`, `worker_healthy=true` og
  `cleanup.clean=true`;
- manuel matrix har mindst fem trials, `passed=true` og ingen stale audio;
- topniveauets `gate.passed` er `true`.

Rapporten gemmer transcript som normaliseret scoredata og SHA, men ikke det fulde
modelsvar. Input-WAV-filerne forbliver lokale og skal ikke committes.

## 7. Gem permanent evidens

Efter manuel kontrol:

```powershell
Copy-Item `
  validation\voice-baseline-latest.json `
  validation\voice-baseline-2026-07-XX.json
```

Commit kun den daterede rapport, hvis den ikke indeholder uønskede lokale noter,
og hvis version, SHA, modeller, fixtures, cleanup og gate er korrekte. Den lokale
`latest`-fil og WAV-fixtures er arbejdsdata og skal forblive ignoreret.
