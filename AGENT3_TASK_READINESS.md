# Agent 3 task-readiness contract (T-021)

**Status:** dormant evidence gate and typed developer UI delivered; normal task routing remains Agent 2 until T-020 physical review and a later integration slice.

## Purpose

`GET /api/v1/experimental/agent3/task-readiness` combines two independent,
version-bound evidence sources:

1. the existing physical Agent 3 rig-validation assessment;
2. the T-020 read-only pilot report (`kaliv-agent3-readonly-pilot/v1`).

The endpoint is mounted only when `KALIV_AGENT3_ENABLED=1`, remains behind the
paired-device Bearer boundary and performs no model or tool call.

## Hard invariants

The v1 response always states:

- `selected_surface=agent2`;
- `candidate_surface=agent3_readonly`;
- `fallback_surface=agent2`;
- `normal_chat_route_unchanged=true`;
- `production_activation=false`;
- `ui_contract.route_source=server_authoritative`.

The worker router rejects a provider that tries to return another selected
surface or claim activation. Android and desktop independently reject an
unknown schema, unknown surface, non-server routing or an activation claim.

A valid report can therefore make `eligible_for_task_ui=true`; it cannot route a
single user turn.

## Evidence requirements

Pilot evidence is trusted only when the operator explicitly configures
`KALIV_AGENT3_PILOT_REPORT`. No default path is scanned or guessed. The file:

- must be a regular, non-symlink JSON file of at most 2 MiB;
- must be fresh (default 168 hours, bounded by
  `KALIV_AGENT3_PILOT_MAX_AGE_HOURS`);
- must match the running `VERSION` and runtime code fingerprint;
- must name a valid Git commit SHA;
- must declare experimental read-only execution and no activation;
- must report exactly 20/20 successful tasks, no failures, errors or retries;
- may report non-negative replans, which remain visible in the UI;
- must contain 20 successful `rig_tools_local` results without confirmation
  events;
- must prove stop after one read and fallback of the same turn to `/api/v1/chat`.

The physical rig-validation must independently remain fresh, version-matched,
code-matched and eligible for developer preview.

## Operator switch

`KALIV_AGENT3_TASK_UI=1` records operator intent. Its default is off. In this
slice it does not activate routing; with valid evidence the server reason is
`task_ui_integration_not_delivered`. With the switch off, evidence remains
visible but the reason is `operator_disabled`.

## Developer UI

The existing Android and desktop Validation Center now reads both protected GET
endpoints and displays:

- selected, candidate and fallback surfaces;
- the server-authored reason list;
- pilot success count, replans and retries;
- freshness, version/code binding and stop/fallback proof;
- the permanent normal-chat and production locks.

The clients expose no write or activation method.

## Remaining T-021 work

This PR deliberately does **not** finish T-021. After PR #98 is reviewed and a
physical 20/20 pilot report exists for the exact candidate:

1. review and commit dated evidence;
2. add the actual normal task-UI integration behind this server gate;
3. preserve Agent 2 for unknown/stale evidence and every client/server error;
4. device-test Android and desktop stop, fallback, receipts, replans and final
   outcome rendering;
5. prove disabling the operator switch restores the prior experience without
   migration or lost chat state.
