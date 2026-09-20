# DC-L16 product status surface candidate

**Date:** 14/09-2026  
**Status:** implementation candidate only  
**production_activation:** false

## Scope

This slice turns the selected implementation direction into the smallest possible real product seam without creating DevControl execution authority.

The backend may mount exactly one new endpoint when, and only when, the process starts with the exact environment value:

`KALIV_DEVCONTROL_PILOT=1`

Any other value keeps the route absent.

Mounted route:

`GET /api/v1/experimental/devcontrol-pilot/status`

The route is protected by the existing paired-device Bearer middleware and returns `Cache-Control: no-store`.

## What the endpoint may say

The response is a static, non-authorizing observation contract. It identifies the intended operator surface as `desktop.control-center` and states that this candidate is manual-refresh/read-only.

It must report false for:

- automatic polling;
- unattended cadence;
- task-registry readiness;
- runtime-preflight satisfaction;
- pilot-start authorization;
- product-pilot start;
- local-commit authority;
- remote transport availability;
- remote write, push and PR mutation;
- merge, release and deploy;
- production activation.

Authority is only `dc-l16-product-status-observation-only`.

## Deliberate absences

This slice does **not**:

- import `kaliv_dev_control` into product code;
- register any `DevelopmentTask` or model-defined command;
- call the worker or any DevControl runtime;
- add credentials or a remote transport;
- expose POST/PUT/PATCH/DELETE operations under the pilot prefix;
- change Desktop Control Center UI yet;
- satisfy the runtime preflight from ADR-DC-017;
- constitute the separately signed human pilot GO from ADR-DC-015 / issue #423.

The next implementation step, if this candidate qualifies, is a Desktop Control Center **read-only display/client** for this status route. Executor wiring remains a later authority boundary.
