> ⚠️ **Aktuel autoritativ tilstand: `VERSION` (1.58.2), `ROADMAP.md`, `SECURITY.md`.**
> Denne fil er en historisk log — ældre datoer/versioner nedenfor er ikke nødvendigvis aktuelle.
> 13/7-2026: audit-P0/P1 lukket (1.58.1/1.58.2); VERSION-kilde + CI-gate indført; roadmap fornyet.

# ModelRig / Kaliv — komplet handoff til ny chat

**Dato:** 2026-07-12 (aften) · **Version:** v1.58.0 · **Repo:** `github.com/Ternedal/ModelRig` (**PUBLIC** — gratis CI)

Copy/paste dette som første besked i en ny chat. Dokumentet er selvbærende:
det dækker beslutninger, tilstand, arbejdsform, release-flow, toolchain,
arkitektur og lektier. Ved tvivl: dette dokument + `STATUS.md` linje 3 vinder
over hukommelse og antagelser.

---

## 0. AFGJORTE beslutninger — genåbn dem IKKE

Disse er truffet af Anders og står ved magt. En ny session skal IKKE flagge
dem, minde om dem eller starte en diskussion om dem.

1. **Tokens/PAT ligger i Notion — Anders VED det.** PAT'en (og øvrige tokens)
   er gemt i Notion og skal på et tidspunkt revokes/roteres. **Det er Anders'
   opgave, på Anders' tidspunkt.** Ingen påmindelser, ingen "akut punkt 1",
   ingen ny diskussion — dette afsnit ER kvitteringen for at det er kendt.
   Den eneste stående, operationelle regel: **masker altid tokens i output**
   (release-flowets `sed 's/[A-Za-z0-9_]\{20,\}/***/g'`-mønster) og brug
   origin-URL'ens indlejrede PAT som den er.
2. **Keystoren + passwords ligger i det offentlige repo** (`android/signing/`,
   committet v1.10.1 mens repoet var privat; repoet blev senere public).
   **Risiko ACCEPTERET af Anders 12/7.** Rationale: personligt projekt; der
   installeres udelukkende APK'er fra egne releases. Rotation ved en naturlig
   geninstallations-lejlighed (samtale-eksport findes nu, v1.56.0, så det
   koster ikke data). Fjern den IKKE — CI signerer hver `kaliv-latest.apk`
   med den. Stående regel: kun egne releases; rotér hvis reglen brydes.
3. **Navne:** kun BACKEND hedder ModelRig (server/worker/repo/API/exes).
   ALT brugervendt hedder **Kaliv**. `applicationId dk.ternedal.modelrig`
   er permanent og må ALDRIG ændres. ALVA_*-env-navnene er bevidst uændrede.
4. **qwen3:14b er primær rig-model** (bekræftet on-device 12/7: kender
   identitet + tools). Kendte model-svagheder (IKKE app-bugs): dropper
   bindestreger, hallucinerer dansk faktaviden, ignorerer emoji-forbud
   (→ deterministisk klient-strip). hermes3:8b er fallback.
5. **CI bygger KUN** Windows-jar + Android-APK + 2 Windows-exes (6 assets).
   Ingen Linux/macOS-desktop-builds — Anders kører Windows + Android.
6. **Notion-MCP må ALDRIG kaldes uopfordret.**

---

## 1. Hvad projektet er

Anders' personlige, selv-hostede AI-platform ("Local AI Control Surface"):
Ollama-modeller på egen Windows-rig (RTX 3060 12GB), nået fra **Kaliv**
(Android, Pixel 6a) og **Kaliv Desktop** (Windows, Compose JVM). Dansk voice
(ASR→LLM→TTS, streamet sætning-for-sætning), RAG-ingest (pdf/docx/pptx/html/
foto), bekræftelses-gatet tool-lag, og valgfri Ollama Cloud-hjerne. Telefonen
når riggen via Tailscale: `http://100.88.91.64:8080`.

Succes = pålidelig, testet on-device-oplevelse med rene CI-verificerede
releases. Kadence: MVP → V1 → V2; roadmap er lukket-endet ved V15.

---

## 2. Aktuel tilstand (v1.58.0)

