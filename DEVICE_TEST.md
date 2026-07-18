# Kaliv — device-test runbook

Formålet med denne kørsel: at afprøve på **rigtig hardware** det, som hverken
kode-review, tests eller måling kan nå — koden er rigtig, men opfører den sig
rigtigt mod din rig og din Pixel? Alt herunder er compile-verificeret og
CI-grønt; intet af det er kørt på hardware før nu.

Gå ovenfra og ned. Hvert trin har: **hvad du gør**, **hvad du bør se**, og
**hvis det fejler → hvor du kigger**. Det sidste er det vigtigste — det er
forskellen på en brugbar fejlmelding og "det virkede ikke".

Går noget galt undervejs: se **TROUBLESHOOTING.md** (symptom → årsag → fix, samlet fra faktiske fejl). Hold `/health/full` åben i en fane. Det er din første diagnose ved *alt* nedenfor.

---

## 0. Start rig'en (tre vinduer)

**Genvej:** kør `scripts\start-kaliv.bat` i stedet — den starter alle tre
processer korrekt (inkl. `MODELRIG_HOST=0.0.0.0`) og kører `/health/full` til
sidst. Se `scripts/START_HERE.md`. Trinene herunder er den manuelle vej.

Som HANDOFF §2. Til kold-start-testen i trin 2 er det vigtigt at du **ikke**
tilføjer manuelle PATH-linjer i worker-vinduet — vi tester netop at den ikke
længere er nødvendig.

```cmd
:: Vindue 1
ollama serve

:: Vindue 2 — worker, fra repo-mappen. INGEN manuel PATH-mutation.
cd /d "%USERPROFILE%\Desktop\modelrig-new"
set PYTHONPATH=%CD%\worker
python -m uvicorn app.entrypoint:app --host 127.0.0.1 --port 8099

:: Vindue 3 — server
cd /d "%USERPROFILE%\Desktop"
set MODELRIG_HOST=0.0.0.0
modelrig-server-windows-x64.exe
```

---

## 1. Sundhedstjek først

**Gør:** på riggen,
```cmd
curl http://127.0.0.1:8099/health/full?deep=true
```
(Windows-terminalen viser rå JSON — læsbart nok. Vil du have det pænt:
`curl -s http://127.0.0.1:8099/health/full?deep=true | python -m json.tool`.)

**Bør se:** `"ok": true`, `"faults": []`, og under `checks`:
- `worker.documents` > 0 hvis du har ingesteret noget
- `ollama.ok: true` + `embed_dims` (fra `deep=true`)
- `asr.ok: true` og **`asr.device: "cuda"`** ← afgørende, se trin 2
- `tts.ok: true`
- `tools.enabled: false` (endnu — vi tænder i trin 3)
- `disk.ok: true`

**Fejler noget →** hver check har et `detail`-felt med grunden. Læs det først.
Det er hele pointen med endpointet: du skal ikke gætte hvilken del der er nede.

---

## 1.5 Preflight før den fysiske validering

**Gør:** før du kører selve valideringen (som er tung og forudsætter at *hele*
riggen er oppe korrekt), kør denne — den tjekker hvert led uafhængigt og siger
præcis hvad der mangler, uden at ændre noget:

```cmd
python scripts\rig_preflight.py
```

**Bør se:** en linje pr. afhængighed — token, planner-model, backend på :8080,
worker på :8099, Agent 3-status, `code_sha256`, og workerens egen rapport-view —
og til sidst enten:
- `READY TO VALIDATE` (evt. med et par `WARN` om at der ikke er nogen rapport
  endnu — det er den normale tilstand *før* første kørsel), eller
- `ALREADY VALIDATED` hvis en accepteret rapport allerede findes.

**Fejler noget →** hver `FAIL` har en `->`-linje med præcis hvad du gør. Den
hyppigste er at workeren blev startet **uden** `KALIV_AGENT3_VALIDATION_REPORT`:
sæt variablen, genstart workeren, kør preflight igen. Pointen med preflight er at
du bruger din rig-tid på at *køre* valideringen én gang, ikke på at fejlsøge den.

Når preflight er grøn, kør den rigtige validering:
```cmd
powershell -File scripts\run-agent3-rig-validation.ps1
```

---

## 2. Kold-start af PATH-fixet (v1.12.3)

Den fejl med længst historik i projektet: cuBLAS/CTranslate2 fandt ikke sine
DLL'er, og ASR faldt lydløst tilbage på CPU. Fixet var at *prepende* nvidias
bin-mapper til `os.environ["PATH"]` før modellen initialiseres —
`os.add_dll_directory()` alene var ikke nok.

