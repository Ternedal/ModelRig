# Agent 4 A4-14 — Default-off worker-mounted operator read API

## Formål

Monter A4-10- og A4-13-read-services på den eksisterende loopback-only worker
uden at indføre en parallel Agent 4-runtime, en ny dataroot eller en write-flade.
Implementeringen følger ADR-A4-007.

## Aktivering og ejerskab

- eneste mount-ejer er
  `worker/app/agent4/production_mount.py::mount_agent4_operator(app, context)`;
- `KALIV_AGENT4_OPERATOR_API` er default-off, og kun præcis `"1"` tænder;
- production-entrypointet kalder mountet samme sted som Agent 3-mountet;
- flag on uden en allerede host-composed `Agent4RuntimeContext` fejler lukket;
- mountet komponerer aldrig selv og åbner ingen dataroot.

A4-09-contexten ejer nu også den kanoniske evidence record-store, recorder,
query-service og evidence-operator under samme root som campaign repository og
timeline. Konstruktion opretter fortsat ingen mapper eller filer.

## Read-flade

Prefix: `/experimental/agent4/operator`

Kun GET er registreret:

- `/campaigns`
- `/campaigns/{campaign_id}`
- `/campaigns/{campaign_id}/timeline`
- `/campaigns/{campaign_id}/evidence`
- `/campaigns/{campaign_id}/evidence/verification`
- `/campaigns/{campaign_id}/evidence/{evidence_id}`

Der findes ingen submit-, dispatch-, pause-, resume-, cancel-, checkpoint-,
retry-, intervention- eller recovery-route.

## Wire-kontrakt

Svar bruger media type
`application/vnd.modelrig.agent4.operator+json` og envelope-schema
`modelrig-agent4/operator-api/v1`.

Inde i envelopen genbruges de eksisterende kanoniske payloads direkte:

- `CampaignRecord.to_dict()`;
- `CampaignTimelineEntry.to_dict()`;
- `CampaignEvidenceRecord.to_dict()`;
- `CampaignTimelineQueryCursor.to_dict()`;
- `CampaignEvidenceQueryCursor.to_dict()`.

`after` og `snapshot_head` modtages som URL-encoded JSON-objekter i præcis den
samme cursor-model. Der findes ingen parallel cursor eller identity-model.

## Dvale og sikkerhedsgrænse

Mount og router:

- starter ingen tråde, timers, polling eller recovery;
- skaber ingen filer;
- kalder ingen lifecycle writes eller Agent 3-dispatch;
- ændrer ikke workerens loopback-only middleware;
- er ikke en fjernadgangsgrænse i sig selv.

Backend-proxy og paired-device `agent4:read`-grant er en separat slice. Indtil
den er landet, er denne worker-flade kun den dvalende, default-off host-side
kontrakt. ADR-A4-008 blokerer fortsat Agent 4-aktivering og enhver fremtidig
write-eksponering, men ikke denne read-flade.
