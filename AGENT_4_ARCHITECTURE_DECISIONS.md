# Agent 4 — arkitekturbeslutninger (ADR)

**Truffet af Anders 30/07-2026** efter en målt gennemgang af de 14 åbne
Agent 4-PR'er og en sammenligning af de to konkurrerende timeline-modeller.

Disse beslutninger er den fælles sandhed, både mennesker og AI-sessioner
arbejder ud fra. **Genåbn dem ikke uden en ny, eksplicit beslutning.**

Rækkefølgen var bevidst: *først måle, så vælge retning, og først derefter
merge eller omskrive PR'er.* Det er derfor beslutningerne står her, før noget
Agent 4-arbejde er landet — ikke bagefter.

---

## ADR-A4-001 — Timeline-arkitektur

**Beslutning.** Gren **`#258` (B)** er den valgte referencearkitektur for
Agent 4's timeline. Gren A (`#254`) anvendes **ikke** som fundament.

**Kontekst.** A4-06 til A4-09 blev implementeret to gange, i to gensidigt
udelukkende grene fra samme base (`#253`). Begge oprettede
`worker/app/agent4/timeline.py` — med hver sin API, hver sin lagringsmodel og
hver sin stak ovenpå. De kunne ikke begge lande.

**Målingsgrundlag** (30/07-2026, mod repoet):

| | `#254` (A) | `#258` (B) |
|---|---|---|
| Lagring | én JSONL-fil pr. kampagne | én JSON-fil pr. post |
| Skrivning | `os.open(O_APPEND)` + `fsync` | `tempfile` + `fsync` + `os.link` |
| Append-only håndhæves af | disciplin | filsystemet |
| Fejl midt i skrivning | delvis linje → **hele** timelinen afvises | forældreløs `.tmp`, timelinen uberørt |
| Paging | kræver linjescanning eller separat indeks | sekvensnr. nulpolstret i filnavnet |
| Storage/read-model | `DurableCampaignEventBus` **inde i** `timeline.py` | store kan `append`/`list`/`verify`/`replay`, intet andet |
| Evidens | førsteklasses, adresserbar post i strømmen | reference hængt på en hændelse |

**Begrundelse.** Valget er truffet på arkitektonisk retning, ikke på
implementeringsstørrelse. Det afgørende er, at B holder lagringslaget smalt
med ét ansvar, at append-only håndhæves af lagringsmekanismen frem for af
disciplin, og at paging kan bygges uden et separat indeks ved siden af en
append-only-fil.

**Konsekvens.** A's evidensmodel er en reel styrke, som ikke skal gå tabt —
se ADR-A4-001a. A's event bus flyttes **ikke** med; se ADR-A4-002. Resten af
A4-stakken vurderes mod B som referencearkitektur.

### ADR-A4-001a — Evidens som first-class record (udskudt, ikke forkastet)

A behandler evidens som en selvstændig, adresserbar post i den ordnede strøm.
B behandler evidens som en reference hængt på en hændelse. A's model er
rigere for et kommende operator-/API-lag, hvor ét evidensstykke skal kunne
adresseres direkte.

**Beslutning:** funktionen løftes til et roadmap-punkt oven på B's
lagringsmodel — *"indfør evidens som first-class timeline record"* — frem for
at være grunden til at vælge A. Retningen er valgt, fordi den omvendte
rækkefølge er dyrere: at trække en event bus ud af A's lagringsmodul rører
kode, der allerede har flere PR'er stablet ovenpå.

---

## ADR-A4-002 — Storage Boundary

**Beslutning.** Storage-laget må ikke kende subscribers, `publish`, `notify`
eller projektioner. Afhængighedsretningen er **envejs**:

- `event_bus` **må** importere storage.
- Storage må **ikke** importere `event_bus`.
- Ingen storage-moduler må definere `subscribe`, `publish` eller `_notify`.

**Kontekst.** Målingen viste, at forskellen mellem de to grene ikke først og
fremmest var *hvordan* storage var implementeret, men **afhængighedsretningen**.
Reglen holdt allerede i `#253`'s base og i hele gren B: `event_bus.py` er et
sidestillet modul, som kun `__init__.py` re-eksporterer, og intet
lagringsmodul importerer det. Gren A brød den: `DurableCampaignEventBus` var
defineret inde i `timeline.py` og blev wiret af `composition.py` som
kampagnens event-vej.

**Hvorfor en gate og ikke en regel.** En arkitekturregel i prosa ville have
tilladt A at lande. Grænsen er derfor gjort mekanisk målbar i
**`tests/workflow_agent4_storage_boundary.py`**.

