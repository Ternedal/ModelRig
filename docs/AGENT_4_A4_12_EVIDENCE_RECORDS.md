# Agent 4 A4-12 — First-class evidence records

## Formål

Implementér det udskudte punkt i ADR-A4-001a: evidens skal kunne adresseres
som en selvstændig, immutable record i stedet for kun at eksistere som en
reference på et lifecycle-event.

A4-12 bygger på den valgte B-referencearkitektur og ændrer ikke den landede
A4-06-eventmodel. Evidensrecords bruger samme grundprincip som B: én atomisk
fil pr. record, append-only identitet, hashkæde og fuld validering ved læsning.

## Valgt afgrænsning

Evidensrecords ligger i en separat, ordnet kæde pr. kampagne. Hver record:

- har et kampagneglobalt `evidence_id`;
- kan hentes direkte uden at kende et lifecycle-event eller sekvensnummer;
- binder sig til SHA-256-headet på en allerede valideret A4-06-timeline;
- kan valgfrit pege på et konkret, eksisterende `event_id`;
- indeholder den eksisterende immutable `CampaignEvidenceReference`;
- binder sig til den foregående evidensrecord med `previous_hash`;
- har et eget indholdshash og et filnavn bundet til sekvens og identitet.

Denne sidecar-kæde er bevidst. Den gør evidens førsteklasses uden at omskrive
A4-06's event-sekvens, levering, query-cursors, A4-11-projektioner eller
allerede landede storage-kontrakter.

## Fail-closed regler

- En evidensrecord kan ikke oprettes uden en eksisterende, fuldt valideret
  kampagnetimeline.
- Et angivet `related_event_id` skal allerede findes i den validerede timeline.
- Et `evidence_id` kan kun bruges én gang pr. kampagne.
- En byte-/semantisk identisk retry returnerer den eksisterende record.
- Samme identitet med ændret digest, placering, timestamp eller relation er en
  konflikt.
- Huller, dubletter, forkert `previous_hash`, ændret record-hash, forkert
  kampagnebinding eller omdøbt fil afviser hele kæden.
- Midlertidige filer er aldrig records og ignoreres efter et afbrudt write.

## Dormans og ejerskab

A4-12 er caller-driven. Konstruktion opretter ingen mapper eller filer og
starter ingen thread, timer, polling-loop, netværkskald eller Agent 3-opgave.
Kun det eksplicitte `record(...)`-kald skriver data.

Der tilføjes i denne slice:

- ingen route eller operator-API;
- ingen runtime-mount eller baggrundsreconciliation;
- ingen ændring i Agent 3-kontrakter;
- ingen automatisk indsamling eller kopiering af evidenspayloads;
- ingen ændring af A4-06 delivery/query-cursors;
- ingen produktionsaktivering.

## Implementering

- `worker/app/agent4/timeline_evidence.py`
  - `CampaignEvidenceRecord`
  - `CampaignEvidenceVerification`
  - `CampaignEvidenceRecordStore`
  - `JsonCampaignEvidenceRecordStore`
  - `CampaignEvidenceRecordService`
- `tests/workflow_agent4_evidence_records.py`
  - roundtrip, direkte opslag, timeline-binding og relation;
  - idempotens og konflikt;
  - hash-, kæde- og filnavnstampering;
  - manglende timeline/event;
  - afbrudt write og dormant konstruktion.

## Senere integration

Et senere, separat arbejde kan eksponere bounded operator-reads eller føje
records til en samlet query-model. Det må genbruge denne identitet og kæde og
må ikke indføre en anden evidensrepræsentation eller skjult baggrundscadence.
