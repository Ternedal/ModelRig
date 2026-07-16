# VALIDATION-1.58.49.md

**Status:** AFVENTER KØRSEL · resultatfelter tomme · gælder 1.58.49+ · **Ejer:** Anders (rig + telefon)

> **Formål:** on-device-bevis for alt det, CI kun kan kompilere/unit-teste.
> Udfyld **Resultat** (✅/❌/⏭️) + **Note** under test. Dette er porten mellem
> "CI-grøn" og "tør stole på det" — og den er nu ajour med hvad der faktisk er
> bygget (afløser VALIDATION-1.58.49.md; 13 releases er landet siden).
>
> **Genvej:** `deploy\validate-rig.ps1` kører de mekaniske Windows-tjek
> (A0/A5, journal/lock, B4/B7, og A2–A4 med `-Destructive`) og gemmer en
> paste-klar blok i `logs\validate-rig-latest.md`. Resten er telefon + hænder.
>
> 🆕 = ny eller ændret siden 1.58.36.

## Testkontekst (udfyld)

| Felt | Værdi |
|---|---|
| Version (APK / server / worker / updater) | 1.58.49 / APK versionCode **179** |
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
| A5 | `logs\supervisor-heartbeat` | Går FREMAD (ikke bare eksisterer) | | |
| A6 | Env med inline-kommentar (kopiér example uændret) | Server binder 0.0.0.0; telefon når den | | |

## B. Updater — transaktion & recovery

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| B1 | Normal opdatering til nyeste release | Alle tre på ny version; journal arkiveret som `committed` | | |
| B2 | Kør updateren igen | "already up to date"; ingen sideeffekter | | |
| B3 | **Kill updateren midt i swap** | Næste kørsel: whole-set-recovery; ingen blandede versioner | | |
| B4 | `-recover` offline (netværk fra) | Reparerer/arkiverer uden netværk | | |
| B5 | Defekt update (brudt worker) | Rollback; `rolled_back` arkiveres FØRST når gammel runtime er bevist (versioner + heartbeat) | | |
| B6 | Manipulér et checksum | Afvises FØR swap | | |
| B7 | To updaters samtidig | Nr. 2 fejler lukket på `updater.lock` | | |
| B8 | Korrumpér `update-transaction.json` | Task + processer stoppes konservativt; fejler lukket; evidens bevaret | | |
| B9 | Updater-exe'ens egen version | **Kendt:** self-update findes ikke — manuel udskiftning (UPDATER_DESIGN §4a) | | |

## C. Privacy & credentials

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| C1 | Rig slukket, defaults, send besked | INGEN cloud-kald; ærlig fejl | | |
| C2 | `modelrig.xml` efter frisk pairing | `token_enc` m. **`enc:v1:`-prefix**, ingen klartekst | | |
| C3 | Opgradér gammel installation | Legacy-token migreres; pairing holder | | |
| C4 | 🆕 Ødelæg en krypteret profil-værdi (adb, skift ét tegn) | Profilen kræver **re-pairing** — bliver ALDRIG "migreret" som plaintext | | |
| C5 | `adb backup` / auto-backup | `modelrig.xml` + `modelrig.db` ekskluderet | | |

## D. Tools, samtykker & agent

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| D1 | Ét write → godkend | Kort → udføres → svar | | |
| D2 | To writes i træk | TO kort; hver godkendes for sig | | |
| D3 | Godkend første, afvis andet | Andet udføres ikke | | |
| D4 | Retry af en tools-tur (rig nås) | Retry kører TOOLS-ruten igen — kort som normalt | | |
| D5 | Cloud+tools på 4G (rig kan ikke nås) | Hurtig, klar fejl med valget stavet ud — intet hæng | | |
| D6 | Samme, Tools slået fra | Cloud svarer direkte | | |
| D7 | 🆕 **⋮-menuen** | To nye toggles synlige: "Dokumentviden → cloud" og "Auto cloud-fallback" | | |
| D8 | 🆕 Slå begge til → luk app → åbn igen | Tilstand **overlevede genstart** (persisteret, ikke session) | | |
| D9 | 🆕 Begge FRA: normal chat + RAG + tools | Adfærd **uændret** fra i går | | |
| D10 | 🆕 "Dokumentviden → cloud" TIL + cloud + tools + RAG | Dokumentuddrag sendes til cloud-modellen via tools-ruten (**tilsigtet** — det er hvad D4-samtykket betyder; verificér at det kun sker når toggle er TIL) | | |

