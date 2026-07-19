# SECURITY.md — ModelRig / Kaliv

> ## Model her — tilstand dér
>
> Dette ER trusselsmodellen (F-1019): den varige arkitektur-ræsonnering — hvem
> angriberen er, hvor grænserne går, hvilke lag der står imellem, og hvilke
> risici der er accepteret med begrundelse. Den slags rådner langsomt, fordi
> den handler om design, ikke om øjebliksbilleder.
>
> Hvad den bevidst IKKE er: en påstand om aktuel tilstand. Om kontrollerne
> faktisk er koblet og grønne på netop denne commit regnes ud fra koden i
> [`CURRENT_STATE.md`](CURRENT_STATE.md) og
> [`ACTIVATION_READINESS.md`](ACTIVATION_READINESS.md) — sidstnævnte kører
> durability-proberne live ved hver generering. Versionsnumre nedenfor er
> historik ("indført i 1.58.x") og forbliver sande for evigt.
>
> **Og én ærlig grænse:** alt her er arkitektur-niveau. Intet i denne fil
> erstatter den fysiske valideringskampagne (F-1001) — papir og CI beviser
> ikke en appliance.

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

1. **Modellens eget output** — lokal eller cloud, direkte eller via et
   forgiftet dokument. Det er den definerende trussel for et agentisk system
   og har sit eget afsnit nedenfor.
