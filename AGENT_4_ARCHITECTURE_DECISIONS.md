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

**Beslutning.** Modulnavne skal beskrive adfærd. `watchdog.py`,
`scheduler.py` og `retry_scheduling.py` gennemgås **samlet**. Er de
kalder-drevne komponenter uden selvkørende eksekvering, omdøbes de **før**
landing.

**Kontekst.** Målingen viste, at `watchdog.py` (135 linjer i `#253`) hverken
har tråde, timere, `sleep` eller `while True`. Docstringen kalder den *"caller-
driven execution boundary"*, og den offentlige flade er en koordinator med et
handler-map, som en kalder skal levere. Det er en beslutnings- og
dispatch-grænse, ikke en vagthund, der selv vågner. Samme mønster gælder
`scheduler.py` (*"deterministic in-memory queue"* — en passiv prioritetskø) og
`retry_scheduling.py`.

**Begrundelse.** En watchdog er en selvkørende overvågningsmekanisme. Gør
modulet ikke det, skal navnet afspejle det. Et misvisende navn løses ved
omdøbning, ikke ved en undtagelse til invarianten — for undtagelsen ville
gælde for altid, mens navnet kun er forkert indtil nogen retter det.

**Sekvens.** Omdøbningen sker **før** `#253` lander. Det koster en rebase af
den overlevende stak, men den rebase skal udføres alligevel, og til gengæld
bliver et navn, vi allerede ved er misvisende, aldrig en del af `main`.

Mulige navne, til gennemgangen: `scheduler_boundary.py`, `dispatch_policy.py`,
`campaign_gate.py`, `campaign_decision.py`, `runtime_gate.py`.

---

## Status og ejerskab

`worker/app/agent4/**` ejes af **Sol** jf. `SOL-CLAUDE-SAMARBEJDE.md`, som er
uændret. Disse beslutninger ændrer ikke ejerskab, lukker ingen PR'er og
merger ingenting. De fastlægger den arkitektur, det videre arbejde skal
opfylde — og de to gates gør, at opfyldelsen kan måles i stedet for at blive
husket.

Agent 4-koden findes **ikke på `main`** endnu. Begge gates passerer derfor
tomt i dag og er armeret til den dag, laget lander — samme mønster som
`tests/workflow_agent3_dormant.py`, hvis dormanskrav også landede før koden.
Hver detektor køres desuden mod overtrædende prøver, fordi *en test, der kun
kan bestå, ikke er en test.*
