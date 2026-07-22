# ModelRig — klient-build og røgtest (handoff)

> **⚠️ HISTORISK DOKUMENT (7/7).** Præmissen — "klienterne er aldrig bygget,
> intet SDK i byggemiljøet" — er død: CI bygger APK + Windows-jar + exes på HVER
> release (6 assets), og worker-suiten er 298 tests, ikke 90. Byggetrinnene
> herunder kan stadig bruges til LOKALT byg, men se README "Run order" +
> HANDOFF §9 for den aktuelle vej.

Alt server-side (backend + worker + CLI) er kompileret og testet: 90 assertions
grønne. **Det eneste, der ikke er verificeret, er de to Kotlin-klienter** (desktop
+ Android), fordi der ikke var Kotlin/Gradle/Android SDK i byggemiljøet. De er
skrevet til at kompilere, men første build på din maskine er den rigtige test.

Dette dokument er den checkliste, du kører når du sætter dig ned. Rækkefølge:
**stå server op → røgtest med CLI → byg desktop → byg Android**.

## 0. Forudsætninger (Windows + RTX 3060)
- **Ollama** kørende med dine modeller:
  ```powershell
  ollama pull qwen2.5-coder:7b
  ollama pull nomic-embed-text
  ```
- **Go** (til backend) og **Python 3.10+** (til worker) på PATH.
- **JDK 17** (til desktop + Android Gradle).
- **Android Studio** (nemmest til Android) eller Android command-line tools.

## 1. Stå serveren op og røgtest med CLI (verificeret)
Dette virker allerede — brug det som referencekæde og til at bekræfte at din
Ollama svarer, før du kaster dig over klient-builds.

**Hurtig vej uden Go/Python-toolchain (fra 0.20.14):** releasen indeholder
færdigbyggede, CI-røgtestede Windows-exe'er — `modelrig-server-windows-x64.exe`
og `modelrig-worker-windows-x64.exe`. Læg server-exe'en som
`backend\modelrig-server.exe` og worker-exe'en i `worker\`-mappen (run-scriptet
finder selv `modelrig-worker*.exe` og foretrækker den over python). Så kan du
springe `go build` og `pip install` over og gå direkte til run-scriptet.
Helt uden repo kan de også køres standalone fra én mappe:
```powershell
$env:MODELRIG_HOST = "0.0.0.0"          # så telefonen kan nå den
Start-Process .\modelrig-worker-windows-x64.exe
.\modelrig-server-windows-x64.exe        # forgrund; Ctrl+C stopper
```

```powershell
# byg backend + installér worker-deps (én gang)
go build -C backend -trimpath -o modelrig-server.exe .\cmd\modelrig-server
pip install -r worker\requirements.txt

# kør begge (binder 0.0.0.0 så telefonen kan nå den)
powershell -ExecutionPolicy Bypass -File .\deploy\run-windows.ps1
```
I en anden terminal:
```powershell
# par en enhed
.\backend\modelrig-server.exe -pair          # udskriver en XXXX-XXXX kode
python tools\modelrig-cli.py --url http://localhost:8080 pair --code XXXX-XXXX

# den vigtigste test: round-trip mod din RIGTIGE Ollama
python tools\modelrig-cli.py doctor --deep
#   -> forventet: alle grønne, embed_dims + models udfyldt

python tools\modelrig-cli.py chat "skriv en linje om Nørrebro"     # streaming
python tools\modelrig-cli.py rag-ingest --source test "ModelRig binder 0.0.0.0 for LAN"
python tools\modelrig-cli.py rag-chat "hvad binder den for LAN?"   # streaming RAG-svar
```
Hvis `doctor --deep` er grøn, ved du at backend + worker + Ollama spiller sammen
på din maskine. **Nu er klient-builds den eneste ukendte.**

## 2. Byg desktop-klienten (verificeret — CI bygger Windows-jar ved desktop-ændringer og milepæle)
```powershell
cd desktop
gradle wrapper --gradle-version 8.9      # der er ingen wrapper-jar i repoet
.\gradlew run
```
Konfigurer i appen (eller via miljøvariabler før start):
`localUrl=http://localhost:8080`, `deviceToken=<token fra pairing>` (env
`MODELRIG_TOKEN`), evt. `OLLAMA_API_KEY` for cloud-fallback.