2. Nogen på tailnettet/LAN (P0'en i 1.58.2 lukkede anonym remote kode-minting via `/pair/start`).
3. Et ondsindet dokument ved RAG-ingest (upload-limits + decoded-size-cap i
   1.58.1) — bemærk at dokumentets *indhold* derefter er aktør #1's kanal.
4. En tabt/stjålet telefon (device-token → revokér via CLI/`/api/v1/token/rotate`;
   scheduler-godkendelser er device-bundne, så en fremmed enhed kan ikke minte dem).
5. **Supply chain på kode-siden:** Python-deps pinnet `==`, GitHub Actions
   SHA-pinnet, Dependabot + CodeQL på main, release-assets SHA-256-verificeret
   af updateren (1.58.15; ærlig grænse: manifestet er selv usigneret — se
   accepteret risiko #4).

*Uden for model:* nation-state, fysisk adgang til riggen (single-user-appliance;
lokal adgang = game over by design, med DPAPI-at-rest som åbent punkt, T-033),
supply-chain på selve Ollama-modelvægtene.

## Den definerende trussel: modellens output som angriber

En LLM der kan kalde værktøjer, er et system hvor *svaret* er en potentiel
angriber — prompt injection via chat, et hentet dokument eller et cloud-svar.
Forsvaret er lagdelt, og hvert lag er arkitektur (dateret historik, ikke
tilstandspåstand):

- **Prosa eksekverer aldrig.** Workeren udfører kun strukturerede
  `tool_calls`; "jeg har oprettet noten" i løbende tekst gør ingenting.
- **ToolGate:** risikoklasser (read/write), hvert write bag et
  menneske-godkendt kort med fingerprint bundet til de *præcise* argumenter,
  engangs-bekræftelser, origin-tagget audit, global kill-switch der pauser før
  claim. `sensitivity`-klassen styrer ortogonalt hvor et *resultat* må rejse
  (se cloud-read-egress under åbne beslutninger).
- **Stående grants (scheduleren) er den farligste flade** — en godkendelse der
  virker uden et menneske i loopet — og fik derfor sin egen kæde (18-19/7,
  1.58.116–127): device-bundne engangs-tokens (1.58.93) med persisterede
  approval-receipts (hvem/hvornår/hvorfra, atomisk med granten);
  occurrence-ledger med budget reserveret ved claim, så `max_runs` holder
  under crash og genstart; evidensbaseret recovery med attempt-markør — et
  ukendt udfald *beholder* sin slot og pauser granten frem for at muliggøre
  en ekstra kørsel; revision-guard umiddelbart før eksekvering, så pause,
  fornyelse eller sletning faktisk stopper in-flight arbejde; owner-lease, så
  en levende workers claims ikke kan opgives af en anden proces; og en
  freeze-gate der kun siger FROZEN med exact-head CI-bevis. Readiness-siden
  kører disse egenskaber som live-prober, bevist ikke-blinde.
- **Dormant by design:** ToolHost-procesgrænsen og Tier B-policy findes i
  koden men er bevidst inaktive indtil I0b-isolationen er fysisk bevist —
  udvidelse af den agentiske flade er gated på bevis, ikke på at koden
  eksisterer.

## Credentials-oversigt

| Credential | Hvor | Note |
|---|---|---|
| Device-tokens | SHA-256 i store'et (backend); Android: Keystore-krypteret (`token_enc` + `rig_profile`); **desktop: Windows DPAPI, current-user scope** | Desktop migrerer ældre klartekst i SQLite før første udlevering. Single-use pairing-kode → token. Revokér/rotér pr. enhed. |
| `MODELRIG_ADMIN_KEY` | env (valgfri) | Sat → `/pair/start` kræver `X-Admin-Key`. Unset → `/pair/start` kun loopback. |
| `KALIV_SCHEDULER_APPROVAL_SECRET` | env i **backend og worker** | Samme tilfældige værdi på mindst 32 bytes. Signerer korte scheduler-godkendelsestokens; må aldrig committes. |
| GitHub PAT | Notion (Secrets) | Fine-grained, repo-scopet. Bruges til releases. Genbrugt på tværs — rotation er en stående todo. |
| Ollama Cloud-nøgle | Android: Keystore-krypteret; **desktop: Windows DPAPI, current-user scope** | Desktop migrerer ældre klartekst i SQLite før første udlevering. Kun i Cloud-tilstand; dyreste credential (kontoforbrug). |
| Android signeringsnøgle | **committet i repo** | Se accepteret risiko nedenfor. |

## Sikkerheds-defaults

Alle nye kontroller **defaulter til sikker adfærd**; man opter ud eksplicit via env-vars.

- Fail-closed persistens (rollback + 503 ved skrivefejl).
- Tool-gate fejler lukket ved korrupt state; `state_error` i `/health/full`.
- Worker loopback-only (`KALIV_WORKER_ALLOW_LAN` for at åbne).
- SSRF-guard på klient-leveret `cloud_base_url` (`KALIV_CLOUD_ALLOW_PRIVATE` for at åbne).
- Upload-limits (`KALIV_MAX_UPLOAD_MB=25`).
- `/pair/start`: loopback-only uden admin-key; `X-Admin-Key` når sat.
- Per-IP rate limit på pairing-claims.
- **Agent (v2):** reads kan kæde (bounded); ethvert write kræver et menneske-godkendt kort — også i en fortsættelse efter et godkendt write. `delete_model`/`pull_model` er gated writes med navne-validering.
- **Scheduler-writes:** `preview → approve → create/renew`; godkendelsestokenet er HMAC-signeret, device- og vilkårsbundet, udløber efter to minutter og kan kun bruges én gang. Manglende eller for kort fælles secret fejler lukket.
- **Desktop-credentials:** `deviceToken` og `cloudKey` lagres som versionsmærkede DPAPI-envelopes. Ukendt version, korrupt ciphertext eller utilgængelig DPAPI afvises; der findes ingen klartekst-fallback.
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

### 5. Nonce forbruges FØR granten persisteres — **ACCEPTERET (F-1006)**

Scheduler-godkendelsens engangs-nonce konsumeres, og *derefter* skrives
granten. Et crash imellem brænder tokenet uden at der findes en grant.
**Fejlretningen er den sikre:** der kan aldrig opstå en grant uden forbrugt
token, kun et forbrugt token uden grant — og prisen er at brugeren bekræfter
igen. At vende rækkefølgen ville åbne det modsatte (en grant hvis token kan
genbruges), og en distribueret transaktion over to processer er ikke
kompleksiteten værd for et to-minutters engangstoken. Receipt og grant er til
gengæld atomiske i samme transaktion (T-014).

## Rotation & incident

- **Device-token:** `/api/v1/token/rotate` eller CLI; revokér enhed ved tab.
- **Desktop DPAPI-data:** efter skift af Windows-konto eller maskine kan gamle envelopes ikke låses op. Slet de berørte `deviceToken`/`cloudKey`-settings, par desktop igen og indtast cloud-nøglen på ny; appen må ikke forsøge klartekst-fallback.
- **Admin-key:** skift `MODELRIG_ADMIN_KEY` og genstart.
- **Scheduler approval-secret:** generér en ny tilfældig 32+ byte værdi, sæt den identisk i backend og worker, og genstart begge. Alle ikke-forbrugte godkendelsestokens bliver ugyldige.
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

- **Øvrige åbne sikkerhedspunkter ejes af backloggen** — ikke gentaget her:
  cloud-read-egress-beslutningen (T-032, gjort prøvbar via
  `KALIV_EGRESS_GATE` ovenfor), at-rest-beskyttelse af følsomme
  Agent3-memoryværdier (T-033, kræver riggen), fysisk bevis af
  I0b-procesisolering før den agentiske flade udvides, og
  concurrency-modellen ud over single-flight (T-018). Se
  [`BACKLOG.md`](BACKLOG.md).

## Kontrakt: writes (præcisering, 1.58.37)

**Tool-/model-initierede writes er server-gated** (parkeres, godkendelseskort,
TTL, immutable argumenter). **Eksplicit brugerinitierede administrationskald**
(`/models/pull`, `/models/delete` m.fl.) er bearer-beskyttede og
klient-bekræftede — serveren gater dem ikke igen. Enhver klient med gyldig
device-token kan altså kalde dem direkte; det er den bevidste kontrakt, ikke et
hul i tool-gaten. (Cloud-initierede READS er fortsat ugatede — åbent punkt #6.)
