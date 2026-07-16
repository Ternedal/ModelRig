# SECURITY.md — ModelRig / Kaliv

> Sikkerhedsbaseline pr. **13/7-2026** (kode: se `VERSION`). Dette er en *aktuel* trusselsmodel og
> risikooversigt, ikke en absolut garanti. Absolutte udsagn ("eneste sikkerhedspunkt")
> undgås bevidst — se "Kendte, accepterede risici".

## Hvad beskyttes (assets)

- **Device-tokens** (adgang til backend/riggen). Gemt som **SHA-256** i store'et, aldrig i klartekst.
- **Samtaler + RAG-data** (lokalt, potentielt personligt).
- **Selve riggen** (RTX 3060-maskinen) og dens modeller.

## Trust boundaries

- **Backend (Go, :8080) er eneste gateway.** Klienter taler aldrig direkte med en
  model-runtime. Al remote-adgang kræver Bearer-token (loopback-fri middleware; 127.0.0.1
  får ingen bypass).
- **Worker (FastAPI, :8099) er loopback-only** og uautentificeret bag backenden. Middleware
  + fail-fast forhindrer LAN-eksponering (opt-out: `KALIV_WORKER_ALLOW_LAN`).
- **Ollama (:11434)** er en lokal upstream bag backenden.
- **Transport:** **Tailscale (WireGuard)** er eneste sanktionerede remote-transport. Rå LAN
  er en accepteret risiko (se nedenfor).

## Trusselsaktører (realistisk for et solo-hjemmesetup)

