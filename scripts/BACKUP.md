# Kaliv backup, restore and rig migration

Bundles persistent rig state that cannot be rebuilt from GitHub into one
sha256-verified archive. The same archive format is used for ordinary backup and
for the old-rig -> new-rig migration, with stricter operator checks around a
cross-machine move.

## What is backed up

The current inventory covers:

- RAG index (`modelrig-rag.db`);
- backend pairing/device-token state (`modelrig-data.json`);
- tool audit + persisted kill-switch state;
- async jobs and scheduler state;
- Agent 3 run, execution-progress, read-review, replan, replan-preview, memory,
  memory-grant, plan, task-plan and approval-use databases;
- home-rig pilot grant/audit/data-sharing stores;
- the notes directory used by `note_append`.

Every per-store environment override is honoured. Relative overrides in
`modelrig.env` are evaluated from the appliance runtime working directory, just
as they are when the real supervisor starts the server/worker. Other relative
defaults resolve through the worker's stable `KALIV_DATA_DIR` logic.

Not backed up: Ollama model weights, Piper voices, repository files,
`modelrig.env`, API keys, approval secrets, passwords or other credentials.
Secrets must be configured separately on the new machine; they are never copied
into a migration archive or printed by the migration operator.

### Agent 3 run/progress authority

Schema 5 treats the Agent 3 run database and execution-progress sidecar as one
persistent authority pair. A live pair carries one stable `pair_id` in both
SQLite stores. Each backup adds a fresh `snapshot_id`; verification requires
both identities, exact store roles, closed SQLite schemas and a semantically
coherent run/watermark relation before restore is allowed.

A non-empty pre-schema-5 installation is **not** silently assigned a pair id at
normal startup. Cross-machine export stops ModelRig first and then runs the
explicit offline adoption transition. Adoption revalidates the stores under an
exclusive maintenance guard and writes both pair rows in one ATTACHed SQLite
transaction. One-sided/mismatched authority or replay-risk state is refused.

The run store and progress store both use closed-schema validation: unexpected
triggers, views or indexes are authority and make backup/restore fail closed.
The minimal historical run-store shape and the full runtime shape with
`agent_events` are the only accepted run-store variants.

### Protected Agent 3 memory is not yet cross-machine portable

`KALIV_AGENT3_MEMORY_STORE=protected` uses Windows DPAPI current-user protection.
The dedicated T-033 backup path proves ciphertext-only backup and same-user key
open on Windows, but the repository does **not** yet have a physical proof that a
protected memory store can be moved to a different Windows installation/profile
and reopened safely.

Therefore `migrate-new-rig-state.ps1 -Action Export` fails closed when protected
mode is configured and a protected memory database exists. It does not silently
copy that database and call the result portable. Complete the dedicated T-033
physical migration/restore proof before moving protected memory state between
machines.

This restriction is specific to the cross-machine migration operator. The
ordinary archive inventory still knows the memory store so existing same-machine
backup/restore behavior remains visible and testable.

## Old rig -> new rig (Windows)

Use `migrate-new-rig-state.ps1` for a cross-machine move. It stops the registered
ModelRig tasks, waits for every `modelrig-*` process to exit, performs the
explicit Agent 3 legacy-pair adoption when needed, runs the schema-5 backup,
verifies it, and starts the old appliance again if it was running before export.

On the **old** rig, from a current ModelRig checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-new-rig-state.ps1 `
  -Action Export `
  -RuntimeRoot C:\Rig\ModelRig `
  -OutDir D:\ModelRigMigration
```

If the runtime is somewhere else, pass that path. When the registered
`KalivSupervisor` task exists, the script can infer its working directory if the
requested default root does not exist.

The export produces:

```text
kaliv-backup-YYYYMMDD-HHMMSS.tar.gz
kaliv-backup-YYYYMMDD-HHMMSS.tar.gz.migration.json
```

The sidecar binds the archive filename and SHA-256 to source
computer/runtime/repo identity and GPU inventory. It exports values only for an
explicit allowlist of known non-secret settings. Secret-looking keys and unknown
future settings are listed by name only and their values are not exported.

Copy **both** files to the new rig. Import requires the migration sidecar and
verifies its archive SHA-256 before the archive's own per-file verification.
After the bootstrap has installed the new runtime, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-new-rig-state.ps1 `
  -Action Import `
  -RuntimeRoot C:\Rig\ModelRig `
  -Archive D:\ModelRigMigration\kaliv-backup-YYYYMMDD-HHMMSS.tar.gz `
  -MinimumGpuCount 1
