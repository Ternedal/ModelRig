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

**Truffet af Anders 31/07-2026. Status: besluttet.** Gælder **før**
genimplementeringen af Agent 4 runtime composition. Supplerer ADR-A4-001,
ADR-A4-002, ADR-A4-003 og ADR-A4-005.

### Kontekst — målt, ikke antaget

Agent 4-lifecycle-operationer persisterer i dag kampagnestate og
timeline-event som **to separate durable writes** (målt: otte steder i
lifecycle-servicen). Et crash eller en skrivefejl imellem kan efterlade:

- en autoritativ kampagnestate uden det tilsvarende timeline-event;
- et allerede skrevet timeline-event, som lifecycle-servicen ikke nåede at
  registrere som leveret;
- en startet eller forsøgt Agent 3-dispatch, hvis historik endnu ikke er
  projiceret.

Dagens event-identitet er desuden **positionel** (`{campaign_id}:{sequence}`):
et retry efter et crash beregner en ny sekvens og skaber dermed et nyt id for
samme logiske hændelse. Repository-laget gemmer `state.revision`, men bruger
den ikke som guard.

Timeline-storage må samtidig ikke blive command source, event bus eller
dispatch-vej. En journal-autoritativ model ville både være en større
omlægning og skabe en uønsket kobling mellem historik og runtime-adfærd — og
den ville gøre timelinen til det, systemet *handler* på, i strid med
ADR-A4-002's ånd.

### Beslutning 1 — Kampagnestate er autoritativ

Den durable kampagnestate er den autoritative sandhed om kampagnens aktuelle
lifecycle-status, revision, attempt og fejltilstand. Timelinen er en
immutable **audit-projektion** af allerede besluttede lifecycle-overgange og
andre eksplicit registrerede hændelser.

Systemet må ikke:

- udlede, at en lifecycle-operation skal udføres, alene fordi et
  timeline-event findes;
- bruge timeline-storage som command queue eller dispatch-trigger;
- betragte fraværet af et timeline-event som bevis for, at en durable
  state-overgang ikke fandt sted;
- genafspille timeline-events automatisk som runtime-kommandoer.

Agent 3-dispatch, recovery og intervention styres fortsat af lifecycle-state
og de eksisterende fail-closed kontrakter — ikke af timeline-projektionen.

### Beslutning 2 — Durable projection intent

Enhver state-overgang, der skal repræsenteres i timelinen, skal gemme en
**durable projection intent sammen med den resulterende kampagnestate**.
State-overgangen og projection intent skal være del af samme atomisk
publicerede repository-record eller envelope.

Projection intent skal mindst indeholde: campaign identity; resulterende
state-revision; event-type; kanonisk JSON-safe event-payload; deterministic
event-id; event schema-version.

Dermed kan systemet efter et crash fastslå, at en autoritativ overgang
mangler sin audit-projektion, uden at rekonstruere hændelsen ud fra fri
fortolkning af den aktuelle state. **En projection intent er metadata om en
allerede besluttet state-overgang. Den er ikke en command og må ikke udføre
eller genudføre Agent 3-arbejde.**

### Beslutning 3 — Deterministisk og idempotent event-identitet

Lifecycle-events skal have en deterministisk identitet baseret på deres
stabile årsag og resulterende revision. Identiteten skal mindst bindes til:
campaign identity; resulterende state-revision; event-type; event
schema-version. Når flere hændelsestyper lovligt kan knyttes til samme
revision, skal event-type eller en anden stabil producer-identitet indgå.

Timeline-append skal følge disse regler:

1. Et nyt event-id kan appendes normalt.
2. Et allerede eksisterende event-id med **identisk kanonisk indhold**
   behandles som idempotent succes.
3. Et allerede eksisterende event-id med **andet indhold** behandles som
   corruption og fejler lukket.
4. Et retry må aldrig skabe to logiske events for samme durable
   state-overgang.

Entry-hash og event-id har forskellige formål: event-id identificerer den
logiske hændelse; entry-hash beskytter den konkrete placering og hash-kæde i
timelinen.

### Beslutning 4 — Eksplicit reconciliation

Runtime composition skal levere en **caller-driven reconciliation-service**,
som: finder durable projection intents, der endnu ikke er bekræftet i
timelinen; appenderer dem idempotent; verificerer, at et eksisterende event
med samme identitet har identisk indhold; markerer eller fjerner en
projection intent, når projektionen er verificeret; kan gentages efter crash
uden duplikering eller runtime-side effects; og fejler lukket ved
identitets-, payload- eller hash-konflikt.

Reconciliation må kun køres ved eksplicit kald — under eksplicit
startup-recovery, før eller efter en caller-drevet lifecycle-operation, eller
via en eksplicit operatorhandling.

Der må ikke introduceres: background thread; timer; polling-loop; automatisk
tailer; event-bus-subscription; implicit runtime-aktivering.

### Beslutning 5 — Crash-semantik

Implementeringen skal kunne håndtere mindst følgende vinduer:

- **State og intent gemt, timeline mangler:** recovery finder den durable
  intent og projicerer eventet.
