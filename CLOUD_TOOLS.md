# Cloud-assisteret agent-flow

Status og plan for at bruge en cloud-model til pålidelige tool-kald + dansk, når
de lokale modeller på 3060'eren ikke rækker.

## A. Hvad er verificeret (kode-niveau)

Cloud-tools-flowet er **allerede bygget og korrekt trådet igennem**:

- Appen sender i cloud-mode `cloudBaseUrl="https://ollama.com"` + `cloudKey` +
  cloud-modellen ind i `toolsChat` (AppUi.kt ~994). Ikke kun almindelig chat —
  også tools-stien. (Verificeret: intet tavst hul hvor cloud-mode kalder riggen.)
- Worker'en router til cloud når `cloud_key` er sat (`origin = "cloud"`), samme
  `/api/chat`-format, så **ingen ny integration** for Ollama Cloud.
- **Sikkerhedsmodellen er intakt og bevidst:** bekræftelses-gaten kører lokalt i
  worker'en uanset origin. En cloud-model må *foreslå* et værktøj, men enhver
  WRITE går gennem dit bekræftelseskort (`origin=cloud` i kortet og i audit-
  loggen). En READ kører frit — men dens resultat sendes til cloud-modellen for
  at blive formuleret, dvs. tool-output forlader huset (bevidst valg, dok. i
  koden).

Automatiseret dækning: T16 (gate-niveau) + **T30 (ny, hele stien)** beviser at et
cloud-foreslået write parkerer bag kortet gennem `tools_chat`, og at intet skrives
før godkendelse. Mutationstjekket: gør writes auto-eksekverende → testene bliver
røde.

**Det eneste uverificerede er en rigtig Ollama Cloud-kørsel med tools** — det
kræver din nøgle. Kør protokollen herunder.

## A. On-device test-protokol (cloud-tools)

Forudsætning: cloud-nøgle sat i appen (⋮ → Ollama Cloud), en cloud-model valgt
(fx `gpt-oss:120b` eller `kimi-k2`), worker startet med `KALIV_TOOLS_ENABLED=1`.

1. **Skift til cloud** ("Skift"-knappen → cloud-mode), slå **Tools til**.
2. Skriv: **lav en note om at cloud-agenten virker**.
3. Forventet: **bekræftelseskort** hvor der står at *cloud-modellen* foreslår
   note_append. Tryk **Godkend**.
4. Tjek på riggen: `notes.md` fik linjen, og ⋮ → Handlingslog viser rækken med
   **origin=cloud**.
5. Prøv en READ: **hvad er status på riggen?** → skal køre uden kort (rig_status
   er en read), svaret formuleret af cloud-modellen på dansk.

Hvis kortet siger "cloud-modellen foreslår", noten skrives efter godkendelse, og
audit-loggen viser origin=cloud → hele cloud-agent-kæden virker ende-til-ende.

Fejler det: send worker-loggen. `tools_chat=calling_ollama url=https://ollama.com`
bekræfter at cloud-upstreamet bruges; en 401 dér = forkert/manglende cloud-nøgle.

## B. Design: auto-rute til cloud når Tools er på

**Problem:** i dag skal du manuelt trykke "Skift" til cloud hver gang du vil have
pålidelige tool-kald. Ønsket: når Tools er på, brug cloud automatisk (fordi cloud
er markant bedre til tool-kald end en lokal 8B/14B).

**Anbefalet design (opt-in, ingen overraskelser):**

En ny indstilling: **"Brug cloud automatisk når Tools er slået til"** (bool,
default **fra**). Logikken, ét sted i send-stien:

```
effectiveCloud = (mode == "cloud")                        // manuel toggle vinder altid
    || (autoCloudForTools && toolsEnabled && cloudKey != null)  // auto, kun hvis muligt
```

Regler der gør det sikkert og forudsigeligt:
- **Kun hvis en cloud-nøgle findes.** Ingen nøgle → forbliv lokal, ingen fejl.
- **Manuel "Skift" vinder altid.** Slår du eksplicit cloud fra, respekteres det.
- **Synligt.** Svar-chippen viser allerede "via cloud". Når auto-ruten er aktiv,
  skal chippen sige *hvorfor* (fx "via cloud (tools)"), så du aldrig er i tvivl
  om hvor dine data gik hen — vigtigt givet privacy.
- **Gaten er uændret.** Auto-rute ændrer kun *hvilken model der foreslår*; kortet
  og den lokale eksekvering er præcis som før. Ingen sikkerhedsændring.

**Hvad det kræver at bygge (lille):**
1. `store.autoCloudForTools: Boolean` (default false) + en switch i Indstillinger.
2. Beregn `effectiveCloud` som ovenfor der hvor `viaCloud`/`useCloud` sættes
   (AppUi.kt ~919, ~984). Erstat `mode == "cloud"` med `effectiveCloud`.
3. Chip-tekst: skeln "via cloud" (manuel) fra "via cloud (tools)" (auto).
4. Ingen worker-ændring — den ser bare cloud-config som nu.

**Privacy-konsekvens der skal med i beslutningen:** auto-rute betyder at *alle
tool-samtaler* (inkl. RAG-kontekst fra dine dokumenter, hvis RAG er på samtidig)
sendes til cloud. Det er hele pointen med at slå det til — men det bør være et
bevidst valg, derfor default-fra og tydelig chip. Overvej en variant: auto-cloud
kun når Tools er på **og RAG er fra**, så personlige dokumenter aldrig auto-sendes.

**MVP → V1:**
- MVP: switchen + `effectiveCloud`. Manuel kontrol bevaret, cloud kun når muligt.
- V1: chip-differentiering + evt. "auto kun uden RAG"-varianten.
- V2 (hvis nogensinde): pr.-samtale-hukommelse af valget, eller auto-eskalering
  kun når den lokale model *fejler* et tool-kald (mere logik, mere fejl-flade —
  ikke nødvendigt nu).

## Åbne spørgsmål (dine at afgøre)
- Cloud-provider: Ollama Cloud (nul ny kode) vs. en rigtig Claude/OpenAI-adapter
  (reelt arbejde: andet request/tool-schema-format). Test Ollama Cloud først.
- Skal auto-cloud undgå at sende RAG-kontekst? (privacy vs. kvalitet)
- Omkostningsloft: cloud koster pr. token; en chatty stemme-assistent kan løbe op.
