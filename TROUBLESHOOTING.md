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