## E. Streams — må aldrig lyve (1.58.49)

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| E1 | Cloud-chat på 4G, flere sends | Svar kommer; net-blips auto-retryes | | |
| E2 | **Stop** midt i et svar | Stopper omgående; ingen ny request bagefter | | |
| E3 | glm-4.7 / deepseek (reasoning) | Direkte svar; ingen tavshed | | |
| E4 | gpt-oss:120b | Svar (think:"low") | | |
| E5 | Ugyldigt modelnavn | ÆGTE fejltekst | | |
| E6 | 🆕 **Normal rig-chat** | Fuldfører som altid (klienten er blevet STRENGERE — hvis den nu fejler, er det et ægte fund) | | |
| E7 | 🆕 **RAG-chat** | Kildechips + svar; fuldfører | | |
| E8 | 🆕 **Voice-tur** | Transskription → tale → afsluttes; **ingen evig spinner** | | |
| E9 | 🆕 Afbryd en rig-chat undervejs (sluk Tailscale/wifi midt i svaret) | Klar fejl om **afbrudt** svar — ikke et afkortet svar der ser færdigt ud, og det gemmes ikke i samtalen | | |

## F. Jobs (1.58.47) 🆕

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| F1 | Bed modellen hente en model (tools til) | Svar med **job-id** + besked om `job_status` | | |
| F2 | Spørg "hvordan går downloaden?" | `job_status` viser running + progress% | | |
| F3 | Bed om at annullere jobbet | `cancel_job` → status `cancelled`, download stopper | | |
| F4 | Genstart workeren midt i et pull | Jobbet står som **`interrupted`** med ærlig tekst — ikke "running" for evigt | | |
| F5 | Lad et pull køre færdigt | Status `completed` **først** når modellen er i modeloversigten | | |

## G. Grænser & pairing (1.58.46) 🆕

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| G1 | Upload en PDF større end `KALIV_MAX_UPLOAD_MB` (default 25) | **413** med klar besked — riggen bruger ikke hukommelse på den først | | |
| G2 | `modelrig-server -pair` **mens serveren kører**, fra en anden mappe | Koden udstedes af den kørende server og virker på telefonen (ingen 401) | | |
| G3 | `modelrig-server -pair` med serveren **stoppet**, fra en anden mappe | Skriver til den exe-forankrede store; start serveren → koden virker stadig | | |
| G4 | Bekræft at worker starter via `app.entrypoint` (ikke `app.main`) | Launcher/README peger på entrypoint = guarden er aktiv | | |

## H. Isolation (1.58.48, dormant) 🆕

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| H1 | Normal drift | Uændret — substratet er dormant (`isolate` sat på nul tools) | | |
| H2 | Sæt `KALIV_TOOL_ISOLATION=process`, genstart worker, kør tools | **Alt virker som før** (delegation) — beviser at flaget er sikkert at have | | |
| H3 | Voice + RAG med flaget sat | Uændret | | |

## I. RAG (1.58.40) + kalibrering

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| I1 | Ingest PDF + DOCX → spørg | Svar bruger dokumenterne | | |
| I2 | 🆕 **Gen-ingest samme fil** (fx opdateret PDF) | Chunk-antal **stabilt**, svar bruger det NYE indhold, ingen dubletter | | |
| I3 | 🆕 Scannet PDF (uden tekstlag) | Ærlig **422** — ikke tavs tom indeksering | | |
| I4 | 🆕 **Kalibrering** (RAG_DESIGN §5): 5 spørgsmål du VED står i dokumenterne + 3 der ikke gør | Notér misses/støj → afgør om `min_score=0.3` / `top_k=4` / chunk 800/150 skal justeres | | |

## J. Capabilities & voice

| # | Test | Forventet | Resultat | Note |
|---|---|---|---|---|
| J1 | `GET :8099/capabilities` | Matcher installerede deps | | |
| J2 | Voice ×10 i træk | Alle lykkes; barge-in efterlader intet hængende | | |
| J3 | `/health/full` (m. token) | `ok: true` | | |

---

## Kendte begrænsninger (forventede — ikke fejl)
- **#2a trin 3–5**: toggles bevarer ikke tilstand på tværs af mode-skift endnu; intet samtykke-KORT (kun menu-toggle); `useRagCloud`-ruten er dormant (CLIENT_STATE_DESIGN §4).
- **I0b**: Windows-rettighedslaget (Job Object/reduceret token/lav integritet) mangler — uden Job Object reapes børnebørn ikke ved kill (ISOLATION_DESIGN §5).
- **Klient-gating på capabilities** mangler · **desktop-credentials klartekst** (DPAPI-handoff klar) · **updater self-update** mangler · **cloud-reads ugatede** (#6 — Agent 3 er svaret).

## Opsummering (udfyld)
Bestået: ___ / ___ · Blokkere: _____________________ · Klar til 1.59-RC? ja/nej