**Røgtest desktop:**
1. "Load models" fylder dropdown (rammer `/api/v1/models` via backend).
2. Send en besked → svaret **streamer** token-for-token ind i boblen.
3. Badge viser LOCAL. Stop Ollama, send igen med cloud-nøgle sat → falder til CLOUD.

## 3. Byg Android-klienten (uverificeret)
Nemmest i Android Studio (åbn `android/`-mappen, lad den sync'e, kør på
emulator/enhed). Eller CLI:
```powershell
cd android
.\gradlew assembleDebug
#   APK: android\app\build\outputs\apk\debug\app-debug.apk
```
**VIGTIGT for Android:** backend SKAL binde `0.0.0.0` (det gør `run-windows.ps1`),
og telefonen skal være på samme LAN. Brug maskinens LAN-IP (fx
`http://192.168.1.20:8080`) i pairing-skærmen — ikke `localhost`.

**⚠️ 0.16.0 — ENGANGS-AFINSTALLATION:** signaturen er skiftet til den faste
release-keystore. Afinstallér den gamle app én gang før du installerer 0.16.0
(cloud-nøgle + system-instruktioner skal indtastes igen). Alle fremtidige
versioner opdaterer oven på.

**Røgtest Android:**
1. Pair-skærm: indtast LAN-URL + XXXX-XXXX kode → token gemmes.
2. Chat-skærm: modeldropdown fyldes, besked → svaret streamer ind (spinner mens
   det genereres).