1. Nogen på tailnettet/LAN (P0'en i 1.58.2 lukkede anonym remote kode-minting via `/pair/start`).
2. Et ondsindet dokument ved RAG-ingest (upload-limits + decoded-size-cap i 1.58.1).
3. Et ondsindet **cloud-model-svar** der forsøger at trigge tools (worker confirmation gate + SSRF-guard).
4. En tabt/stjålet telefon (device-token → revokér via CLI/`/api/v1/token/rotate`).

*Uden for model:* nation-state, fysisk adgang til riggen, supply-chain på Ollama-modeller.

## Credentials-oversigt

| Credential | Hvor | Note |
|---|---|---|
| Device-tokens | SHA-256 i store'et (backend); Android: Keystore-krypteret (`token_enc` + `rig_profile`); **desktop: klartekst i SQLite (DPAPI udestår)** | Single-use pairing-kode → token. Revokér/rotér pr. enhed. |
| `MODELRIG_ADMIN_KEY` | env (valgfri) | Sat → `/pair/start` kræver `X-Admin-Key`. Unset → `/pair/start` kun loopback. |
| GitHub PAT | Notion (Secrets) | Fine-grained, repo-scopet. Bruges til releases. Genbrugt på tværs — rotation er en stående todo. |
| Ollama Cloud-nøgle | Android: Keystore-krypteret; **desktop: klartekst i SQLite (DPAPI udestår)** | Kun i Cloud-tilstand; dyreste credential (kontoforbrug). |
| Android signeringsnøgle | **committet i repo** | Se accepteret risiko nedenfor. |

## Sikkerheds-defaults (håndhævet pr. 1.58.14)

Alle nye kontroller **defaulter til sikker adfærd**; man opter ud eksplicit via env-vars.

- Fail-closed persistens (rollback + 503 ved skrivefejl).
- Tool-gate fejler lukket ved korrupt state; `state_error` i `/health/full`.
- Worker loopback-only (`KALIV_WORKER_ALLOW_LAN` for at åbne).
- SSRF-guard på klient-leveret `cloud_base_url` (`KALIV_CLOUD_ALLOW_PRIVATE` for at åbne).
- Upload-limits (`KALIV_MAX_UPLOAD_MB=25`).
- `/pair/start`: loopback-only uden admin-key; `X-Admin-Key` når sat.
- Per-IP rate limit på pairing-claims.
- **Agent (v2):** reads kan kæde (bounded); ethvert write kræver et menneske-godkendt kort — også i en fortsættelse efter et godkendt write. `delete_model`/`pull_model` er gated writes med navne-validering.
- **Updater:** verificerer BÅDE backend og worker `/healthz`+version efter swap; auto-rollback ellers. Supervisoren indlæser `modelrig.env` til børnene (`MODELRIG_HOST=0.0.0.0` kræves for remote).

## Kendte, accepterede risici

### 1. Committet Android-signeringsnøgle — **ACCEPTERET** (D1, 13/7-2026)

`android/signing/modelrig.keystore` + `keystore.properties` ligger committet i det **public**
repo. En committet signeringsnøgle betyder i princippet at enhver kan bygge og signere en APK
som `dk.ternedal.modelrig`.

**Beslutning: risikoen accepteres, nøglen roteres/purges ikke nu.** Begrundelse:
- Solo-projekt, **sideload-only** — appen distribueres ikke via Google Play eller nogen anden kanal.
- Eneste bruger er Anders; appen taler kun med hans egen backend over Tailscale.
- En forfalsket-signatur-APK har derfor **ingen distributionskanal** til at nå nogen og **ingen
  tredjepart** at angribe. Angrebet forudsætter allerede at kunne få Anders til at sideloade en
  fremmed APK — på hvilket tidspunkt signaturen ikke er det svageste led.

**Revurderes hvis:** appen nogensinde distribueres offentligt, får andre brugere, eller
`applicationId` skal beskyttes mod squatting. Da: rotér nøgle, purge fra git-historik, flyt til CI-secret.

### 2. Rå LAN-transport — **ACCEPTERET**

`server.host = 0.0.0.0` (uden Tailscale) eksponerer backenden på LAN. Bevidst convenience;
Bearer-token kræves stadig. Foretræk Tailscale-IP.

### 3. Ingen TLS på backenden — **ACCEPTERET (for nu)**

Tailscale/WireGuard leverer den krypterede transport. Egen TLS er et **NEXT/apparat**-punkt
(ROADMAP.md), ikke et P0 så længe remote går gennem Tailscale.

### 4. Executable supply chain — **SHA-256 verificeret (1.58.15)**

`modelrig-updater` henter server/worker/supervisor-exes over HTTPS fra seneste GitHub-release.
Releasen publicerer nu `SHA256SUMS.txt` over alle assets, og updateren verificerer hver exe's
SHA-256 mod den **før** supervisoren stoppes — mismatch eller manglende entry afviser installationen
(fail closed; `-insecure-skip-verify` kun for en release der ligger før checksums).

**Ærlig grænse:** `SHA256SUMS.txt` er selv usigneret, så dette stopper et *tamperet/trunkeret asset*,
ikke en angriber med release-write (som kunne erstatte begge). Næste niveau: signeret manifest /
GitHub artifact attestation.

## Rotation & incident

- **Device-token:** `/api/v1/token/rotate` eller CLI; revokér enhed ved tab.
- **Admin-key:** skift `MODELRIG_ADMIN_KEY` og genstart.
- **GitHub PAT:** revokér på github.com/settings/tokens, lav ny fine-grained, opdatér Notion.
- **Signeringsnøgle:** kun relevant hvis accepteret risiko #1 revurderes.

## Åbne sikkerhedsrelaterede beslutninger

- **D3 — LUKKET:** destruktive model-writes (`delete_model`/`pull_model`) kører nu gennem samme
  server-side confirmation gate som andre writes (navne-valideret, menneske-godkendt).
- **D4a — RAG→cloud:** samtykke-gate implementeret server-side (`allow_rag_cloud`); Android-toggle
  er pt. ikke-funktionel (UI-fix udestår).
- **D4b — auto-cloud-fallback (LUKKET som sikker default, 1.58.19):** begge klienter falder kun
  tilbage til cloud når `autoCloudFallback`/`autoFallback` eksplicit er slået til; et billede sendes
  aldrig via fallback. Synligt opt-in-UI + "spørg før cloud"-kort udestår (kommer med #2a).
- **Cloud-read egress (ÅBEN — men nu klassificeret, 1.58.57):** read-tools kræver stadig ingen
  godkendelse for cloud-modeller. Det nye er, at det ikke længere er usagt: hvert tool har en
  `sensitivity`, der siger hvor dets **resultat** må rejse (ortogonalt på `risk`, som styrer hvad
  det må **gøre**):

  | Klasse | Betyder | Til en cloud-model? |
  |---|---|---|
  | `public` | Allerede offentligt/indholdsløst (uret) | Altid |
  | `operational` | Beskriver riggen: GPU, modeller, jobstatus | Ja — nuværende, dokumenterede adfærd |
  | `private` | Dit indhold: dokumentnavne, notetekst | **Kun med samtykke** — håndhæves bag `KALIV_EGRESS_GATE=1` indtil beslutning #6 |
  | `secret` | Nøgler | **Aldrig.** Samtykke kan ikke købe det. Håndhæves ALLEREDE — reglen findes før det første tool der får brug for den |

  `list_documents` er klassificeret `private`. Med gaten slået fra (default) opfører den sig præcis
  som før, så dette lukker ikke #6 — det gør beslutningen konkret og prøvbar: sæt
  `KALIV_EGRESS_GATE=1` på workeren og se hvad gating af reads faktisk koster i praksis, før du
  vælger.

## Kontrakt: writes (præcisering, 1.58.37)

**Tool-/model-initierede writes er server-gated** (parkeres, godkendelseskort,
TTL, immutable argumenter). **Eksplicit brugerinitierede administrationskald**
(`/models/pull`, `/models/delete` m.fl.) er bearer-beskyttede og
klient-bekræftede — serveren gater dem ikke igen. Enhver klient med gyldig
device-token kan altså kalde dem direkte; det er den bevidste kontrakt, ikke et
hul i tool-gaten. (Cloud-initierede READS er fortsat ugatede — åbent punkt #6.)