Et lagringsmodul udpeges dér på **adfærd, ikke på navn** — et modul, der
skriver til disk, *er* storage, uanset hvad filen hedder. Ellers kunne reglen
omgås ved en omdøbning, og navngivning er netop et åbent punkt (ADR-A4-004).

**Verificeret 30/07-2026:** detektoren blev kørt mod den faktiske kode i
begge grene. Den fælder gren A's `timeline.py` (*"lagringsmodul definerer
abonnementsflade"*) og frikender gren B's, basens `repository.py` og basens
`event_bus.py` — sidstnævnte fordi bussen netop **må** have en
abonnementsflade. Reglen er retningsbestemt, ikke et forbud mod abonnementer.

---

## ADR-A4-003 — Dormant Runtime

**Beslutning.**

- Ingen **applikationsstyrede** polling-loops.
- Ingen `while True` kombineret med `sleep` i `worker/app/agent4/**`.
- **OS-blokering er acceptabel.**
- **Platformsspecifikke OS-primitiver er acceptable** (fx Win32 `LockFileEx`).
- Aktiv polling kræver en eksplicit arkitekturbeslutning — ikke en kommentar.

**Kontekst.** Invarianten hed oprindeligt blot *"ingen polling"*. Den
formulering holdt ikke ved måling:

> På POSIX blokerer `fcntl.flock(fd, LOCK_EX)` ægte i kernen. På Windows ser
> `msvcrt.locking(fd, LK_LOCK, n)` blokerende ud, men forsøger internt igen
> hvert sekund op til ti gange. Polling forsvinder ikke — den flytter ned i
> C-runtimen, hvor den hverken kan ses i et review eller måles af en gate.

Et forbud mod al ventning ville altså have skubbet løkken derhen, hvor ingen
kunne se den. En synlig løkke er bedre end en skjult. Reglen rammer derfor
det, der faktisk er problemet: løkker, vores egen kode styrer.

**Håndhævet i** `tests/workflow_agent4_dormant_runtime.py`. Detektionen er
AST-baseret, ikke tekstsøgning: en fil må gerne indeholde både en `while True`
og et `sleep` hver for sig — det er kombinationen i samme løkkekrop, der er
ventemekanismen.

**Verificeret 30/07-2026** mod den faktiske kode i alle grene: gaten fælder
`#267`'s `timeline_lock.py` (linje 169) og er ren på alle øvrige.

---

## ADR-A4-004 — Navngivning

**Status: afgjort 31/07-2026.** Omdøbningen gennemføres før `#253` lander.

### Fire lukkede spørgsmål

1. **De to A4-grene var ikke et bevidst design-spike.** De opstod utilsigtet
   mellem sessioner og skulle ikke have udviklet sig til to merge-klare
   arkitekturer. Gren B (`#258`-linjen) er referencearkitektur. Gren A er kun
   kilde til afgrænsede idéer, der genimplementeres bevidst oven på B.
2. **`watchdog.py` var tænkt som en rent kalder-drevet health/intervention-
   grænse.** Ingen selvkørende watcher, timer eller intern observationsløkke
   var planlagt i Agent 4. En fremtidig host må kalde grænsen eksplicit;
   cadence og scheduling ligger uden for Agent 4.
3. **`#267`'s timeout var defensiv, ikke et funktionskrav.** Den bæres ikke
   videre. `#267` ligger på den fravalgte A-gren. Hvis B senere får behov for
   cross-process writer-arbitration, designes det som en ny afgrænset slice
   med OS-blokering eller en platformsspecifik primitiv og uden
   applikationsstyret polling.
4. **Scopet er den fulde semantiske løsning.** Moduler, offentlige typer,
   imports, tests og dokumentation omdøbes samlet. Der tilføjes ingen
   kompatibilitetsaliaser, fordi Agent 4-koden endnu ikke er landet på main.

### Autoritativ navnemapping

- `scheduler.py` → `campaign_queue.py`. Den eksisterende `CampaignQueue`-API
  beholdes; det er modulet og scheduler-ordlyden omkring den passive kø, der
  var misvisende.
- `retry_scheduling.py` → `failure_handling.py`.
  `CampaignRetrySchedulingService` → `CampaignFailureHandlingService` og
  `RetryScheduleResult` → `FailureHandlingResult`.
