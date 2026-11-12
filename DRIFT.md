# ModelRig — Drift (backup, Tailscale, geninstallation)

Praktisk driftsdokumentation til daglig brug. Se `deploy/README.md` for selve
opstart af backend/worker; dette dokument dækker det der sker *efter* det kører.

---

## 1. Tailscale — brug rig'en uden for hjemmenetværket

Formålet: telefonen skal kunne nå rig'en, uanset om du er hjemme på Nørrebro
eller ude. Tailscale giver en privat, fast IP der virker begge steder — uden at
åbne noget mod det åbne internet.

**På rig-maskinen (Windows/Linux):**
1. Installér Tailscale: `https://tailscale.com/download`
2. Log ind (samme konto du bruger på telefonen).
3. Find rig'ens Tailscale-IP: `tailscale ip -4` (typisk `100.x.y.z`).
4. Sæt `MODELRIG_HOST=0.0.0.0` i `modelrig.env` (binder på alle interfaces,
   inkl. Tailscale) og genstart backend.

**På telefonen:**
1. Installér Tailscale-appen, log ind på samme konto.
2. Tænd Tailscale (VPN-toggle).
3. I ModelRig, brug rig'ens Tailscale-IP som Server-URL, fx `http://100.x.y.z:8080`
   — samme felt som ved lokal parring, bare med Tailscale-IP i stedet for LAN-IP.

**Vigtigt:** parringstokenet er knyttet til enheden, ikke til netværket — du skal
**ikke** parre igen når du skifter mellem hjemme-LAN og Tailscale, *medmindre* du
har brugt forskellige Server-URL'er (parring er pr. `baseUrl` i appen). Skal du
bruge begge, er den enkleste løsning at bruge Tailscale-IP'en konsekvent — den
virker også når du er hjemme.

**Sikkerhed:** eksponér aldrig rig'en direkte mod det åbne internet (kun LAN eller
Tailscale). Backend'en snakker almindelig HTTP — det er fint på Tailscale (som er
krypteret i sig selv), men ikke på åbent internet.

---

## 2. Backup og restore

**Brug [`scripts/BACKUP.md`](scripts/BACKUP.md).** Den beskriver den rigtige vej
(`scripts\kaliv-backup.bat`, som kalder `python -m worker.app.backup
create|verify|restore`; daglig task via `scripts\kaliv-backup-scheduled.ps1`;
maskinflytning via `scripts\migrate-new-rig-state.ps1`) og dækker alle stores —
RAG-index, backend-parring, tool-audit, jobs/scheduler, Agent 3-databaser,
home-rig-stores og notes — på deres faktiske stier. Workerens relative stier
ankres under `KALIV_DATA_DIR` (default `%LOCALAPPDATA%\Kaliv`), og backend-storen
`modelrig-data.json` ligger ved siden af server-exe'en. Kopiér ikke enkeltfiler
fra working dir: det rammer forkerte eller tomme filer.

**Konsekvens hvis `modelrig-data.json` mistes** (ikke gendannet): alle parrede
enheder mister deres token og skal parres igen (ny XXXX-XXXX-kode, `-pair` på
serveren). RAG-indekset (`modelrig-rag.db`) er upåvirket — det er en separat fil.

**Konsekvens hvis `modelrig-rag.db` mistes**: RAG-tilstanden i appen virker stadig
teknisk, men returnerer ingen kilder — dokumenterne skal geningesteres.

**Android-siden** (samtaler, cloud-nøgle, system-prompts) ligger **kun på
telefonen** (SQLite + Keystore-krypteret SharedPreferences) — der er **ingen
server-side backup af dette**. Mistes telefonen, mistes samtalehistorikken og
cloud-nøglen (men ikke rig-parringen, som kan genoprettes med en ny kode).

---

## 3. Geninstallation af Android-appen

**Almindelig opdatering** (samme signeringsnøgle, som er standard fra v0.16.0 og
frem): installér den nye APK oven på den gamle — ingen data går tabt, ingen
afinstallation nødvendig.

