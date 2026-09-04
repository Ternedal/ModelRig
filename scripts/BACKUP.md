# Kaliv backup, restore and rig migration

Bundles persistent rig state that cannot be rebuilt from GitHub into one
sha256-verified archive. The same archive format is used for ordinary backup and
for the old-rig -> new-rig migration.

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

Every per-store environment override is honoured. Relative defaults resolve
through the same stable `KALIV_DATA_DIR` logic as the worker.

Not backed up: Ollama model weights, Piper voices, repository files,
`modelrig.env`, API keys, approval secrets, passwords or other credentials.
Secrets must be configured separately on the new machine; they are never copied
into a migration archive or printed by the migration operator.

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

The sidecar contains the archive SHA-256, source computer/runtime/repo identity,
GPU inventory and non-secret `modelrig.env` settings. Sensitive key names are
listed only to remind the operator what must be reconfigured; their values are
never exported.

Copy both files to the new rig. After the bootstrap has installed the new
runtime, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-new-rig-state.ps1 `
  -Action Import `
  -RuntimeRoot C:\Rig\ModelRig `
  -Archive D:\ModelRigMigration\kaliv-backup-YYYYMMDD-HHMMSS.tar.gz `
  -MinimumGpuCount 1
```

Import verifies the complete archive before writing anything, refuses to
overwrite existing state by default, starts the new appliance through
`KalivBootstrap`, and then runs `bootstrap-new-rig.ps1 -Phase Validate`.

If an intentionally disposable new rig already contains test state, explicit
`-ForceRestore` allows the verified archive to replace it. Do not use that switch
on a machine whose current state you care about.

Archive-only verification never stops services:

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
- **Verify before restore.** Every stored file is SHA-256 checked before restore.
- **No silent clobber.** Restore refuses existing destinations unless explicitly
  forced.
- **Atomic writes.** The archive and each restored file use temp + rename.
- **Stopped migration boundary.** Cross-machine export/import refuses to proceed
  if a ModelRig process remains alive after the scheduled tasks are stopped.
- **No secret export.** `modelrig.env` values matching key/secret/token/password/
  credential are never written to the migration sidecar.
- **Proven round trip.** `tests/worker_backup.py` performs create -> wipe ->
  restore -> byte-for-byte comparison plus SQLite integrity checks for every
  current database on every normal test run.

## Physical proof still required

CI proves the archive contract and script syntax, but cannot prove the actual old
and new Windows machines. Keep the old rig untouched until the new rig passes
post-restore validation and a real client can connect.