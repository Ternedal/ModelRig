# ROUTE_INVENTORY.md

**Genereret af `scripts/route_inventory.py` — rediger ikke i hånden.**

Aflæst fra appens OpenAPI-overflade, ikke fra importgrafer eller grep.
En importgraf beviser at et *modul* kan nås; den siger intet om hvorvidt
en *rute* serveres. En router kan bygges og aldrig inkluderes.

- **Host-overflade (Agent 3 slukket): 58 ruter**
- **Agent 3 tilføjer, når `KALIV_AGENT3_ENABLED=1`: 29 ruter**
- I alt tændt: 87

## Dormans-invariant

Agent 3 serverer **intet** uden det eksplicitte flag. Hver rute nedenfor
ligger under `/experimental/`, så en klient ikke kan ramme den ved et uheld,
og ingen af dem findes i host-overfladen.

## Host-ruter

- `/body/active`
- `/body/active/avatar.vrm`
- `/body/active/motions/{name}.vrma`
- `/body/active/thumbnail.png`
- `/capabilities`
- `/control-center/schedules`
- `/control-center/status`
- `/health/deep`
- `/health/full`
- `/healthz`
- `/persons`
- `/persons/active`
- `/persons/select`
- `/persons/{person_id}`
- `/persons/{person_id}/activate`
- `/persons/{person_id}/body-revisions`
- `/persons/{person_id}/person-revisions`
- `/persons/{person_id}/personality-revisions`
- `/persons/{person_id}/voice-revisions`
- `/rag/chat`
- `/rag/ingest`
- `/rag/ingest/docx`
- `/rag/ingest/docx/status`
- `/rag/ingest/html`
- `/rag/ingest/html/status`
- `/rag/ingest/image`
- `/rag/ingest/image/status`
- `/rag/ingest/pdf`
- `/rag/ingest/pdf/status`
- `/rag/ingest/pptx`
- `/rag/ingest/pptx/status`
- `/rag/query`
- `/rag/source`
- `/rag/source/enabled`
- `/rag/sources`
- `/rag/stats`
- `/schedules`
- `/schedules/preview`
- `/schedules/status`
- `/schedules/{schedule_id}`
- `/schedules/{schedule_id}/enabled`
- `/schedules/{schedule_id}/renew`
- `/schedules/{schedule_id}/renew/preview`
- `/tools`
- `/tools/audit`
- `/tools/chat`
- `/tools/chat/stream`
- `/tools/confirm`
- `/tools/confirm/chat`
- `/tools/enabled`
- `/tools/propose`
- `/voice/asr/status`
- `/voice/asr/transcribe`
- `/voice/converse`
- `/voice/converse/stream`
- `/voice/converse/upload`
- `/voice/tts/status`
- `/voice/tts/synthesize`

## Agent 3 (kun med flaget)

- `/experimental/agent3/capabilities`
- `/experimental/agent3/memory`
- `/experimental/agent3/memory/context-preview`
- `/experimental/agent3/memory/search`
- `/experimental/agent3/memory/{memory_id}`
- `/experimental/agent3/memory/{memory_id}/confirm`
- `/experimental/agent3/memory/{memory_id}/correct`
- `/experimental/agent3/memory/{memory_id}/history`
- `/experimental/agent3/memory/{memory_id}/reject`
- `/experimental/agent3/plan`
- `/experimental/agent3/plans/{plan_id}/start`
- `/experimental/agent3/replan-previews/{preview_id}/apply`
- `/experimental/agent3/runs`
- `/experimental/agent3/runs/{run_id}`
- `/experimental/agent3/runs/{run_id}/answer-preview`
- `/experimental/agent3/runs/{run_id}/cancel`
- `/experimental/agent3/runs/{run_id}/capability-receipt`
- `/experimental/agent3/runs/{run_id}/confirm`
- `/experimental/agent3/runs/{run_id}/events`
- `/experimental/agent3/runs/{run_id}/replan-preview`
- `/experimental/agent3/runs/{run_id}/replans`
- `/experimental/agent3/runs/{run_id}/resume`
- `/experimental/agent3/runs/{run_id}/retry`
- `/experimental/agent3/status`
- `/experimental/agent3/task-readiness`
- `/experimental/agent3/task/plan`
- `/experimental/agent3/task/plans/{plan_id}/start`
- `/experimental/agent3/task/runs/{run_id}`
- `/experimental/agent3/task/runs/{run_id}/cancel`
