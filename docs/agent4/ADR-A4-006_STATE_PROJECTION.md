# ADR-A4-006 — Autoritativ kampagnestate og reparerbar audit-projektion

## Status

**Besluttet 31/07-2026.**

Denne ADR supplerer ADR-A4-001, ADR-A4-002, ADR-A4-003 og ADR-A4-005.
Den gælder for næste stabiliseringsslice, **A4-11**, oven på den allerede landede
B-referencearkitektur med A4-09 runtime-komposition og A4-10 operator-read-model.

ADR'en ændrer ikke den nuværende dormansgrænse: Agent 4 er fortsat caller-driven,
ikke mounted og uden route, background thread, timer eller polling-loop.

## Kontekst

Den landede lifecycle-kode gemmer kampagnestate og registrerer timeline-events som
separate durable writes. Et crash eller en skrivefejl mellem de to writes kan derfor
efterlade en autoritativ state-overgang uden den tilsvarende audit-post, eller en
audit-post som ikke blev kvitteret af produceren.

Den landede timeline-recorder bruger desuden en positionel event-identitet baseret på
campaign og sequence. Et retry efter et crash kan derfor få en ny identitet, selv om
det logisk er den samme state-overgang.

Timeline-storage må fortsat ikke blive command queue, dispatch-trigger eller event bus.
Audit-reparation og execution-recovery er separate ansvar.

## Beslutning 1 — Kampagnestate er autoritativ

Den durable kampagnestate er den autoritative sandhed om campaign lifecycle-status,
revision, attempt og fejltilstand.

Timelinen er en immutable audit-projektion af allerede besluttede state-overgange og
andre eksplicit registrerede hændelser.

Systemet må ikke:

- udføre lifecycle-arbejde alene fordi et timeline-event findes;
- bruge timeline-storage som command queue eller dispatch-trigger;
- fortolke fraværet af et timeline-event som bevis for, at state-overgangen ikke skete;
- replaye timeline-events automatisk som runtime-kommandoer.

## Beslutning 2 — Durable projection intent

Enhver state-overgang, der skal projiceres til timelinen, skal gemme en durable
`projection intent` sammen med den resulterende campaign-record.

State og intent skal publiceres atomisk som samme repository-record eller envelope.
Intenten skal mindst indeholde:

- campaign identity;
- resulterende state-revision;
- event-type;
- kanonisk JSON-safe payload;
- deterministisk event-id;
- event schema-version.

En projection intent beskriver en allerede besluttet overgang. Den er ikke en command
og må aldrig udføre eller genudføre Agent 3-arbejde.

## Beslutning 3 — Deterministisk og idempotent event-identitet

Lifecycle-events skal have en deterministisk identitet bundet til mindst:

- campaign identity;
- resulterende state-revision;
- event-type;
- event schema-version.

Hvis flere logiske events lovligt kan knyttes til samme revision, skal en stabil
producer-identitet indgå.

Timeline-append følger disse regler:

1. Et nyt event-id appendes normalt.
2. Et eksisterende event-id med identisk kanonisk indhold er idempotent succes.
3. Et eksisterende event-id med andet indhold er corruption og fejler lukket.
4. Et retry må aldrig skabe to logiske events for samme durable state-overgang.

Event-id identificerer den logiske hændelse. Entry-hash beskytter placering og
hash-kæde; de to værdier har forskellige ansvar.

## Beslutning 4 — Eksplicit reconciliation

Runtime-kompositionen skal levere en caller-driven reconciliation-service, som:

- finder ukvitterede durable projection intents;
- appender dem idempotent til timelinen;
- verificerer identisk indhold ved eksisterende event-id;
- kvitterer intenten, når projektionen er verificeret;
- kan gentages efter crash uden dubletter eller runtime-side effects;
- fejler lukket ved identitets-, payload- eller hash-konflikt.

Reconciliation må kun ske ved eksplicit kald, for eksempel under eksplicit
startup-recovery, omkring en caller-driven lifecycle-operation eller via en eksplicit
operatorhandling.

Der introduceres ingen background thread, timer, polling-loop, tailer,
event-bus-subscription eller implicit runtime-aktivering.

## Beslutning 5 — Crash-semantik

Implementeringen skal håndtere mindst disse vinduer:

- **State og intent gemt, timeline mangler:** reconciliation projicerer intenten.
- **Timeline appendet, intent ikke kvitteret:** samme event-id forsøges igen;
  identisk event er idempotent succes, hvorefter intenten kvitteres.
- **Konfliktende event med samme identitet:** processen fejler lukket og kræver
  operatorintervention eller tilsvarende eksplicit fejltilstand.
- **Ukendt dispatch-outcome:** timeline-reconciliation afgør ikke, om dispatch skal
  gentages. Det forbliver lifecycle-/recovery-kontraktens ansvar.

## Beslutning 6 — Single-writer host-ejerskab

Den kanoniske Agent 4 runtime-komposition skal eje præcis ét campaign repository, én
lifecycle-writer/service, én timeline-recorder, én reconciliation-service og ét delt
sæt process-local coordination-objekter pr. kanonisk dataroot.

Alle Agent 4-services i samme runtime-context skal dele disse instanser.

Flere samtidige writer-contexts mod samme kanoniske dataroot i samme proces er ikke
understøttet og skal afvises, hvor det praktisk kan håndhæves. Canonical dataroot
betyder realpath samt platformskorrekt case-normalisering.

Denne ADR introducerer ikke cross-process filesystem lock, distributed lease, global
runtime-singleton, polling-baseret lock acquisition eller automatisk process arbitration.
Flere writerprocesser mod samme dataroot er fortsat en ikke-understøttet deployment.

## Beslutning 7 — Revision-CAS er ikke første krav

Repository compare-and-swap på campaign revision er ikke et krav for A4-11. Det kan
senere tilføjes som defensiv stale-writer-guard, men må ikke erstatte entydigt
runtime-ejerskab.

## Obligatoriske kontrakttests

A4-11 skal mindst bevise:

1. crash efter state/intent-save og før timeline-append repareres;
2. crash efter timeline-append og før intent-kvittering skaber ikke dublet;
3. identisk event-retry accepteres;
4. konfliktende indhold med samme event-id afvises fail-closed;
5. reconciliation udfører ingen lifecycle-command eller Agent 3-dispatch;
6. services i samme runtime-context deler writer, recorder og reconciler;
7. en anden writer-context mod samme canonical dataroot afvises i samme proces;
8. import og composition starter ingen thread, timer eller polling-loop;
9. storage-boundary- og dormant-runtime-gates forbliver grønne.

## Implementeringsgrænse for A4-11

A4-11 skal være én afgrænset stabiliseringsslice oven på den landede
B-referencearkitektur. Den må ikke introducere en parallel timeline-model, ny event bus,
API-route, runtime-mount, automatisk cadence eller cross-process lock.

Den eksisterende timeline-store afviser allerede duplicate event-id. A4-11's delta er,
at identisk kanonisk indhold skal behandles som idempotent succes, mens konfliktende
indhold fortsat fejler lukket.

Projection intent og reconciliation skal gå gennem repository- og timeline-API'erne og
må ikke implementere et nyt sideløbende lagringsformat uden en ny ADR.
