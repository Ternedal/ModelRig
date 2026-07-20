# Kaliv — fejlsøgning

Symptom → sandsynlig årsag → tjek → fix. Alt herunder er noget vi faktisk ramte
under test. **Start altid med `/health/full`** (launcheren kører det, eller
`curl http://127.0.0.1:8099/health/full`). Læs den faktiske fejl før du retter.

---

## Appen: "modellen svarede ikke i tide" på HVER besked (også "hej")

- **Årsag (hyppigst):** tool-laget er slået fra på riggen. Det er fra som
  standard (opt-in). Appen viste det før misvisende som en timeout.
- **Tjek:** `curl http://127.0.0.1:8099/tools/chat -H "Content-Type: application/json" -d "{\"message\":\"hej\",\"model\":\"hermes3:8b\"}"`
  → hvis svaret er `{"detail":"the tool layer is disabled"}`, er det dét.
- **Fix:** start workeren med `set KALIV_TOOLS_ENABLED=1` før uvicorn. (Den nye
  `start-kaliv.bat` gør det automatisk.)
- **Anden mulig årsag:** telefonen når slet ikke riggen (se afsnittet om 401 /
  cloud-fallback). En ægte timeout er sjælden — modellen svarer typisk på
  sekunder; bekræft med `ollama run hermes3:8b "hej"`.

## Appen: "Ikke godkendt. Parringen er nok udløbet" (401)

- **Betydning:** telefonen NÅR riggen (godt!), men serveren afviser tokenet.
- **Årsag:** device-tokens ligger i `modelrig-data.json`. Før v1.34.14 var stien
  relativ til opstartsmappen, så en server startet fra en anden mappe end der
  hvor du parrede, læste en tom/anden fil → 401. Fra v1.34.14 ankres filen på
  exe'ens mappe (se `device store: <sti>` i server-loggen ved opstart).
- **Fix:** kør v1.34.14+ serveren, og genpar under ⋮ → Indstillinger. Parring er
  åben i dev-mode (`MODELRIG_ADMIN_KEY` unset), så det er hurtigt.

## Appen svarer "via cloud (rig utilgængelig)" — når slet ikke riggen

- **Årsag:** serveren lytter ikke på en adresse telefonen kan nå.
- **Tjek på riggen:** `curl http://<rig-adresse>:8080/health`. Timeout = serveren
  binder ikke rigtigt.
- **Almindelige fælder:**
  - `MODELRIG_HOST` ikke sat til `0.0.0.0` → serveren binder kun til loopback.
    **Sæt den på sin EGEN linje**, ikke `set MODELRIG_HOST=0.0.0.0 && exe`
    (batch fanger et efterfølgende mellemrum → "lookup 0.0.0.0 : no such host").
    v1.34.10+ trimmer det defensivt.
  - Appen parret med forkert adresse: rig på Tailscale (100.x) men parret med
    LAN (192.168.x), eller omvendt. Par med den adresse riggen FAKTISK er på.
    Tailscale-IP: `tailscale ip -4` på riggen.

## Launcheren crasher: "... was unexpected at this time"

- **Årsag:** cmd mis-parser parentes-blokke med indlejrede citationstegn / bare
  `&`. Rettet i v1.34.13 (goto-labels + genererede .cmd-filer).
- **Fix:** hent v1.34.13+ `start-kaliv.bat`.

## Worker: "[Errno 10048] ... kun bruges én gang" (port 8099)

- **Årsag:** en gammel worker kører allerede på 8099.
- **Fix:** luk det gamle worker-vindue først. v1.34.13+ launcheren advarer i
  stedet for at kollidere.

## Modellen "gør" noget den ikke gør (skriver note / skifter sprog i prosa)

- **Symptom:** "Sure, I've created the note" men ingen fil; eller "I'll speak
  Danish" og fortsætter på engelsk.
- **Årsag:** IKKE en kode-fejl. Workeren udfører KUN på strukturerede
  `tool_calls`, aldrig på prosa — så intet falsk sker. Men hermes3:8b (8B)
  hallucinerer handlinger og glemmer instruktioner. Iboende for små modeller.
- **Fix (delvist):** sæt en system-prompt (⋮ → Indstillinger → rolle-feltet),
  fx "Svar altid på dansk. Kald værktøjer i stedet for at beskrive dem." Det
  tilter oddsene men fjerner det ikke.
- **Ægte fix:** en større / mere instruktionstro model på agent-stien, eller en
  cloud-model gennem riggen (bærer allerede bekræftelses-gaten).

## Schedule-job står som "cancelled" med en dansk grund

- **Symptom:** et scheduled job ender `cancelled` med "planen blev pauset,
  ændret eller slettet efter claim; occurrence annulleret og budget-slot
  refunderet".
- **Årsag:** IKKE en fejl — det er revocation-guarden (T-013). Du pausede,
  fornyede eller slettede planen EFTER at occurrencen var claimet men FØR den
  nåede ToolGate. Den stalede occurrence annulleres, slotten refunderes, og
  planen kører videre under sine nye vilkår ved næste due-tid.