```

Import verifies the sidecar and complete archive before writing anything,
refuses to overwrite existing state by default, starts the new appliance through
`KalivBootstrap` only after restore has completed, and then runs
`bootstrap-new-rig.ps1 -Phase Validate`.

A failed or partial import deliberately leaves the new appliance **stopped** for
diagnosis. It never restarts a runtime whose restore did not complete.

If an intentionally disposable new rig already contains test state, explicit
`-ForceRestore` allows the verified archive to replace it. Do not use that switch
on a machine whose current state you care about.

Archive-only verification never stops services. If a migration sidecar is next
to the archive it is also checked; a plain ordinary backup archive can still be
verified without one:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-new-rig-state.ps1 `
  -Action Verify `
  -Archive D:\ModelRigMigration\kaliv-backup-YYYYMMDD-HHMMSS.tar.gz
```

## Daily use (Windows)

```text
scripts\kaliv-backup.bat                 REM create -> .\backups
scripts\kaliv-backup.bat verify FILE     REM check an archive
scripts\kaliv-backup.bat restore FILE    REM restore (refuses to overwrite)
scripts\kaliv-backup.bat restore FILE /f REM restore, overwriting live data
```

Restore is intentionally offline for Agent 3. A running `AgentRunStore` holds a
shared runtime lease, so restore refuses before touching live state until the
worker is stopped. Pair bootstrap uses the same shared authority so it cannot
race a restore. Restore then commits a durable `restore_in_progress` guard before
publication and clears it only after the complete archive succeeds. If a restore
is interrupted or fails after publication begins, Agent 3 startup and pair
maintenance remain blocked until a complete verified retry finishes.

Schema verification and the normal no-clobber check happen **before** the
restore marker is set. Invalid archives and ordinary no-clobber refusals therefore
do not manufacture a false incomplete-restore state. Once guarded publication
starts, however, any failure deliberately leaves the blocker set.

Schedule a daily 03:00 backup (run once, elevated):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\kaliv-backup-scheduled.ps1
```

For a machine migration, prefer `migrate-new-rig-state.ps1` rather than the
one-click backup because the migration operator establishes a stopped-appliance
boundary first.

## Guarantees

- **Complete current inventory.** The CI round-trip seeds every current
  persistent store, not only the original V7 RAG/audit files.
- **Persistent Agent 3 pair provenance.** Schema 5 binds run/progress stores with
  a stable pair id and each archive with a fresh snapshot id.
- **Closed execution schemas.** Hidden SQLite triggers/views/indexes in either
  Agent 3 execution-authority store are refused rather than transported.
- **Semantic execution validation.** Watermarks must refer to the exact run step
  and cannot make a non-idempotent pending step replayable.
- **Correct relative paths.** Cross-machine migration runs the backup module from
  the live appliance runtime, so `./...` means what it means to the appliance.
- **Verify before restore.** Every stored file is SHA-256 checked before restore;
  migration import also checks the archive against its sidecar SHA-256.
- **No silent clobber.** Restore refuses existing destinations unless explicitly
  forced.
- **Runtime/maintenance exclusion.** Restore and pair adoption cannot run beside
  an active Agent 3 runtime, and runtime cannot enter either exclusive boundary.
- **Crash-fenced pair publication.** The run path becomes a deliberate non-SQLite
  fence before progress publication and is replaced by the valid run DB last.
- **No restart after failed import.** A restore error leaves the appliance down
  instead of booting potentially partial state.
- **No secret export.** Only explicitly allowlisted non-secret configuration
  values enter the sidecar; sensitive or unclassified values do not.
- **DPAPI fail-closed.** Protected Agent 3 memory is rejected as a generic
  cross-machine payload until its dedicated physical restore is proven.
- **Proven round trip.** `tests/worker_backup.py` performs create -> wipe ->
  restore plus SQLite integrity/authority checks; dedicated Agent 3 regressions
  additionally cover restore/maintenance exclusion, pair adoption and hidden
  run-store schema authority.

## Physical proof still required

CI proves the archive contract and PowerShell syntax, but cannot prove the actual
old and new Windows machines. Keep the old rig untouched until the new rig
passes post-restore validation and a real client can connect.