- `WatchdogAction` → `HealthInterventionAction`.
- `WatchdogPolicy` → `HealthPolicy`.
- `WatchdogDecision` → `HealthDecision`.
- `CampaignWatchdogPolicy` → `CampaignHealthPolicy`.
- `watchdog.py` → `health_intervention.py`:
  - `WatchdogActionHandler` → `HealthInterventionHandler`;
  - `WatchdogCompositionError` → `HealthInterventionCompositionError`;
  - `WatchdogExecutionError` → `HealthInterventionExecutionError`;
  - `WatchdogExecutionResult` → `HealthInterventionResult`;
  - `CampaignWatchdogCoordinator` → `CampaignHealthInterventionCoordinator`.
- `watchdog_adapters.py` → `health_intervention_adapters.py`:
  - `WatchdogLifecycleService` → `HealthInterventionLifecycleService`;
  - `WatchdogAdapterCompositionError` →
    `HealthInterventionAdapterCompositionError`;
  - `CampaignWatchdogFailClosedService` → `CampaignHealthFailClosedService`;
  - `WatchdogServiceAdapters` → `HealthInterventionServiceAdapters`.

### Adfærdsgrænse

Omdøbningen er mekanisk. Enum-værdier, persistente payload-felter og øvrige
wire-formater ændres ikke som en skjult del af navnearbejdet. Den ændrer ingen
runtime-adfærd, starter intet og udvider ikke Agent 4's scope.

**Begrundelse.** Et modulnavn og en offentlig type skal beskrive den adfærd,
en kalder faktisk får. En passiv kø er ikke en scheduler, en eksplicit
fejlhåndteringstjeneste scheduler ikke selv noget, og en kalder-drevet
interventionsgrænse er ikke en selvkørende watchdog. Et misvisende navn løses
ved omdøbning, ikke ved en permanent undtagelse til dormans-invarianten.

**Sekvens.** Beslutningen lander i denne ADR først. Derefter gennemføres den
mekaniske omdøbning på `#253`; testene flytter med. Først når den eksakte
branch-head er grøn mod de aktive governance-gates, kan `#253` landes.

---

## Status og ejerskab

`worker/app/agent4/**` ejes af **Sol** jf. `SOL-CLAUDE-SAMARBEJDE.md`, som er
uændret. Disse beslutninger ændrer ikke ejerskab, lukker ingen PR'er og
merger ingenting. De fastlægger den arkitektur, det videre arbejde skal
opfylde — og de to gates gør, at opfyldelsen kan måles i stedet for at blive
husket.

Gates er skrevet, så de passerer tomt, når pakken ikke findes, og scanner
den fuldt, når den gør — de hævder ingen aktuel merge-status. Aktuel tilstand
aflæses af de genererede tilstandsdokumenter, aldrig af ADR'er.

**Regel:** ADR'er beskriver beslutninger og deres konsekvenser — de må ikke
hævde, hvad der aktuelt er merged. En statuspåstand i et beslutningsdokument
bliver falsk i samme øjeblik, virkeligheden flytter sig, og læses derefter
som sandhed. (Reglen er indført, efter at netop dette afsnit nåede at blive
falsk.)

Hver detektor køres mod overtrædende prøver, fordi *en test, der kun kan
bestå, ikke er en test* — samme mønster som `tests/workflow_agent3_dormant.py`.

---

## ADR-A4-005 — Én referencearkitektur

**Truffet af Anders 31/07-2026**, efter at gennemgangen konstaterede, at Agent
4 havde udviklet sig i **to parallelle, merge-klare arkitekturer**. ADR-A4-001
valgte mellem dem. Denne ADR handler om, at situationen ikke må kunne opstå
igen.

### Beslutning

Der må kun eksistere **én aktiv referencearkitektur** for Agent 4.
Referencearkitekturen er den eneste retning, som må modtage nye funktionelle
PR'er.

Alternative implementeringer må kun eksistere som **spikes, eksperimenter
eller prototyper**. De må ikke udvikle sig til parallelle merge-klare stakke.

### Krav ved en alternativ retning

- Den markeres **eksplicit** som eksperiment.
- Den må **ikke** blive base for nye stacked PR'er.
- Den skal enten **adopteres** som ny referencearkitektur gennem en ADR, eller
  **lukkes**.

### Konsekvens for alle fremtidige Agent 4-PR'er

Hver PR skal angive:

- hvilken ADR den implementerer,
- hvilken referencearkitektur den bygger på,
- hvilke eksisterende PR'er den afhænger af.

**Kan en PR ikke placeres entydigt i referencearkitekturen, stoppes den**,
indtil arkitekturen er afklaret.

### Review-gate

Ved review skal alle fire besvares med **ja**:

1. Bygger PR'en på den aktuelle referencearkitektur?
2. Implementerer den eksisterende ADR'er?
3. Introducerer den **ikke** en alternativ arkitektur?
4. Er dens afhængigheder entydige?

Ét **nej** betyder, at PR'en ikke må landes.

**Note om håndhævelse.** ADR-A4-002 og A4-003 er maskinelt målbare og
håndhæves af gates. Denne review-gate er det ikke i sin helhed — den kræver et
menneskes eller en reviewers vurdering. Den ene del, der *kan* automatiseres,
er dokumentationskravet ovenfor: at hver PR-beskrivelse faktisk indeholder ADR,
referencearkitektur og afhængigheder. Det er ikke bygget, og det er en åben
mulighed, ikke en truffet beslutning.

---

## Implementeringsdirektiv — Agent 4

**Anders, 31/07-2026. Governance-fasen er afsluttet.** Fra dette punkt er målet
ikke at skabe flere arkitekturvalg, men at implementere den vedtagne
referencearkitektur konsekvent.

### Arbejdsregel — dokumenteres for hver PR

- **Formål** (én sætning)
- **Implementeret ADR**
- **Afhængighed** af tidligere PR'er
- **Påvirkede moduler**
- **Bekræftelse** af grønne CI-gates
- **Bekræftelse** af, at dormans-invarianterne fortsat overholdes

Kan en PR ikke beskrives inden for denne ramme, **skal den opdeles** i mindre
ændringer.

### Review-kriterier for landing

En PR er først klar, når den:

- implementerer **præcis ét** afgrænset skridt,
- ikke introducerer ny arkitektur,
- ikke udvider scopet,
- består **alle** relevante gates,
- passer ind i B-referencearkitekturen.

### Stopregel

Afdækker implementeringen et behov for at **ændre** en ADR, **stoppes
implementeringen**. Arkitekturen ændres først gennem en ny ADR og derefter
gennem kode — aldrig omvendt.

### Fokus indtil videre

1. Landing af fundamentet.
2. Konsolidering af B-stakken.
3. Fjernelse af den parallelle A-stak.
4. Stabilisering af Agent 4 på `main`.

**Ingen nye funktionelle spor åbnes, før denne proces er afsluttet.**

---

## ADR-A4-006 — Autoritativ kampagnestate, reparerbar timeline-projektion og single-writer host-ejerskab

**Truffet af Anders 31/07-2026. Status: besluttet.** Supplerer ADR-A4-001,
ADR-A4-002, ADR-A4-003 og ADR-A4-005; implementeres af stabiliseringsslicen
A4-11.

Fuldteksten — de syv beslutninger, crash-semantikken og de obligatoriske
kontrakttests — bor i `docs/agent4/ADR-A4-006_STATE_PROJECTION.md` og står
kun dér. Denne indgang gengiver ikke beslutningsteksten; den findes, så
filen her forbliver det komplette indeks over Agent 4's
arkitekturbeslutninger.

## ADR-A4-007 — Operator-API'ets host-, transport- og auth-grænse efter A4-13

**Truffet af Anders 01/08-2026. Status: besluttet** (issue #308). Supplerer
ADR-A4-005 og ADR-A4-006; implementeres af A4-14 (worker-mount) og en
separat backend-slice (proxy + `agent4:read`-grant).

Fuldteksten — de syv beslutninger (worker-hostet, kun backend-proxied,
paired-device Bearer + eksplicit grant, default-off flag med én mount-ejer,
kun read, kanoniske hash-bound cursors, én injiceret context) og de ni
obligatoriske kontrakttests — bor i
`docs/agent4/ADR-A4-007_OPERATOR_API_BOUNDARY.md` og står kun dér. Denne
indgang gengiver ikke beslutningsteksten; den findes, så filen her forbliver
det komplette indeks.

**Historik.** Beslutningen blev truffet med klausulen *»gælder før
genimplementeringen af Agent 4 runtime composition«*. Kompositionen (A4-09)
og operator-read-modellen (A4-10) landede, før ADR'en var indskrevet.
Klausulens formål — at kompositionen bygges mod kontrakten — er
efterfølgende opfyldt ved bevis frem for ved rækkefølge: A4-11's testsuite
beviser kontrakttest 6-8 (delt writer/recorder pr. kanonisk dataroot,
afvisning af en anden writer-context i samme proces, ingen tråde ved import
og komposition). Forløbet er dokumenteret i `SOL-CLAUDE-SAMARBEJDE.md`
(31/07).
