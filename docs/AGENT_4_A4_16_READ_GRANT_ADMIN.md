# Agent 4 A4-16 — local `agent4:read` grant administration

## Scope

A4-16 adds one explicit operator action for one fixed capability:

```text
agent4:read
```

It is not a general RBAC system and accepts no model- or caller-supplied grant
name.

## Activation

The backend route is absent unless exact opt-in is set:

```powershell
$env:KALIV_AGENT4_GRANT_ADMIN = "1"
$env:MODELRIG_ADMIN_KEY = "<separate operator secret>"
```

The route accepts loopback callers only. A paired-device Bearer token is not
admin authority and cannot grant itself access.

## CLI

Build or run the dedicated local command from `backend`:

```powershell
go run ./cmd/modelrig-agent4-grants -grant <DEVICE_ID>
go run ./cmd/modelrig-agent4-grants -revoke <DEVICE_ID>
```

The command:

- requires `MODELRIG_ADMIN_KEY`;
- accepts only a loopback HTTP backend URL;
- follows no redirects;
- talks to the already-running backend;
- has no offline JSON-store fallback;
- prints no token or admin key.

The default backend is:

```text
http://127.0.0.1:8080
```

## HTTP boundary

Exact routes:

```text
PUT    /api/v1/admin/devices/{id}/grants/agent4-read
DELETE /api/v1/admin/devices/{id}/grants/agent4-read
```

Required header:

```text
X-Admin-Key: <MODELRIG_ADMIN_KEY>
```

Successful response:

```json
{
  "device_id": "...",
  "grant": "agent4:read",
  "enabled": true,
  "changed": true
}
```

Repeated grant/revoke calls are successful and return `changed: false`.

## Persistence and rollback

`Store.SetAgent4ReadGrant` owns the mutation. It:

- preserves unrelated grants;
- never appends a duplicate during normal operation;
- removes every `agent4:read` entry on revoke;
- persists with the existing atomic temp-file replacement;
- restores the exact previous in-memory grant slice if persistence fails;
- reports an unknown device without changing state.

Auth reads the live store on every request, so revoke takes effect on the next
request without re-pairing or backend restart. The state also survives restart.

## Audit

Every attempt logs:

- device ID;
- fixed grant name;
- grant/revoke action;
- loopback-admin actor boundary;
- UTC timestamp;
- result classification.

The audit does not contain the admin key, paired-device token or token hash.

## Safety and non-goals

A4-16 does not add:

- Agent 4 writes or lifecycle controls;
- remote grant delegation;
- Android admin UI;
- arbitrary scope strings;
- direct JSON editing;
- a second device-store writer;
- unattended activation.

`production_activation` remains `false`.

## Validation

Backend tests cover:

- default-off route inventory;
- separate admin authority;
- loopback-only enforcement;
- missing/wrong key handling;
- idempotent add and revoke;
- preservation and restart persistence;
- rollback on write failure;
- unknown device failure;
- full `403 → 200 → 403` Agent 4 read transition;
- loopback-only CLI URL validation.
