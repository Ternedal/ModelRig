# T-038 Home Assistant: consented live read-only test

**Status: PENDING, not run.** Nobody has read a real Home Assistant through
T-038 yet. This page says what the fixture evidence proves, what it does not
prove, and how the consented live read is run and recorded.

Tracking: KalivNexus #1, and P0 "Read-only NAS/Home Assistant journey" in
ModelRig #2264.

## What is already proven, without hardware

`tests/worker_home_rig_e2e_fixture.py` runs the whole read path. The only
fixture is the Home Assistant server itself, a stdlib HTTP server on
`127.0.0.1`. The workflow `t038-home-assistant-e2e` runs it, re-checks its
JSON report with `--check` against the same checkout, and keeps the report as
an artifact.

`--check` confirms four things:

- the summary matches the cases;
- the recorded commit equals `HEAD`;
- the files under test have no uncommitted changes;
- every recorded file hash equals the file on disk.

The report is **not signed**. It is consistency evidence for one exact
commit, not proof of who produced it, because anyone who can rerun the test
can produce a new report.

The test covers:

- A scoped entity read returns a fresh receipt with `source`, `source_id`,
  `observed_at` and `freshness`. Exactly one `GET /api/states/<entity>` is
  sent, carrying the deployment bearer.
- A T-032 permission can be used once.
- An unscoped entity, `http://` without opt-in, and a group- or world-readable
  token file never reach the server.
- A 401 response, a timeout (5 s) and a body for another entity are never
  reported as state.
- Wake and control previews never reach the server, and the server only ever
  receives `GET`.
- The bearer and Home Assistant attributes never appear in the receipt, the
  audit log, the sharing ledger, the databases, the logs or the report.

## What the fixture cannot prove

- Behaviour against a real Home Assistant version and its real state JSON.
- TLS to Home Assistant, because the fixture uses plaintext on loopback.
- Name resolution of `homeassistant.local` and other LAN names, and the LAN
  path itself (latency, Wi-Fi, a sleeping NAS).
- That the token file on the **Windows rig** is protected. The file-mode check
  in `_load_bearer` applies only on POSIX. On Windows no ACL check is made, so
  the protection rests on the folder's permissions. This is a known limitation
  and is not changed here. A narrow, default-deny design for checking the
  Windows DACL is in `docs/T038_WINDOWS_TOKEN_ACL_DESIGN.md`.

## Operator entry point

A read used to happen only through the ToolGate tool `home_assistant_read`,
which a model must choose to call, so a live test could not be repeated.
`scripts/t038_operator_read.py` is now the deterministic operator entry point.
It adds no capability: it runs the same `HomeRigRuntime.read` with the
worker's own grant store, audit log and T-032 ledger, and the same deployment
settings. It reads exactly one entity, once, and has no rig, preview or write
path.

Before it makes any network or credential access, it refuses unless
`KALIV_HOME_RIG_PILOT=1` is set and `--confirm-live-read` is given.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | observed and fresh |
| 3 | Home Assistant unavailable (`unknown`) |
| 1 | denied, or a configuration failure |
| 2 | refused |

`tests/worker_t038_operator_read.py` runs the script as a real subprocess
against the loopback fixture.

## Live test protocol

These steps require Anders' explicit consent for each run. Use one entity,
and only one with harmless data (for example a temperature sensor).

1. **Token in a file, never on the command line.** Create a long-lived Home
   Assistant token locally and store it on one line in a file that only your
   user can read, for example `C:\Rig\secrets\ha.token`. Never put it in chat,
   in an issue or in a log.
2. **Deployment settings** in the worker's environment:
   - `KALIV_HOME_RIG_PILOT=1`
   - `KALIV_HOME_ASSISTANT_ORIGIN=https://<ha-host>:8123`. Use `http://` only
     on a LAN address, and then also set
     `KALIV_HOME_ASSISTANT_ALLOW_INSECURE_HTTP=1`. A global address is always
     refused for plaintext.
   - `KALIV_HOME_ASSISTANT_TOKEN_FILE=<absolute path to the file>`
3. **Scope.** Call `POST /home-rig/grants/preview` and then `POST
   /home-rig/grants` on the loopback worker (`127.0.0.1:8099`). The scope must
   contain exactly the one entity and the operation `entity_state`, and the
   second call must send the `expected_scope_sha256` returned by the first.
4. **Permission.** Call `POST /home-rig/sharing/preview`, then `POST
   /home-rig/sharing/permissions` with the `expected_request_digest` from the
   preview, then `POST /home-rig/sharing/permissions/<id>/approve` with
   `{"confirm": true}`.
5. **Read** the entity once, in the worker's environment (same `KALIV_*`
   settings, so the same stores are used):

   ```powershell
   python scripts\t038_operator_read.py --entity sensor.<one_entity> --permission-id dsp_<id> --confirm-live-read --evidence validation\t038-live-read.json
   ```

   The evidence file holds the receipt, the result and only the origin's
   scheme. It holds no token, no attributes and no host.
6. **Record the evidence:**
   - the receipt: `state`, `source_id`, `observed_at`, `freshness`;
   - the `/home-rig/audit` row;
   - the T-032 receipt outcome;
   - the Home Assistant version;
   - whether you used http or https.

   Record **no** token and no attributes.
7. **Clean up.** Revoke the grant (`POST /home-rig/grants/<id>/revoke`), delete
   the token file, and revoke the token in Home Assistant.

The result counts as **PASS** only when all of these have been observed and
recorded. Missing credentials or consent mean **PENDING**, never PASS.