- **Handling:** ingen. Tjek evt. `runs_used` i `GET /schedules/{id}` — den er
  refunderet.

## Kampagne-script siger "not a git repo" / "git HEAD is unavailable"

- **Symptom:** `freeze_check`/`rig_preflight`/kampagnen fejler med en
  git-fejl på riggen.
- **Forklaring:** riggen er gitless (ZIP-workflow). Fra 1.58.131 håndterer
  værktøjskæden det selv: kør `python scripts\freeze_check.py` FØRST — i
  gitless-mode løser den identiteten via GitHub-API'et (kræver
  `GITHUB_TOKEN`) og skriver `validation\frozen-candidate.json`, som
  preflight og aggregatoren derefter læser. Ser du fejlen alligevel, mangler
  attestationsfilen: kør freeze_check igen og bekræft FROZEN.
- **Før 1.58.131** antog hele kæden en git-klon og døde på operatørens
  allerførste kommando.

## /plan svarer 422: "planner response has unsupported top-level fields"

- **Symptom:** model_eval (eller et manuelt /plan-kald) får 422 med denne
  tekst, mens andre tasks lykkes.
- **Betydning:** planner-modellens output brød den typede kontrakt (ekstra
  felter på topniveau). Workeren afviser fail-closed frem for at gætte.
  Det er en egenskab ved MODELLEN, ikke ved kæden — små modeller
  (fx qwen2.5:0.5b i sandkasse-smoke) rammer den ofte; evalen tæller det
  som request_error og exit 1.
- **Handling:** kør med den tiltænkte planner-model (qwen3:14b på riggen).
  Vedvarende 422 dér er et ægte eval-fund om modellens disciplin.

## Worker-log ved start: "recovered N executed / M abandoned / K unknown"

- **Symptom:** linjen dukker op ved worker-start. **(Synlig fra 1.58.130 —
  før da nåede kun WARNING-niveauet loggen, så en ren-crash-recovery kørte
  lydløst. Fundet ved generalprøven af piloten.)**
- **Årsag:** crash-recovery (T-012/F-1002). Workeren døde midt i en occurrence.
  `executed` = audit-evidens viste at side-effekten NÅEDE at køre — budgettet
  forbliver brugt, jobbet afstemmes til completed. `abandoned` = intet nåede
  at køre — slotten refunderes, hængende job lukkes failed. `unknown` = døde
  MELLEM forsøgs-markøren og resultatet: side-effekten KAN være sket, slotten
  BEHOLDES (refusion kunne give flere kørsler end max_runs), og planen pauses.
- **Handling:** `executed`/`abandoned` én gang efter kendt crash: normalt.
  `unknown` > 0: afklar manuelt om handlingen skete (fx om noten findes), og
  genoptag planen bagefter (resume starter ved en frisk fremtidig occurrence).
  "recovery sprunget over — en anden ejer holder lease'en": to worker-processer
  mod samme DB — den nye venter til den gamles lease udløber (90 s) eller
  stoppes rent. HVER start: workeren crasher i selve tick-løkken — kig i
  loggen umiddelbart FØR linjen.

## GET /schedules/{id}: tom `approval_receipts`

- **Symptom:** ingen receipts på et schedule.
- **Årsag:** reads har pr. design ingen (kræver ingen godkendelse). Writes
  oprettet FØR receipts-leveringen (1.58.123) har heller ingen — historikken
  starter der. Et NYT write-schedule uden mindst én receipt kan ikke
  eksistere: create ruller tilbage hvis receipt-inserten fejler.
- **Handling:** gamle writes: fornys planen (renew appender en receipt med
  bumpet revision). Nyt write uden receipt: det er en ægte fejl — meld den.

## CI: release med 0 assets / build-jobs fejler med tomme logs

- **Årsag:** GitHub Actions storage/kvota for et PRIVAT repo er opbrugt. Jobs
  der uploader fejler; `server-tests` (uploader ikke) består. Logs giver
  `BlobNotFound`.
- **Tjek:** `github.com/settings/billing` → Actions / Storage.
- **Fix:** gør repo public (gratis ubegrænset), eller vent til kvoten nulstilles
  (1. i faktureringsmåneden), eller byg APK'en lokalt på riggen.

## Første svar er meget langsomt, derefter hurtigt

- **Årsag:** kold model-load (~5 GB ind i 3060) ved første kald.
- **Afhjælpning:** `keep_alive` (v1.34.7, default 30m) holder modellen resident
  mellem ture, så kun første load betaler. `MODELRIG_OLLAMA_KEEP_ALIVE=-1`
  pinner den permanent.

## ASR falder tilbage til CPU (langsom transskription)

- **Tjek:** `/health/full` → `asr.device`. Skal være `cuda`, ikke `cpu`.
- **Årsag:** cuBLAS/CTranslate2 finder ikke sine DLL'er (Windows PATH). Fixet i
  v1.12.3 (prepender nvidia-bin til PATH før modellen loades).
