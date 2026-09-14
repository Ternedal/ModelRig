# DC-L16 product integration implementation handoff

**Date:** 14/09-2026  
**Status:** implementation-direction record only  
**production_activation:** false

## Purpose

ADR-DC-018 intentionally pinned the three candidate product sources and failed on source drift. The subsequent selection proposal intentionally implemented nothing. This handoff is the narrow boundary that permits one selected candidate path to change for an inert product-integration slice without rewriting either historical artifact.

## Selected implementation direction

The implementation direction is:

- operator surface: `desktop.control-center`;
- route host pattern: `backend.local-api-host-pattern`;
- exact default-off flag: `KALIV_DEVCONTROL_PILOT`;
- first route: `GET /api/v1/experimental/devcontrol-pilot/status`;
- interaction model: manual refresh only.

This is an implementation choice, not ADR-DC-015 pilot GO. `human_pilot_go_verified=false` remains mandatory.

## Exact source transition

Only the inventory-pinned backend host source is allowed to drift in this slice:

- `backend/internal/httpapi/server.go`
- from Git blob `6085d525ff86a3d2b5c7cdece20bcaeace896e85`
- to Git blob `3b202c783b288f77572611ee71e0d732183e5404`

Two new backend files are pinned independently:

- `backend/internal/httpapi/devcontrol_pilot.go` → `ddbdbb0aba2c95a63d42d6b89aeb5fbd85fd134d`;
- `backend/internal/httpapi/devcontrol_pilot_test.go` → `07b787298bfd02259f97cb7800e4b5c48d895304`.

Desktop and Android candidate source bytes remain pinned to the ADR-DC-018 inventory in this slice.

## Authority stop

The handoff does not satisfy runtime preflight and does not authorize pilot start, task execution, local commits, remote writes, push, PR mutation, merge, release, deploy or production activation.

Authority is only `dc-l16-product-implementation-handoff-only`.

A later Desktop read-only client/display may consume the status surface after this slice qualifies. Any task registry, executor or signed pilot start remains a separate authority boundary.