**Hardware-bekræftet (pr. 12/7):** PDF/DOCX→RAG · dansk TTS+ASR (CUDA
large-v3) · voice ende-til-ende · **voice-via-cloud** (deepseek-671b korrekt,
efter keep_alive-fixet) · barge-in/tap-to-stop/RMS-meter · agent-laget (læs +
skriv bag bekræftelseskort, audit) · rig-model-skifter · emoji-strip + persona ·
voice-cloud-model-vælger + retur-til-rig · routing-stribe · desktop-rebrand
gennem v1.41→v1.47.

**Afventer Anders' test (kø, vigtigst først):**
1. **Streamende voice (v1.54–55)** — S1–S4 i `DEVICE_TEST.md`.
   **Forudsætning: genstart workeren først** (streaming er worker-side; gammel
   worker → 404 på stream-endpointet). Bufret endpoint urørt som fallback.
   Lyt efter: taler den før hele svaret er færdigt · RMS-meter opdaterer ·
   boblen fyldes sætning-for-sætning · barge-in midt i stream · gaps/overlap.
2. **Desktop v1.58 mod mockup'en** — hold jar'en op mod
   `assets/design/kaliv-ui-guide/Kaliv_UI_Target_Mockup.png` (dark+light).
3. **Eksport/import af samtaler (v1.56)** — eksportér, importér samme fil,
   bekræft dublet-skip.
4. **Foto→RAG** — kræver `KALIV_VISION_MODEL` (fx `llama3.2-vision:11b`) på
   workeren; uden = ærlig 501. VRAM-kabale forventet (model-swap-latens).
5. **Eval-harness:** `python -m app.eval_models hermes3:8b qwen3:14b` — tal
   på tool-disciplin/dansk/latens. 6. **migrate_data** dry-run → `--apply`.

**Tests (grønne):** worker **298** (unit 52 · tools 124 · backup 17 · RAG 48 ·
paths 12 · migrate 7 · eval 18 · vision 12 · voice-stream 8) + Go
(config, httpapi). Alle kørt i CI på hver release.

---

## 3. Arbejdsform med Anders

- **Svar på dansk.** Koncist, ærligt, direkte. Ingen falsk sikkerhed.
- **Skeln verificeret / kvalificeret antagelse / gæt.** Sig hvad der ikke er
  testet. Standard-forbehold på UI: "verificeret ved build, ikke med øjne".
- **"kør" / "kør videre"** = fuld autonom eksekvering uden check-ins, med
  fuld commit-autoritet. **"test jeg"** = Anders tester på hardware.
- **Anders kører FLERE parallelle Claude-sessioner.** Derfor: `git pull
  --rebase` før alt arbejde, tjek version-sites for kollisioner, og forvent
  at en anden session kan have tilføjet det samme (skete med
  voiceCloudModel — dup fjernet, UI wired ovenpå).
- **Ærlig modstand er ønsket.** Sig fra når noget ikke kan bygges meningsfuldt
  uden Anders' test eller beslutning — det har flere gange været det rigtige.
- **MVP → V1 → V2.** Byg smalt, bevis, udvid. **DKK** ved priser;
  København/Nørrebro som kontekst.
- Ret aldrig noget "efter øjemål" når der findes en autoritativ kilde
  (design-tokens, fejltekster, docs) — og læs fejlteksten FØR du fikser.

---

## 4. Release-flow (bevist, følges præcist)

1. **Bump alle FIRE version-sites i lockstep:** `worker/app/main.py`
   (VERSION) · `backend/internal/config/config.go` (const Version) ·
   `android/app/build.gradle.kts` (versionName + versionCode, monotont —
   næste er **132**) · `desktop/composeApp/build.gradle.kts` (packageVersion).
2. Byg/verificér (APK og/eller jar) → kør tests → opdatér `STATUS.md`
   linje 3 (indeks [2] via python splitlines).
3. `git add -A && git -c commit.gpgsign=false commit -q -F /tmp/m.txt`
   → `git fetch -q origin main && git rebase -q origin/main && git push
   origin main:main` (masker tokens i output med sed-mønstret fra §0.1).
   NB: `git pull --rebase` brokker sig ("Please commit or stash") når træet
   er beskidt — harmløst; commit+push går igennem.