**Gør:** du startede allerede worker i trin 0 **uden** manuelle PATH-linjer.
Kør nu en rigtig transskription (en kort stemmebesked fra Kaliv, eller
`/voice/asr/transcribe` mod en wav på riggen).

**Bør se:** `asr.device: "cuda"` i `/health/full`, og transskriptionen kommer
tilbage på under et sekund eller to for en kort optagelse.

**Fejler (device: "cpu" eller ImportError om cublas/cudnn) →** så tog fixet
ikke ved kold. Kig i `worker/app/voice_asr.py`: PATH skal *muteres*
(`os.environ["PATH"] = nvidia_bin + os.pathsep + ...`) før `WhisperModel(...)`,
ikke kun `os.add_dll_directory`. Send mig det fulde traceback fra worker-vinduet
— ikke "ASR virkede ikke", men de faktiske linjer.

---

## 3. Agent-lags-runden (hovedtesten)

Dette er det, alt de sidste to dage har handlet om. Tag det i rækkefølge — hvert
punkt tester en specifik release.

### 3a. Grundflow (v1.18–v1.21)
**Gør:** i worker-vinduet, `set KALIV_TOOLS_ENABLED=1` og genstart worker.
I Kaliv: ⋮ → Tools: til. Bed hende: *"Skriv en note om at jeg testede agent-laget i dag."*

**Bør se:** et bekræftelseskort med den foreslåede tekst. Tryk **Godkend**.
Kaliv bekræfter. Åbn ⋮ → Handlingslog: en grøn `EXECUTED note_append`-række.
Tjek på riggen at `~/Documents/Kaliv/notes.md` (eller din `KALIV_TOOLS_DIR`)
faktisk fik linjen.

**Fejler →** `/health/full` → `tools.enabled` skal være `true` nu. Hvis kortet
ikke kommer: er modellen en der understøtter tool-calling (hermes3:8b, ikke
llama3.2:1b)? Send worker-loggen.

### 3b. Kill switchen slår et åbent kort (v1.24)
**Gør:** bed om en note igen, men **inden** du godkender kortet: ⋮ → Tool-styring
→ slå tool-laget fra. Gå så tilbage og tryk Godkend på det gamle kort.

**Bør se:** handlingen kører **ikke**. Handlingsloggen viser en `BLOCKED`-række.
Bremsen er den seneste beslutning og skal vinde.

### 3c. Bremsen overlever genstart (v1.28)
**Gør:** med tool-laget slået fra (fra 3b), genstart worker-vinduet. Husk: du
har `KALIV_TOOLS_ENABLED=1` sat.

**Bør se:** `/health/full` → `tools.enabled: false` **stadig**. Env-varen er kun
første-kørsel-default; din beslutning i appen overlever. (Vil du nulstille: slet
`kaliv-tools-state.json`.)

### 3d. Historik i tools-tilstand (v1.25)
**Gør:** tænd tools igen. Hav en kort samtale ("hvad er 2+2?" → svar). Bed så:
*"Skriv det ned, vi lige talte om."*

**Bør se:** hun ved hvad "det" er. Fejler hun her, mistede tools-grenen
historikken — send mig samtalen.

### 3e. RAG + tools (v1.26)
**Gør:** ingestér et kort dokument. Slå både RAG og Tools til. Stil et spørgsmål
om dokumentets indhold, og bed hende skrive svaret som en note.

**Bør se:** svaret er grundet i dokumentet (kilde-chips vises), og en note kan
foreslås. Kortet skal stadig kræve din godkendelse.

### 3f. Cloud gennem riggen (v1.22)
**Gør:** skift til cloud-model, hold Tools til. Bed om en note.

**Bør se:** kortet siger **"Cloud-modellen foreslår:"**, og handlingsloggen viser
et ☁ på rækken.

### 3g. Kort overlever ikke samtaleskift (v1.27.1)
**Gør:** få et kort frem, og **skift samtale** før du godkender.

**Bør se:** kortet er væk. Det må ikke hænge og pege på den forrige samtale.

---

## 4. Brand (v1.12.4–v1.17)

**Gør:** kig på launcheren, åbn appen koldt, gå gennem skærmene.

**Bør se:** ankh-ikonet på launcheren (og som tema-ikon på Android 13+),
den varme palet (charred black / ember bronze / muted ivory — ikke safir-blå),
splash med ankh på sort, og velkomstskærmen med "Lokal intelligens. Privat."

