# Media generation reconciliation (operator runbook)

This diagnostic is **read-only**. It does not repair jobs, infer successful
generation from a file, mount external volumes, delete files or release work.

## Preconditions

- Use an explicitly verified external media volume; `ExternalMediaSink`
  refuses an unmounted volume and symlinked media roots.
- Use the generation jobs SQLite database associated with that same worker.
- Do not treat a successful local test as proof of Windows volume or GPU
  qualification. Verify the exact PR head in CI before merge/release.

## Offline inspection

Run from the repository root using the **read-only** CLI. Replace the
paths with actual paths on the worker machine:

```sh
python3 scripts/media_reconcile.py \
  --jobs-db /path/to/jobs.sqlite \
  --volume-root /mounted-volume \
  --media-root /mounted-volume/media \
  --limit 100 --offset 0
```

Each output line is a JSON finding. Increase `--offset` by `--limit`
to inspect further pages. The CLI opens SQLite with `mode=ro` and avoids
the schema-creating `ImageJobStore.__init__`; do **not** substitute the
ordinary job-store constructor for a read-only forensic inspection.

Paging is bounded and **not snapshot-consistent**. Concurrent changes may
shift rows between pages. For exhaustive forensics, take a consistent
read-only copy of the job database while the writer is stopped.

## Interpretation

- `consistent` / `completed_legacy_indexed`: the expected indexed file
  appears present and matches catalog size; **not** proof of inference success.
- `*_with_indexed_artifact`: a receipt exists for a noncompleted job; do
  **not** automatically mark it completed.
- `*_with_unindexed_artifact`: an artifact exists but is not registered in
  the gallery; investigate before any manual repair.
- `*_recorded_asset_without_job_artifact` / `*_asset_mismatch`: SQLite
  and deterministic job evidence disagree. Preserve both for investigation.
- `completed_legacy_and_job_artifact_conflict`: legacy and deterministic
  receipts compete; never select one automatically.
- `media_conflict`, `completed_legacy_file_conflict`, missing-file and
  index errors: treat as possible corruption or inaccessible storage.

Do not implement automatic completion, re-publication or deletion from these
findings. The current G2 executor's generic artifact publication must be
integrated with deterministic `publish_and_register_for_job` before assuming
all G2 jobs can be reconciled by deterministic ID.

## Qualification

```sh
PYTHONPATH=worker python3 tests/worker_media_generation_reconciliation.py
PYTHONPATH=worker python3 tests/workflow_media_reconcile_cli.py
python3 scripts/current_state.py --check
```

The repository's `.github/workflows/_tests.yml` discovers
`tests/worker_*.py`, including this test file. Full CI and external-volume
validation remain separate gates.