4. POST release via GitHub API (token trækkes af origin-URL'en;
   `make_latest:"true"`) → `sleep ~290` → verificér **CI grøn + 6 assets**:
   `kaliv-latest.apk`, `modelrig-vX.Y.Z.apk`, `Kaliv-windows-x64-X.Y.Z.jar`,
   zip, 2 Windows-exes.
5. **Docs-only-ændringer = commit uden tag/bump.**

---

## 5. Sandbox-toolchain (verificér selv i ny session)

```
Repo-klon    /home/claude/repo   (PAT indlejret i origin-URL — masker i output)
Android SDK  /home/claude/android-sdk
             export ANDROID_HOME=/home/claude/android-sdk ANDROID_SDK_ROOT=$ANDROID_HOME
             aapt2 findes via: find /home/claude/android-sdk -name aapt2
Gradle       wrapper i repoet (android/gradlew, desktop/gradlew) — brug --offline
Go 1.23      /usr/local/go/bin — SKAL sources: export PATH=$PATH:/usr/local/go/bin
JDK 21       forudinstalleret
mermaid-cli  /home/claude/.npm-global/bin/mmdc — kræver -p cfg med {"args":["--no-sandbox"]}
```
Desktop er JVM-only Compose: tasken hedder `:composeApp:compileKotlin`
(IKKE compileKotlinJvm). Android release-build: `:app:assembleRelease`.
Stierne kan ændre sig mellem sandbox-generationer — verificér med `ls`/`which`.

---

## 6. Sådan starter Anders riggen

**Nem vej:** `scripts\start-kaliv.bat` — starter Ollama + worker + server
korrekt (inkl. `MODELRIG_HOST=0.0.0.0`) og kører `/health/full`. Se
`scripts/START_HERE.md` for manuel vej og fejlsøgning. Telefonen parres mod
Tailscale-IP'en (`http://100.88.91.64:8080`), ikke LAN.

---

## 7. Arkitektur (kort)

```
Kaliv (Android/Desktop) → Go :8080 (pairing/tokens/reverse-proxy, flusher
streams) → Worker :8099 (RAG · voice · tools · eval) → Ollama :11434 (lokal)
                                        └→ Ollama Cloud (valgfrit LLM-trin)
```
- **Voice:** ASR/TTS altid lokalt; LLM-trin kan gå til cloud med EGEN model
  (`voiceCloudModel`, fallback til `cloudModel`). Bufret:
  `/voice/converse/upload`. **Streamet: `/voice/converse/stream`** (NDJSON:
  transcript → chunk pr. sætning m. base64-lyd → done). **`keep_alive`
  sendes ALDRIG til cloud** (lokal-VRAM-direktiv; hang requests — v1.50.0).
- **Tools:** registry i kode, bekræftelses-gate i WORKEREN (klient kan ikke
  omgå), append-only audit. `KALIV_TOOLS_ENABLED=1` for at tænde.
- **RAG:** pdf/docx/pptx/html + foto (`/rag/ingest/image`, 501 uden
  `KALIV_VISION_MODEL`). Embeddings altid lokale (nomic-embed-text).