**Fejler (stadig blåt et sted) →** noter *hvilken* skærm. Desktop er stadig
safir-blå med vilje — det er ModelRig, ikke Kaliv.

---

## 5. Voice (v1.13, v1.15)

**Gør:**
- Under afspilning: tryk ⏹ (tap-to-stop). Bør stoppe på ~200 ms.
- Barge-in-kalibrering med headset: åbn kalibreringen, aflæs RMS-toppen mens du
  taler, sæt tærsklen lige over din stilhed.

**Fejler →** send RMS-tallene du så; tærsklen er justerbar netop fordi den
afhænger af dit headset og rum.

---

## 6. Backup (v1.30)

**Gør:** registrér den planlagte opgave (én gang, som admin), kør den manuelt,
og bevis en restore ind i en midlertidig mappe (så du ikke rører live-data):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\kaliv-backup-scheduled.ps1
Start-ScheduledTask -TaskName KalivBackup
dir .\backups

:: bevis restore uden at røre rig'en:
python -m worker.app.backup verify .\backups\<nyeste>.tar.gz
```

**Bør se:** et `kaliv-backup-*.tar.gz` i `.\backups`, og `verify` siger
`"ok": true`. Det er den sidste brik i V7's exit-kriterium: restore bevist på
selve maskinen, ikke kun i CI.

**Fejler (Scheduled Task kører ikke) →** `Get-ScheduledTask -TaskName KalivBackup`
for status. Windows-stierne i scriptet kan trænge til at pege på din faktiske
repo-mappe — send fejlen.

---

## 7. Hvad du sender tilbage til mig

For hvert trin der fejlede, ikke "det virkede ikke", men:
1. Trin-nummeret (fx **3b**).
2. Den relevante `/health/full`-udskrift på det tidspunkt.
3. De faktiske linjer fra worker-vinduet (traceback, ikke parafrase).
4. Hvad du forventede vs. hvad du så.

Så retter jeg det, der faktisk er i stykker — i stedet for at gætte. Det er
hele grunden til at denne runde er mere værd end den næste release.

---

## 12/7 aften — streamende voice (v1.54.0–1.55.0)

Det store åbne testpunkt. **Forudsætning:** worker genstartet med v1.54.0+
(streamingen er worker-side; en gammel worker giver 404 på stream-endpointet
og appen fejler — så genstart workeren FØRST).

### S1. Grundtest: taler den før svaret er færdigt?

**Gør:** rig-mode, voice-cloud TIL med en stor model (deepseek-671b — netop
fordi den er langsom, er effekten tydelig). Stil et spørgsmål der giver et
langt svar ("fortæl mig om Mandø").
**Bør se:** transskriptionen dukker op først; assistent-boblen fyldes
sætning for sætning; **lyden starter efter første sætning** — ikke efter
hele svaret. Med 671b: sekunder til første sætning i stedet for ½-1 minut.
**Hvis fejl →** worker-konsollen (kører den v1.54.0+? fejler
/voice/converse/stream?), og prøv det bufrede fallback ved at rulle app
tilbage til v1.53.0 (endpointet er urørt).

### S2. Gap/overlap mellem sætninger

**Gør:** lyt til overgangene i et 4-5-sætningers svar.
**Bør se:** små naturlige pauser (TTS-latens pr. sætning), ingen overlap,
ingen sætninger der mangler eller kommer i forkert rækkefølge.
**Hvis fejl →** noter HVILKET mønster (gap-længde? overlap? rækkefølge?) —
det afgør om fixet er i afspiller-køen (app) eller chunk-timingen (worker).

### S3. Barge-in + stop midt i streamen

**Gør:** afbryd ved at tale (barge-in) og ved ⏹ — begge MIDT i et streamet svar.
**Bør se:** lyden stopper hurtigt; ingen efterfølgende sætninger spiller;
RMS-meteret opdaterer sig UNDER talen (fix fra v1.55.0); appen er straks klar.
**Hvis fejl →** er det afspilningen der fortsætter (kø-dræning) eller
netværket der læser videre? Skærmbillede af tilstanden hjælper.

### S4. Persistens efter streamet tur

**Gør:** luk samtalen, åbn den igen.
**Bør se:** transskription som bruger-besked + hele svaret som assistent-
besked, uden emojis (strip ved indlæsning), med 🎙-model-chip.
**Hvis fejl →** var svaret tomt/kun markup? (så skal assistent-rækken
mangle med vilje — det er korrekt adfærd, ikke en fejl).