- **Timeline appendet, intent ikke kvitteret:** recovery forsøger samme
  deterministic event-id igen; identisk event behandles som idempotent
  succes, hvorefter intent kan kvitteres.
- **Konfliktende event med samme identitet:** recovery må ikke fortsætte
  eller overskrive. Kampagnen markeres som krævende operatorintervention
  eller tilsvarende fail-closed tilstand.
- **Dispatch-outcome er ukendt:** timeline-reconciliation må ikke afgøre, om
  dispatch skal gentages. Det håndteres af lifecycle- og recovery-kontrakten
  for ukendt execution outcome.

**Audit-reparation og execution-recovery er separate ansvar.**

### Beslutning 6 — Single-writer host-ejerskab

Den kanoniske Agent 4 runtime composition skal eje **præcis ét** campaign
repository, **én** lifecycle-writer/service, **én** timeline-recorder,
**én** reconciliation-service og **ét** delt sæt process-local
coordination-objekter — per kanonisk dataroot. Alle Agent 4-services i samme
runtime-context skal dele disse instanser.

Det er ikke understøttet at komponere flere uafhængige lifecycle-writers mod
samme dataroot. Kompositionen skal, hvor det er praktisk muligt, afvise flere
samtidige writer-contexts mod samme kanoniske dataroot i samme proces.

Denne ADR introducerer **ikke**: cross-process filesystem lock; distributed
lease; global runtime-singleton; polling-baseret lock acquisition; automatisk
process arbitration. Samtidige writers fra flere processer er fortsat en
ikke-understøttet deployment-konfiguration. Cross-process fencing genovervejes
først, hvis et konkret produktkrav kræver flere Agent 4-writerprocesser.

### Beslutning 7 — Revision-CAS

Repository compare-and-swap på campaign revision er **ikke et krav** for den
første ADR-A4-006-implementering. Det kan senere tilføjes som en defensiv
stale-writer-guard uden at ændre state-autoriteten,
timeline-projektionsmodellen eller single-writer host-kontrakten. **CAS må
ikke bruges som erstatning for entydigt runtime-ejerskab.**

### Obligatoriske kontrakttests

Implementeringen skal mindst bevise:

1. crash efter state/intent-save og før timeline-append repareres;
2. crash efter timeline-append og før intent-kvittering skaber ikke duplikat;
3. identisk retry accepteres;
4. konfliktende event med samme event-id afvises fail-closed;
5. reconciliation udfører ingen lifecycle-command eller Agent 3-dispatch;
6. flere services i samme runtime-context deler samme writer og recorder;
7. en anden writer-context mod samme dataroot afvises i samme proces;
8. import og composition starter ingen thread, timer eller polling-loop;
9. storage-boundary- og dormant-runtime-gates forbliver grønne.

### Konsekvenser

**Positive:** durable state og audit-historik kan konvergere efter crash;
timeline-storage forbliver et separat, read-/append-orienteret lag; recovery
behøver ikke gætte manglende events ud fra den aktuelle state; duplicate
projection bliver sikkert og deterministisk; runtime composition får et
eksplicit ejerskabsansvar; ADR-A4-002 og ADR-A4-003 bevares.

**Accepterede begrænsninger:** state og timeline bliver ikke fysisk atomiske
på tværs af filer; der kan midlertidigt eksistere en backlog af durable
projection intents; cross-process concurrent writers understøttes ikke;
timeline er ikke en event-sourced autoritativ journal; reconciliation kræver
et eksplicit caller-kald.

### Implementeringsnoter — målt mod den landede kode (noter, ikke beslutninger)

1. **Regel 3 er allerede opfyldt** af den landede store: duplikeret
   `event_id` afvises ubetinget med `TimelineConflictError`. **Deltaet er
   regel 2:** identisk kanonisk indhold skal blive idempotent succes i stedet
   for konflikt. Opslaget pr. event-id findes allerede (lineær scanning ved
   append) og passer i den accepterede O(n²)-holdning.
2. **Projection intent findes ikke i dag** — nul forekomster i `domain.py` og
   `repository.py`. Envelope-udvidelsen af repository-recorden er ny, og den
   deterministiske id-opskrift (kanonisk hash over campaign identity,
   resulterende revision, event-type, schema-version) bør pinnes af en test,
   så to implementeringer ikke kan regne forskelligt.
3. **»Kanonisk dataroot« i Beslutning 6 kræver en definition** — realpath og,
   på Windows, case-normalisering — ellers kan samme-proces-afvisningen omgås
   af to stavemåder af samme sti.
4. Reconciliation-servicen bør skrive gennem store- og repository-API'erne og
   ikke selv røre disken; så forbliver den uden for
   storage-klassifikationen, og gate-billedet forbliver entydigt.
5. **Sekvensnote:** runtime-kompositionen (A4-09) og operator-læsemodellen
   (A4-10) landede, før denne ADR var synlig på main — beslutningen var
   truffet, men endnu ikke landet. ADR'en fungerer derfor som gap-kontrakt
   for den efterfølgende slice. Målt delta ved denne ADR's landing: ingen
   projection intent, ingen reconciliation-service, positionel
   event-identitet, ubetinget dublet-afvisning (regel 2 udestår), ingen
   samme-proces-afvisning af en anden writer-context.