- **Hvis cpu:** send worker-loggens traceback — det er en PATH/DLL-sag.

## RAG-dokumenter "forsvinder" / kill-switch nulstiller sig / audit-log har huller

- **Symptom:** ingesteret viden er pludselig væk, eller Tools er tændt igen efter
  du slog det fra, eller handlingsloggen mangler rækker.
- **Årsag:** før v1.34.15 defaultede RAG-index, tools-state og audit-DB til
  RELATIVE stier (som 401-fælden). Startet workeren fra en anden mappe → en
  anden/tom fil. Fra v1.34.15 ankres alt under en stabil data-rod
  (`%LOCALAPPDATA%\Kaliv`, eller `KALIV_DATA_DIR`). Se `data_root=<sti>` i
  worker-loggen ved opstart.
- **Fix:** kør v1.34.15+ workeren. Gamle filer i tidligere opstartsmapper kan
  flyttes ind i data-roden hvis du vil beholde dem.

## Voice med cloud timer ud — men almindelig cloud-chat virker fint

Klassikeren fra 12/7. Årsag: workerens LLM-kald sendte `keep_alive` (en
LOKAL-VRAM-direktiv) til Ollama Cloud, som hang requesten. Almindelig cloud-chat
virkede præcis fordi appens CloudClient aldrig sender `keep_alive`. Fixet i
v1.50.0 (keep_alive sendes kun til den lokale rig; T31 mutations-tjekket).
**Hvis det opstår igen:** tjek at workeren kører v1.50.0+, og at ingen ny
kode-sti sender lokale Ollama-parametre til et cloud-upstream.

## Desktop/Android crasher med SQLITE_CONSTRAINT_FOREIGNKEY ved sletning

At slette den samtale man STÅR i: convId pegede stadig på den slettede samtale,
så næste besked-insert brød foreign key'en. Fixet i v1.46.0 på begge platforme
(aktiv convId nulstilles via callback + addMessage guarder eksistens). **Mønstret
generelt:** enhver "slet det aktive X"-operation skal nulstille den aktive
peger FØR næste skrivning.

## Kaliv er en emoji-drukdnet "hygge-bot" / svarer med forkert tone

To lag: (1) standard-systemprompten var TOM, så modellen improviserede
kundeservice-fyld — fixet med DEFAULT_SYSTEM-personaen (v1.43-44, gemt-tom =
brug default). (2) Små lokale modeller (selv qwen3:14b) IGNORERER "ingen
emojis"-instruktioner — derfor deterministisk klient-side emoji-strip på
færdige svar + ved indlæsning af gamle (v1.45/48). **Lektien:** promptning
alene tøjler ikke en lille models indgroede vaner; deterministisk
efterbehandling gør.

## Voice bruger en anden model end den valgte

Før v1.45.0 sendte appen `model=null` for ikke-cloud voice → workeren faldt
tilbage til GEN_MODEL (qwen2.5-coder — kodemodel, halv-norsk vrøvl). Nu sendes
den valgte rig-model, og voice-cloud har sin EGEN model (voiceCloudModel,
v1.52.0). **Tjek routing-striben** under headeren: den viser altid hvilken
model der svarer tekst og tale, og om cloud er i spil.

## freeze_check siger "NOT release commit" eller afviser attestationen

Træ-bindingen (1.58.132) sammenligner HVER committet fil i det udpakkede
ZIP-træ mod release-committens git-tree via API'et. "NOT release commit: N
mismatched, M missing" betyder at dine lokale bytes IKKE er releasen — typisk
en redigeret fil eller en forkert/gammel ZIP. Løsning: hent den officielle
source-ZIP for tagget igen og start fra en urørt udpakning. Attestations-
afvisninger fra campaign/preflight navngiver altid feltet: "mangler felter"
(gammel v1-fil → kør freeze igen), "timer gammel" (>24t — kør freeze igen på
SELVE rig-dagen), "fingerprint matcher ikke" (træet er ændret EFTER freeze,
eller filen er fabrikeret — hent ZIP + kør freeze forfra). "rollup-digest matcher ikke" (v3, 1.58.136: en committet fil HVOR SOM
HELST i træet er ændret efter freeze — hent ZIP + kør freeze forfra),
"ukendte felter" (fremmed/nyere fil afvises fremfor at ignoreres), og
"NOT in the release tree" ved freeze (en ekstra lokal fil — en frisk ZIP
har nul extras). Rediger aldrig
`validation/frozen-candidate.json` i hånden; den er bevismateriale, ikke
konfiguration.

## Streamende voice: sætninger mangler / meter frosset / forkert transskription gemt

v1.54.0's streaming havde tre samtidigheds-bugs fundet i selv-audit (v1.55.0):
tabt RMS-meter-polling, race på replyIdx (hurtig første sætning kunne miste
tekst), skrøbelig transcript-gendannelse. Alle fixet. **Hvis streaming driller
on-device:** det bufrede endpoint (`/voice/converse/upload`) er urørt — app-
siden kan rulles tilbage til det uden worker-ændringer.