**Fuld geninstallation** (ny telefon, eller du har afinstalleret appen):
1. Installér APK'en.
2. Åbn appen → Indstillinger.
3. **Rig**: indtast rig'ens URL (LAN-IP eller Tailscale-IP) + en ny
   parringskode (kør `-pair` på serveren for at generere en) + evt.
   system-instruktion igen.
4. **Cloud**: indtast API-nøglen igen (fra `ollama.com/settings/keys`) + model +
   system-instruktion igen.
5. Samtalehistorik er væk (den lå kun på den gamle telefon/installation) —
   forventet, ikke en fejl.

**Éngangs-signaturskifte (historisk, allerede overstået):** før v0.16.0 blev
appen signeret med en midlertidig debug-nøgle der ikke var stabil på tværs af
byggesessioner. v0.16.0 indførte en fast release-keystore
(`android/signing/modelrig.keystore`, password i repo + Notion Secrets-backup).
Alt fra v0.16.0 og frem opdaterer problemfrit oven på hinanden. Relevant kun hvis
du en dag rebuilder fra en meget gammel zip.

---

## 4. Hurtig sundhedstjek

```bash
curl http://<rig-ip>:8080/healthz          # backend oppe + version
curl http://<rig-ip>:8080/api/v1/health/deep  # rundtur til Ollama + worker (kræver token)
```
Fuld røgtest efter en opgradering: `python tools/modelrig-cli.py doctor --deep` og
[`DEVICE_TEST.md`](DEVICE_TEST.md).

## 5. API-oversigt

> **[27/7-2026] Listen herunder er ikke længere komplet og er derfor fjernet.**
>
> Den blev skrevet ved 0.20.12 og har ikke fulgt med. Målt 27/7: den listede
> **19 af backendens 60 ruter**. Intet i den var forkert — men hele
> scheduler-, tools- og voice-fladen manglede, og al Agent 3. En oversigt der
> er en tredjedel komplet er værre end ingen: man slår `/api/v1/schedules` op,
> finder den ikke, og konkluderer at den ikke findes.
>
> En håndskrevet kopi af noget koden ejer rådner altid. Derfor en pegepind i
> stedet, som ikke kan blive forældet:
>
> **Backendens ruter (`:8080`, `/api/v1/*`)** — autoritativ kilde er
> `backend/internal/httpapi/`:
>
> ```powershell
> Get-ChildItem backend\internal\httpapi\*.go -Exclude *_test.go |
>   Select-String `
>   -Pattern '"(GET|POST|PUT|DELETE|PATCH) (/[^"]*)"' |
>   ForEach-Object { $_.Matches.Value } | Sort-Object -Unique
> ```
>
> ```bash
> grep -rhoE '"(GET|POST|PUT|DELETE|PATCH) /[^"]*"' \
>   --include='*.go' --exclude='*_test.go' backend/internal/httpapi/ | sort -u
> ```
>
> **Workerens ruter (`:8099`)** står i
> [`ROUTE_INVENTORY.md`](ROUTE_INVENTORY.md), som **genereres** af
> `scripts/route_inventory.py` og er CI-gated mod drift. Bemærk at det er en
> anden service end backenden — de to overflader er ikke den samme.

**RAG-relevans-tærskel (0.20.11):** `POST /api/v1/rag/query` og `/rag/chat`
tager et valgfrit `min_score`-felt (0.0–1.0, default **0.3**). Matches under
tærsklen filtreres FØR `top_k`-afskæringen — så et spørgsmål uden reelt
relevant indhold giver færre/nul kilder i stedet for at tvinge støj ind som
kontekst. 0.3 er et fornuftigt udgangspunkt for `nomic-embed-text`, ikke
empirisk tunet mod dine dokumenter — justér via feltet (ingen kodeændring)
hvis daglig brug viser for mange/for få kilder.