3. **Markdown**: bed om noget med kode (fx "skriv en Kotlin data class") → svaret
   skal vise **kodeblok med monospace + Kopiér-knap**, ikke rå ``` ```-tegn. Tjek
   at **fed**/*kursiv*, punktlister og overskrifter renderes.
4. Overflow-menu (⋮): "Ny samtale", "Samtaler" og "Indstillinger" virker.
5. **Persistens**: skriv en besked, luk appen helt (swipe væk), åbn igen →
   samtalen er der stadig. Tjek også Samtaler-listen (åbn/slet).
6. **Stop**: start et langt svar, tryk på stop-firkanten → streaming stopper
   straks og teksten får et "[afbrudt]"-mærke.
7. **RAG-tilstand** (0.17, kræver mindst én ingesteret kilde — se `rag-ingest`
   ovenfor eller CLI'en): tryk RAG-toggle i top-baren (kun synlig når Rig er
   aktiv) → skal hente kildeliste. Stil et spørgsmål om det ingesterede indhold
   → svaret skal vise **kilde-chips** over teksten (ikke bare rå tekst). Prøv
   "Alle kilder"-dropdown vs. et specifikt filter.
8. **Fejl-UX + retry** (0.18): sluk rig'en (stop backend/worker) midt i en
   samtale, send en besked → skal vise en **læselig dansk fejlbesked** (ikke en
   rå exception-streng) og en **"↻ Prøv igen"**-knap. Tænd rig'en igen, tryk
   "Prøv igen" → svaret kommer, ingen dobbelt bruger-boble.
9. **Presets** (0.19.8, genbygget 0.20.4 — bekræftet on-device): skriv en
   system-instruktion i Rig- eller Cloud-kortet → tryk "+ Gem som preset" →
   et **inline navnefelt folder ud** (ingen dialogboks) → skriv navn ("Gem"
   skifter grå→blå) → tryk → chip vises. Tryk chippen for at genanvende,
   "✕" for at slette.
10. **Model-administration** (0.20.0, kræver rig): ⋮-menu → "Modeller" →
    installerede modeller vises med størrelse, kørende med VRAM. Hent en
    lille model (fx `llama3.2:1b`) → **levende fremgang** (status + %).
    Slet den igen → bekræftelsesdialog → væk fra listen.
11. **RAG-ingest fra appen** (0.20.2): RAG-tilstand til → kilde-dropdown →
    "+ Tilføj dokument (txt/md)…" → Androids filvælger åbner → vælg en
    .txt/.md → status i topbaren ("Ingesteret: navn (N chunks)") → kilden
    dukker op i dropdownen. Menupunktet er deaktiveret ("Ingesterer…") mens
    en ingest kører (0.20.9).
12. **Samtale-oplevelse** (0.20.6): Samtaler-skærmen → skriv i søgefeltet →
    listen filtrerer live. "✎" på en samtale → omdøb inline → navnet holder.
    "Del" → Androids delings-ark åbner med en læselig markdown-udgave.
13. **Multi-rig-profiler** (0.20.8): forbundet til rig → "+ Gem denne rig"
    i Rig-kortet → navngiv (fx "Hjemme") → chip vises. Tryk chippen senere →
    forbinder øjeblikkeligt uden ny parring (gemmer URL + token, ikke
    engangskoden).

Bemærk om markdown: mens svaret streamer vises det som plain tekst; når det er
færdigt skifter det til renderet markdown. Det er med vilje (undgår jank og
halvåbne kodeblokke). Tabeller og dyb list-nesting understøttes ikke — se
`android/ui/Markdown.kt` hvis du vil skifte til fuld CommonMark.

**Cloud uden rig (0.12.0):** På setup-skærmen kan du vælge **Ollama Cloud** i
stedet for (eller udover) rig'en. Indtast din API-nøgle (fra
`ollama.com/settings/keys`) + et modelnavn (fx `gpt-oss:120b`), tryk "Gem & brug
cloud" → chat streamer direkte fra skyen, rig slukket. Er begge sat op, får du en
Rig/Cloud-toggle øverst. Tjek også at nøglen overlever app-genstart (den gemmes
Keystore-krypteret — det er den mindst-testede kode, så sig til hvis "Gem" fejler).

## 4. Mest sandsynlige fejl (og fix)
Ærligt: risiko #1 er **version-drift i Compose/Kotlin**. De pinnede versioner er
plausible, men ikke verificeret sammen.

| Symptom | Årsag | Fix |
|--------|-------|-----|
| Gradle: "Compose Compiler unsupported Kotlin version" | Compose-compiler-plugin matcher ikke Kotlin-versionen | Sæt begge til et kendt matchende par. Desktop pinner Kotlin `2.0.21` + compose-compiler-plugin `2.0.21`; bump samlet hvis nødvendigt. |
| Android: AGP/Gradle-inkompatibilitet | AGP `8.5.2` kræver nyere Gradle end wrapperen | Kør `gradlew wrapper --gradle-version 8.9` i `android/`; opdatér AGP hvis Studio foreslår det. |
| App når ikke serveren | Backend bundet til `127.0.0.1` | `MODELRIG_HOST=0.0.0.0` (eller Tailscale-IP), genstart. |
| Android: cleartext blokeret | HTTP over LAN | Manifest har allerede `usesCleartextTraffic=true`; ellers brug Tailscale + HTTPS. |
| Streaming "hakker" eller kommer i én klump | UI opdaterer ikke pr. delta | Deltas appended på composition-scopet; hvis du ser klumper, tjek at `chatStream`-callback'en kører (ikke den blokerende `chat`). |
| Desktop: `Dispatchers.Main` mangler | JVM-desktop uden coroutines-swing | Allerede undgået (bruger `scope.launch { }` på composition-scopet). Hvis du selv tilføjer kode, gør det samme. |

## 5. Hvad "1.0-klar" betyder
Server-siden er der (**108 assertions grønne** — smoke 11, v1 26, e2e 28,
worker_unit 15, worker_rag 28). Desktop-paritetsløftet fra V2 er siden
**leveret og løbende verificeret** (brand, dansk UI, system-prompts, markdown,
persistens, RAG, presets, model-administration, samtale-browser) — og CI
(`v0.19.5+`) bygger nu APK + OS-native desktop-jars automatisk på hvert
tag-push, så afsnit 2-3 ovenfor er valgfri lokale alternativer, ikke
nødvendige. **V1 hænger udelukkende på Android**: den fulde tjekliste (13
punkter — de 8 originale plus presets, model-administration, RAG-ingest,
samtale-oplevelse og multi-rig-profiler, se `STATUS.md` for den autoritative
liste) skal være kørt igennem og bekræftet grøn på rigtig hardware, før
`v1.0.0` tags. Præcis status pr. punkt vedligeholdes i `STATUS.md` —
denne fil er kun opskriften.

Når du har kørt igennem: sig hvad der fejlede (fejlbesked + hvilket trin), så
retter vi det målrettet. Bekræfter alle punkter, tagger vi `v1.0.0`.