- **Design:** `assets/design/kaliv-ui-guide/` er autoritativ
  (kaliv-ui-tokens.json v1.0). Ændr tokens, ikke øjemål. Desktop følger den
  fra v1.58.0; **Android kører ældre bronze (#8B6B3D) — alignment er en
  ÅBEN Anders-beslutning.** Fonte (Inter/EB Garamond) mangler som filer.
- Fuld env-liste og endpoints: `README.md` + `TROUBLESHOOTING.md`.

---

## 8. Hårdt tillærte lektier (gentag ikke disse fejl)

1. **On-device-test er den eneste sandhed.** Næsten hver v1.34.x+-bug var
   "koden korrekt, tests grønne, brudt på rigtig hardware".
2. **At kompilere er ikke at shippe** — og **at editere træet er ikke at
   shippe.** CI-jobbet verificerer at assets faktisk ligger på releasen.
3. **Verificér HVER patch-erstatning individuelt.** v1.57's composer-patch
   matchede aldrig (søge-anker med `\uXXXX`-escapes mod en fil med rigtige
   tegn) og scriptet printede succes ubetinget → release-noten overpåstod.
   Nu: assert pr. erstatning + grep-verifikation bagefter. Match mod filens
   FAKTISKE indhold, ikke mod hvad du tror du skrev.
4. **Den korteste timeout i kæden vinder.** Voice: Android/Go/worker skal
   alle være lange (5min/10min/600s); almindelig chat bevidst 120s.
5. **Blokerende arbejde i `async def` fryser hele workeren.** Alt tungt i
   `to_thread` — men BEHOLD serialiseringen med en lås (delte modelobjekter).
6. **Windows-lektierne:** env-reads kræver `TrimSpace` (cmd's `set X=val &&`
   fanger trailing spaces — mutations-testet); datafiler ankres til exe-dir
   (Go) / `%LOCALAPPDATA%\Kaliv` (Python); PyAV blokeres af Application
   Control (→ soundfile); CUDA-DLL'er kræver BÅDE `add_dll_directory` OG
   PATH; multi-line python-one-liners virker ikke i cmd; parenteser +
   nested quotes → goto-labels og genererede `.cmd` i `%TEMP%`.
7. **Læs fejlteksten FØR du fikser** — svaret har stået der ordret, to gange.
8. **Et status-endpoint må ikke lave arbejde.**
9. **En ny gren i et `when` arver ingenting.** List hvad de andre grene gør,
   og begrund pr. ting hvorfor din ikke behøver den (kostede historik, RAG,
   billede, persistens ad tre omgange).
10. **Prompt alene tøjler ikke en lille models vaner** (emojis, persona) —
    deterministisk efterbehandling gør (klient-strip på færdige + indlæste).
11. **"Slet det aktive X" skal nulstille den aktive peger FØR næste
    skrivning** (FK-crash på begge platforme, v1.46.0).
12. **Compose:** `SnapshotStateList` er tråd-sikker at mutere fra IO-tråde;
    sæt indeks-variabler synkront i callback-rækkefølgen (replyIdx-racet);
    `painterResource` tegner kun animerede WebP'ers første frame (→ native
    Canvas-animation); `remember` genlæses når skærmen disposes via
    `when(screen)` — naviger tilbage skal sætte den state den forventer.
13. **Send aldrig lokale Ollama-parametre til cloud-upstreams** (keep_alive).
14. **Fire versionskonstanter i lockstep** — CI-smoke fejler releasen ved
    mismatch. **"✓ forbundet" skal pinge**, ikke bare betyde "parring gemt".

---

## 9. Åbne byggekandidater (når Anders siger til)

- **V6 input-halvdel:** streaming-ASR mens man taler (output-halvdelen ✅
  v1.54–55) · wake word "Hey Kaliv" (beslutning: altid-lyttende mik).
- **Design-rester:** footer-strip ("Sikker forbindelse" · "Kaliv kan tage
  fejl") · hover-actions pr. besked (kopiér m.m.) · rigtige fonte når Anders
  leverer .ttf · a11y-punkterne fra checklisten · Android-palet-alignment
  (**Anders-beslutning**).
- **Tools i voice-flowet** (V5-hale): Kaliv siger højt hvad den vil gøre og
  venter på "ja". · **Auto-rute til cloud når Tools er på** (design i
  CLOUD_TOOLS.md §B, kørbar fra v1.50.0+).
- Større spor (V9 hjemmet, V10 vision-udvidelse, V11 agent v2, V12 dansk
  model, V13 API, V14 føderation, V15 modenhed): se `ROADMAP.md` §14–20.

---

## 10. Dok-kort

`STATUS.md` linje 3 = altid-aktuel one-liner (resten: release-historik) ·
`ROADMAP.md` = retning, lukket-endet ved V15 · `DEVICE_TEST.md` = test-
runbooks (S1–S4 streaming) · `TROUBLESHOOTING.md` = symptom→fix fra faktiske
fejl · `MODELS.md` = modelvalg + voice-modeller · `CLOUD_TOOLS.md` =
cloud-agent-status · `DRIFT.md` = Tailscale/backup/geninstallation ·
`scripts/START_HERE.md` = opstart · `assets/design/kaliv-ui-guide/` =
design-autoritet · Historiske (bannered): TESTGUIDE, PLAN_v1.13.0,
ALVA_VOICE_ROADMAP_DELTA, CLIENT_BUILD_AND_TEST, KRAVSPEC_V5 (leveret).
