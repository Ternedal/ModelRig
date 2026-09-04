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
- Agent 3 run, read-review, replan, replan-preview, memory, memory-grant, plan,
  task-plan and approval-use databases;
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
ModelRig tasks, waits for every `modelrig-*` process to exit, runs the backup,
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
- **Correct relative paths.** Cross-machine migration runs the backup module from
  the live appliance runtime, so `./...` means what it means to the appliance.
- **Verify before restore.** Every stored file is SHA-256 checked before restore;
  migration import also checks the archive against its sidecar SHA-256.
- **No silent clobber.** Restore refuses existing destinations unless explicitly
  forced.
- **Atomic writes.** The archive and each restored file use temp + rename.
- **Stopped migration boundary.** Cross-machine export/import refuses to proceed
  if a ModelRig process remains alive after the scheduled tasks are stopped.
- **No restart after failed import.** A restore error leaves the appliance down
  instead of booting potentially partial state.
- **No secret export.** Only explicitly allowlisted non-secret configuration
  values enter the sidecar; sensitive or unclassified values do not.
- **DPAPI fail-closed.** Protected Agent 3 memory is rejected as a generic
  cross-machine payload until its dedicated physical restore is proven.
- **Proven round trip.** `tests/worker_backup.py` performs create -> wipe ->
  restore -> byte-for-byte comparison plus SQLite integrity checks for every
  current database on every normal test run.

## Physical proof still required

CI proves the archive contract and PowerShell syntax, but cannot prove the actual
old and new Windows machines. Keep the old rig untouched until the new rig
passes post-restore validation and a real client can connect.