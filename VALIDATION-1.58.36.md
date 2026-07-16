# VALIDATION-1.58.36.md

> **Formål:** on-device-bevis for alt det, CI kun kan kompilere/unit-teste.
> **Genvej:** `deploy\validate-rig.ps1` automatiserer de mekaniske tjek (A0/A5,
> journal/lock, B4/B7, og A2–A4 med `-Destructive`) og gemmer en paste-klar
> resultatblok i `logs\validate-rig-latest.md`. Telefondelene er stadig manuelle.
> Udfyld **Resultat** (✅/❌/⏭️) + **Note** under test. Dette er den sidste store
> ting mellem 8,4 og 9+ — auditsene har sagt det samme siden første runde.

## Testkontekst (udfyld)

| Felt | Værdi |
|---|---|
| Version (APK + server + updater) | 1.58.36 |
| Dato | _____ |
| Hardware | Windows PC, RTX 3060 12GB · Pixel 6a |
| Worker-type | core-exe / Python-worker (ring om) |

---

## A. Apparatdrift

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| A1 | Reboot Windows, rør intet | Telefon kan chatte uden terminal | | |
| A2 | Dræb worker-processen | Supervisor genstarter den | | |
| A3 | Dræb server-processen | Supervisor genstarter den | | |
| A4 | Dræb supervisoren | Task Scheduler bringer den tilbage | | |
| A5 | `logs\supervisor-heartbeat` | Opdateres løbende (ms-tal stiger) | | |
| A6 | Env med inline-kommentar (kopiér example uændret) | Server binder 0.0.0.0; telefon når den | | |

## B. Updater — transaktion & recovery (nyt siden 1.58.29)

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| B1 | Normal opdatering til nyeste release | Backend+worker+supervisor på ny version; journal væk, `update-transaction.json.last` findes (`committed`) | | |
| B2 | Kør updateren igen bagefter | "already up to date"; ingen sideeffekter | | |
| B3 | **Kill updateren midt i en update** (task manager under download/swap) | Næste kørsel: whole-set-recovery ruller ALT tilbage; riggen kører gammel version; ingen blandede versioner | | |
| B4 | `modelrig-updater.exe -recover` (offline, netværk fra) | Reparerer/arkiverer uden netværk; riggen intakt | | |
| B5 | Defekt update (peg mod release med brudt worker, hvis muligt) | Rollback; `rolled_back` arkiveres FØRST når gammel backend+worker+heartbeat er bevist | | |
| B6 | Manipulér et assets checksum | Afvises FØR swap (fail closed) | | |
| B7 | Start to updaters samtidig | Nr. 2 fejler lukket på `updater.lock` | | |
| B8 | Korrumpér `update-transaction.json` (skriv vrøvl) + kør updater | Task+processer stoppes konservativt; updater fejler lukket; evidens bevaret | | |
| B9 | Updater-exe'ens egen version | **Kendt begrænsning:** self-update findes ikke — manuel udskiftning (design §4a) | | |

## C. Privacy & credentials

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| C1 | Rig slukket, default-indstillinger, send besked | INGEN cloud-kald; fejl vises. Intet forlader enheden | | |
| C2 | `modelrig.xml` (adb) efter frisk pairing | `token_enc`, ingen klartekst-token | | |
| C3 | Opgradér gammel installation m. klartekst-token | Migreres; pairing holder | | |
| C4 | `adb backup` / auto-backup | `modelrig.xml` + `modelrig.db` ekskluderet | | |

## D. Agent v2 & tools (inkl. 1.58.36-semantik)

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| D1 | Ét write → godkend | Kort → udføres → svar | | |
| D2 | To writes i træk | TO separate kort; hver godkendes for sig | | |
| D3 | Godkend første, afvis andet | Andet udføres ikke; korrekt afslutning | | |
| D4 | **Retry af en tools-tur (hjemme/rig nås)** | Retry kører TOOLS-ruten igen — tool-kort som normalt, ikke plain chat | | |
| D5 | **Cloud+tools på 4G (rig kan ikke nås)** | Hurtig, klar fejl med valget stavet ud — INTET hæng, ingen tavs downgrade | | |
| D6 | Samme, men slå Tools fra | Cloud svarer direkte | | |

## E. Cloud-robusthed (1.58.34–36)

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| E1 | Cloud-chat på 4G, flere sends med pauser | Svar kommer; net-blips auto-retryes (ingen manuel "prøv igen" nødvendig) | | |
| E2 | Tryk **Stop** midt i et svar | Stopper omgående; ingen ny request affyres bagefter | | |
| E3 | glm-4.7 / deepseek (reasoning) | Direkte svar (think:false); ingen 3-min-tavshed | | |
| E4 | gpt-oss:120b | Svar (think:"low"-politik) | | |
| E5 | Ugyldigt modelnavn | ÆGTE fejltekst (ikke timeout/tavshed) | | |

## F. Capabilities, voice & RAG

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| F1 | `GET :8099/capabilities` | Matcher faktisk installerede deps | | |
| F2 | Voice ×10 i træk | Alle lykkes; barge-in efterlader intet hængende | | |
| F3 | RAG PDF + DOCX ingest → spørgsmål | Svar bruger dokumenterne | | |

---

## Kendte begrænsninger (forventede — ikke fejl)
- **#2a RAG→cloud-toggle** ikke-funktionel (state-machine-redesign udestår) · **klient-gating på capabilities** mangler · **desktop-credentials klartekst** (DPAPI-handoff klar) · **updater self-update** mangler (design §4a) · retry af en tools-tur har intet billede med (originalens billede er forbrugt).

## Opsummering (udfyld)
Bestået: ___ / ___ · Blokkere: _____________________ · Klar til 1.59-RC? ja/nej
