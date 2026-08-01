# Agent 4 A4-13 — Bounded evidence operator reads

## Formål

Gør de first-class evidensrecords fra A4-12 læsbare gennem en bounded,
transport-uafhængig operatorgrænse uden at montere en API eller ændre den
landede A4-09 runtime-composition.

A4-13 genbruger A4-12-identitet, record-hash og append-only kæde. Den opretter
ikke en alternativ evidensmodel.

## Leverance

- hash-bundne cursors for evidensrecord-kæden;
- bounded paging med maksimum 1.000 records pr. kald;
- valgfrit snapshot-head, så paging er stabil mens nye records appendes;
- direkte opslag via kampagne-id og `evidence_id`;
- verificeret kædesummary for operatorer;
- eksplicit kontrol af, at operator-service og query-service deler præcis samme
  record-store;
- campaign existence-check gennem den eksisterende scheduler før operator-read.

## Fail-closed regler

- cursorens kampagne-id, sekvens og record-hash skal matche den validerede kæde;
- en cursor efter kædens head afvises;
- `after` må ikke ligge efter det valgte snapshot-head;
- sider skal være sekventielt sammenhængende;
- `has_more` afledes af cursor-positionerne og kan ikke sættes frit;
- ukendt kampagne afvises før opslag i evidensstoren;
- ukendt `evidence_id` giver en eksplicit not-found-fejl;
- query/store-mismatch afvises ved composition.

## Dormans

A4-13 er ren read-composition:

- ingen route eller transportadapter;
- ingen runtime-mount;
- ingen thread, timer, polling eller baggrundscadence;
- ingen state-write, cursor-persistens eller delivery-progress;
- ingen Agent 3-dispatch;
- ingen ændring af A4-06 delivery/query eller A4-11 projections.

Konstruktion skaber ingen filer. Reads validerer de eksisterende kæder gennem
A4-12-storen.

## Implementering

- `worker/app/agent4/timeline_evidence_query.py`
  - `CampaignEvidenceQueryCursor`
  - `CampaignEvidenceQueryPage`
  - `CampaignEvidenceQueryService`
- `worker/app/agent4/operator_evidence.py`
  - `Agent4OperatorEvidenceReadService`
  - `CampaignEvidenceRecordNotFoundError`
- `tests/workflow_agent4_evidence_operator_read.py`

## Senere integration

En fremtidig host-adapter kan montere disse reads bag en eksplicit operator-API.
Det er en separat aktiveringsbeslutning og må ikke introducere en anden cursor,
evidensidentitet eller skjult cadence.
