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

To datakilder at have styr på:

| Fil | Indhold | Sti (default) |
|---|---|---|
| `modelrig-data.json` | Parrede enheder, hashede tokens | `./modelrig-data.json` (backend working dir) |
| `modelrig-rag.db` | RAG-index (ingesterede dokumenter, embeddings) | `./modelrig-rag.db` (worker working dir), override via `MODELRIG_DB` |

**Backup (kør med rig'en stoppet, eller accepter en lille race hvis den kører):**
```bash
# Windows (PowerShell)
Copy-Item modelrig-data.json  "$env:USERPROFILE\ModelRigBackup\modelrig-data.json"
Copy-Item modelrig-rag.db     "$env:USERPROFILE\ModelRigBackup\modelrig-rag.db"

# Linux
cp modelrig-data.json /opt/modelrig/backup/modelrig-data.json
cp modelrig-rag.db    /opt/modelrig/backup/modelrig-rag.db
```
Begge er almindelige filer (JSON / SQLite) — ingen særlig eksport nødvendig.
Anbefaling: en simpel dagligt kørende scheduled task/cron der kopierer begge til
en anden disk eller cloud-mappe (OneDrive/Nextcloud-synkroniseret mappe er fint,
så længe filen ikke redigeres af to processer samtidig).

**Restore:**
1. Stop backend + worker.
2. Læg de to filer tilbage på deres pladser (`modelrig-data.json` i backend's
   working dir, `modelrig-rag.db` i worker's working dir).
3. Start op igen. Ingen migrering nødvendig — de læses direkte ved opstart.

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
Se `CLIENT_BUILD_AND_TEST.md` for fuld røgtest af både server og Android-app efter
en opgradering.

## 5. API-oversigt (alle bag bearer-token, medmindre andet nævnt)

Tilføjet 0.20.12 — der fandtes ingen samlet oversigt før; endpoints var kun
dokumenteret spredt i `STATUS.md`-changelogs. Autoritativ kilde er stadig
koden (`backend/internal/httpapi/server.go`); dette er et driftsopslag.

```
GET    /healthz                      # ingen auth: oppe + version
POST   /api/v1/pair/start            # ingen auth: start parring (udsteder kode)
POST   /api/v1/pair/claim            # ingen auth: byt parringskode til token
GET    /api/v1/status                # backend-status
GET    /api/v1/health/deep           # rundtur backend -> Ollama + worker
GET    /api/v1/devices               # parrede enheder
DELETE /api/v1/devices/{id}          # revokér en enheds token
POST   /api/v1/token/rotate          # rotér eget token (gammelt invalideres)
POST   /api/v1/chat                  # streaming chat-proxy (Ollama /api/chat)
GET    /api/v1/models                # installerede modeller (Ollama /api/tags)
GET    /api/v1/models/running        # kørende modeller + VRAM (Ollama /api/ps)      [0.20.0]
POST   /api/v1/models/pull           # hent model, streamer NDJSON-fremgang          [0.20.0]
DELETE /api/v1/models/delete         # slet model (irreversibelt på rig'en)          [0.20.0]
POST   /api/v1/rag/ingest            # ingestér tekst-dokumenter i RAG-indekset
POST   /api/v1/rag/query             # hent matches (+ evt. syntetiseret svar)
POST   /api/v1/rag/chat              # RAG-chat, streamer NDJSON (1. linje = kilder)
GET    /api/v1/rag/sources           # kildeliste med chunk-antal
DELETE /api/v1/rag/source?source=X   # fjern én kildes chunks
GET    /api/v1/rag/stats             # kilder/chunks-totaler
```

**RAG-relevans-tærskel (0.20.11):** `POST /api/v1/rag/query` og `/rag/chat`
tager et valgfrit `min_score`-felt (0.0–1.0, default **0.3**). Matches under
tærsklen filtreres FØR `top_k`-afskæringen — så et spørgsmål uden reelt
relevant indhold giver færre/nul kilder i stedet for at tvinge støj ind som
kontekst. 0.3 er et fornuftigt udgangspunkt for `nomic-embed-text`, ikke
empirisk tunet mod dine dokumenter — justér via feltet (ingen kodeændring)
hvis daglig brug viser for mange/for få kilder.

