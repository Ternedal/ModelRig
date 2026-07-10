# Kaliv backup & restore

Bundles the rig state that cannot be rebuilt from the repo into one verified
archive. Roadmap V7.3.

## What is backed up
- `rag.db` — the embedding index (re-ingesting by hand is the alternative)
- `data.json` — the Go server's device tokens and pairing state
- `audit.db` — the append-only tool audit log (a security record)
- `tools-state.json` — the kill-switch decision (v1.28.0)
- `notes/` — what `note_append` wrote

Not backed up: model weights (re-pull with Ollama), Piper voices (re-download),
anything in the repo. A backup is for the irreplaceable.

## Daily use (Windows)
```
scripts\kaliv-backup.bat                 REM create -> .\backups
scripts\kaliv-backup.bat verify FILE     REM check an archive
scripts\kaliv-backup.bat restore FILE    REM restore (refuses to overwrite)
scripts\kaliv-backup.bat restore FILE /f REM restore, overwriting live data
```

Schedule a daily 03:00 backup (run once, elevated):
```
powershell -ExecutionPolicy Bypass -File scripts\kaliv-backup-scheduled.ps1
```

## Guarantees
- **Verify before restore.** A restore checks every file's sha256 first and
  refuses a corrupt archive rather than half-applying it over live data.
- **No silent clobber.** Restore refuses to overwrite existing files without
  `/f`, so you cannot wipe a working rig by accident.
- **Atomic writes.** Both the archive and each restored file are written to a
  temp path and renamed, so a crash mid-operation never leaves a half file.
- **Proven, not asserted.** `tests/worker_backup.py` does a full
  create -> wipe -> restore -> byte-for-byte round trip on every CI run.

## Not yet verified on the rig
The scripts run the same tool the tests cover, but the Scheduled Task trigger
and the Windows paths need one confirmation on the actual machine:
`Start-ScheduledTask -TaskName KalivBackup`, then check `.\backups`.
