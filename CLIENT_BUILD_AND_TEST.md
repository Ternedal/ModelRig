# ModelRig — klient-build og røgtest (handoff)

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

```powershell
# byg backend + installér worker-deps (én gang)
go build -o backend\modelrig-server.exe .\backend\cmd\modelrig-server
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

## 2. Byg desktop-klienten (uverificeret — forvent småjusteringer)
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

**Røgtest Android:**
1. Pair-skærm: indtast LAN-URL + XXXX-XXXX kode → token gemmes.
2. Chat-skærm: modeldropdown fyldes, besked → svaret streamer ind (spinner mens
   det genereres).
3. **Markdown**: bed om noget med kode (fx "skriv en Kotlin data class") → svaret
   skal vise **kodeblok med monospace + Kopiér-knap**, ikke rå ``` ```-tegn. Tjek
   at **fed**/*kursiv*, punktlister og overskrifter renderes.
4. Overflow-menu (⋮): "Ryd samtale" og "Afbryd forbindelse" virker.

Bemærk om markdown: mens svaret streamer vises det som plain tekst; når det er
færdigt skifter det til renderet markdown. Det er med vilje (undgår jank og
halvåbne kodeblokke). Tabeller og dyb list-nesting understøttes ikke — se
`android/ui/Markdown.kt` hvis du vil skifte til fuld CommonMark.

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
Server-siden er der. **1.0-taggen sætter vi først når begge klienter er bygget og
røgtestet på rigtig hardware** (punkt 2 + 3 grønne). Indtil da er klienterne
kildekode, ikke en verificeret artefakt — det er den ærlige status.

Når du har kørt igennem: sig hvad der fejlede (fejlbesked + hvilket trin), så
retter vi det målrettet. Hvis alt spiller, tagger vi 1.0.
