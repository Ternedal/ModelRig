# VALIDATION-1.58.21.md

> **Formål:** on-device-bevis for at det, CI kun kan kompilere/teste, faktisk virker
> på riggen. Udfyld **Resultat** (✅/❌/⏭️ n/a) + **Note** under test. Dette er
> forskellen på "koden ser rigtig ud" og "apparatet er bevist" (9/10-dokumentets §7).

## Testkontekst (udfyld)

| Felt | Værdi |
|---|---|
| Version (APK + server) | 1.58.21 |
| Dato | _____ |
| Hardware | Windows PC, RTX 3060 12GB · Pixel 6a |
| Worker-type | core-exe / Python-worker (ring om) |
| Tester | Anders |

---

## A. Apparatdrift (supervisor + updater)

| # | Test | Fremgangsmåde | Forventet | Resultat | Note |
|---|---|---|---|---|---|
| A1 | Reboot | Genstart Windows, rør intet | Telefon kan chatte uden at åbne en terminal | | |
| A2 | Kill worker | Dræb worker-processen | Supervisor genstarter den; chat virker igen | | |
| A3 | Kill backend | Dræb server-processen | Supervisor genstarter den | | |
| A4 | Kill supervisor | Dræb supervisor-processen | Task Scheduler bringer den tilbage ved næste logon/interval | | |
| A5 | Manglende/forkert env | Fjern `modelrig.env` eller sæt ugyldig `MODELRIG_HOST` | Tydelig fejl i `logs\supervisor.log` — **ikke** en tavs loop | | |
| A6 | Supervisor-log synlig | Kig i `logs\supervisor.log` | Indeholder start/genstart-beskeder + evt. WARNING | | |
| A7 | Env med inline-kommentar | Kopiér `deploy\modelrig.env.example` → `modelrig.env` uændret, start | Serveren binder 0.0.0.0 (ikke `0.0.0.0 # ...`); telefon når den | | |
| A8 | Disk-varsel | (Valgfrit) simulér lav disk / sæt `-min-free-gb` højt | WARNING i supervisor-log, ingen crash | | |
| A9 | Log-rotation `.1` | Lad en child-log passere `-log-max-mb` to gange (genstart) | Anden rotation fejler ikke; gammel `.1` overskrives | | |

## B. Updater (rollback + checksum)

| # | Test | Fremgangsmåde | Forventet | Resultat | Note |
|---|---|---|---|---|---|
| B1 | Normal opdatering | Kør updater mod en nyere release | Backend **og** worker rapporterer ny version; backup gemt | | |
| B2 | Defekt worker | Udgiv/point mod en release med brudt worker | Rollback — updateren beholder ikke opdateringen | | |
| B3 | Forkert checksum | Manipulér et asset så SHA-256 ikke matcher | Installation afvises **før** swap (fail closed) | | |
| B4 | Updater self-upgrade | Følg CAPABILITIES/README's engangs-manual | Ny updater på plads; fremtidige updates verificerer checksum | | |

## C. Privacy & credentials (nyt i 1.58.17–1.58.21)

| # | Test | Fremgangsmåde | Forventet | Resultat | Note |
|---|---|---|---|---|---|
| C1 | Local-first default | Sluk riggen, send en besked i standard-tilstand | **Intet** cloud-kald; fejlen vises. Ingen samtale/billede forlader enheden | | |
| C2 | Billede aldrig fallback | Med auto-fallback slået til (hvis testet): rig nede + vedhæft billede | Billedet sendes **aldrig** via fallback | | |
| C3 | Token krypteret | Frisk pairing → inspicér `modelrig.xml` (adb) | `token_enc` findes; **ingen** klartekst-`token` | | |
| C4 | Token-migrering | Opgradér en gammel installation m. klartekst-token | Migreres ved første start; klartekst forsvinder; pairing holder | | |
| C5 | Profil-token krypteret | Gem en rig-profil → inspicér `modelrig.db` (`rig_profile`) | `device_token`-kolonnen er ciffertekst, ikke læsbar | | |
| C6 | Backup-eksklusion | `adb backup` / inspicér auto-backup | `modelrig.xml` + `modelrig.db` er ekskluderet | | |
| C7 | Token-rotation | Rotér token på riggen (`/token/rotate` / CLI) | Gammel klient mister adgang (401/403) | | |

## D. Agent v2 (chained-writes)

| # | Test | Fremgangsmåde | Forventet | Resultat | Note |
|---|---|---|---|---|---|
| D1 | Ét write | Bed om én handling der kræver et write | Kort vises; godkend → udføres; svar | | |
| D2 | To writes i træk | Bed om noget der kræver to writes (fx "slet model X og skriv en note om det") | **To separate kort**; hvert godkendes for sig | | |
| D3 | Afvis andet write | I D2: godkend første, afvis andet | Andet udføres ikke; korrekt afsluttende svar | | |
| D4 | Audit-log | Åbn Tool-styring | Begge beslutninger (godkend/afvis) er logget korrekt | | |
| D5 | Desktop chained-writes | Gentag D2 på desktop | Samme adfærd: to kort | | |

## E. Capabilities & release-artefakt (nyt i 1.58.20–1.58.21)

| # | Test | Fremgangsmåde | Forventet | Resultat | Note |
|---|---|---|---|---|---|
| E1 | `/capabilities` ærlig | `GET http://<rig>:8099/capabilities` (loopback) el. `/health/full` | `{asr,tts,pdf,docx,cuda}` matcher hvad der faktisk er installeret | | |
| E2 | Release-APK | Installer `kaliv-latest.apk` fra release | Installerer; er release-variant (ikke debug), signeret | | |

## F. Voice & RAG (kernefunktioner)

| # | Test | Fremgangsmåde | Forventet | Resultat | Note |
|---|---|---|---|---|---|
| F1 | Voice ×10 | 10 voice-turns i træk | Alle lykkes; stop/barge-in efterlader intet hængende | | |
| F2 | ASR på GPU | Tjek `/health/full` `asr.device` under en voice-turn | `cuda` (ikke tavst fald til CPU) | | |
| F3 | RAG PDF | Ingest en PDF, stil et spørgsmål | Svar bruger dokumentet | | |
| F4 | RAG DOCX | Ingest en .docx (incl. tabel) | Svar bruger dokumentet | | |

---

## Kendte begrænsninger (forventede — ikke fejl)

- **#2a RAG→cloud-toggle:** ikke-funktionel i UI (fanget i rig-only-menublok). State-machine-redesign udestår. RAG→cloud kan ikke aktiveres via appen endnu.
- **Windows desktop-credentials:** `deviceToken` + `cloudKey` stadig i klartekst-SQLite (DPAPI-handoff udestår).
- **Publiceret worker er core-only:** ASR/TTS/PDF/DOCX kræver Python-worker med deps (F1–F4 forudsætter det). `/capabilities` er ærlig om det.
- **Klient-gating på capabilities:** endpointet findes, men klienterne gater ikke UI på det endnu.
- **Accepteret (SECURITY.md):** committet keystore (solo/sideload), ingen TLS (Tailscale), usigneret SHA-manifest.

## Opsummering (udfyld)

- Bestået: ___ / ___
- Blokkere fundet: _______________________________________________
- Klar til at fortsætte (Release 3 / videre)?  ja / nej
