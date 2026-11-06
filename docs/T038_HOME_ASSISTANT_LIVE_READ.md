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
- That the token file on the **Windows rig** is protected *in practice*. Since
  step 3 of `docs/T038_WINDOWS_TOKEN_ACL_DESIGN.md`, `_load_bearer` refuses a
  token file on Windows unless its owner and DACL show that only the worker's
  own account, SYSTEM and Administrators can read it, and it reads the bytes
  from the handle it judged. That rule is proven on the Windows CI runner with
  dummy files (`tests/support/windows_credential_acl_contract.py`), not on the
  rig. The fixture runs on Linux and cannot show it.

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
   in an issue or in a log. On Windows the worker **refuses** the file unless
   it is locked to **the account the worker runs as** (SYSTEM and
   Administrators may stay). That is not necessarily you: the worker is a child
   of the `KalivSupervisor` scheduled task, so take the account from the task
   and from the running worker, and check that they agree:

   ```powershell
   (Get-ScheduledTask -TaskName KalivSupervisor).Principal.UserId
   Get-CimInstance Win32_Process -Filter "Name='modelrig-worker-windows-x64.exe'" | Invoke-CimMethod -MethodName GetOwner
   ```

   Then lock the file to that account (replace `<account>` with the value,
   for example `RIG\anders`):

   ```powershell
   icacls C:\Rig\secrets\ha.token /inheritance:r /grant:r "<account>:R"
   icacls C:\Rig\secrets\ha.token
   ```

   The second command must list only that account (and optionally SYSTEM and
   Administrators). This has **not** been run on the rig yet.

   A refused token file shows up only as `unknown`; the receipt does not say
   why. If an otherwise correct read returns `unknown`, check the file with
   `icacls C:\Rig\secrets\ha.token` first. A refusal is never a reason to
   loosen the check.
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

   Only an explicit allowlist of receipt fields reaches the terminal and the
   evidence file:

   - schema, grant and scope IDs;
   - source and target;
   - state, timestamps and freshness;
   - the activation flag.

   Any field the runtime adds later is dropped and named in `omitted_fields`
   instead of being copied. The evidence file also records the result and
   only the origin's scheme; it never contains the token, attributes or host.

   The script refuses to replace an existing evidence file unless
   `--overwrite` is given. That check runs before the read, so a refusal does
   not use up the one-use permission.

   The file is written owner-only. A new file is created exclusively
   (`O_EXCL`), so if a file or link appears after the check, the write fails
   rather than overwriting it. `--overwrite` swaps the file atomically. A
   symbolic link at the evidence path is always refused; nothing is ever
   written through one.

   The evidence file is not secret, but it shows the entity's state. Keep it
   in a folder only you can read. On Windows, lock it down the same way as
   the token file:

   ```powershell
   icacls validation\t038-live-read.json /inheritance:r /grant:r "$env:USERNAME`:F"
   ```
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
