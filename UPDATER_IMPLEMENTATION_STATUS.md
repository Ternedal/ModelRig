# ModelRig updater — implementation status

**Status:** code-complete after the post-commit orchestration change; physical signed-release→signed-release acceptance remains tracked in #401 before claiming end-to-end production proof.

This status addendum records the detailed implementation evidence behind the
summary status in `UPDATER_DESIGN.md`. The design's transaction/failure model
and its implementation-vs-physical-acceptance boundary are authoritative.

## Implemented

### Transaction and recovery

- whole-set transaction journal with fail-closed parsing;
- complete immutable backup before the first target swap;
- whole-set rollback and `manual_recovery` handling;
- backend + worker version verification and advancing supervisor heartbeat;
- recovery before network access and recovery-first appliance boot;
- separate `KalivBootstrap` and on-demand `KalivSupervisor` tasks.

### Windows replacement

- `ReplaceFileW` keeps the live executable name present during replacement;
- explicit `.old` rollback copy remains under the existing journal contract;
- a replacement failure that leaves live byte-identical to `.old` is recognized
  as an already-restored original rather than a false rollback failure;
- real-Windows CI covers replacement, rollback, missing-live recovery and the
  failure-before-mutation case.

### Updater self-update

- `-version` reports the updater's compiled release identity;
- `-self-update` downloads only the updater asset;
- checksum verification is followed by release-bound DSSE/SLSA provenance
  verification for the exact repository, tag, release workflow and SHA-256;
- `.pending` is created exclusively and a detached helper replaces the updater
  only after the running process exits;
- `updater.lock` remains owned until the helper has completed its replacement
  attempt;
- after a normal appliance update, a detached watcher compares committed
  transaction fingerprints before and after the run;
- only a newly committed transaction invokes the verified self-update command;
- checks, recovery, version queries, rollbacks, already-current runs and Go test
  processes do not trigger automatic self-update;
- automatic self-update is deliberately non-gating and logs separately to
  `logs/updater-self-update.log`.

## Bootstrap reality

A binary from **before** self-update support cannot retroactively contain the
helper that replaces itself. Such an installation therefore needs exactly one
manual/bootstrap replacement of `modelrig-updater-windows-x64.exe` with a build
that contains self-update support. After that bootstrap, future successfully
committed appliance updates automatically keep the updater current.

This is not a rollback or safety limitation; it is the unavoidable transition
from a pre-self-updating binary to a self-updating one.

## Evidence still required on the physical rig

CI proves logic and Windows API behaviour, but it cannot honestly prove the
specific installed rig, Task Scheduler configuration, antivirus/file-locking
behaviour or power-loss timing. Physical end-to-end acceptance remains #401 and
requires:

1. start from a known older self-update-capable updater;
2. run a normal update to a newer signed release;
3. prove backend, worker and supervisor commit successfully;
4. prove `logs/updater-self-update.log` records the post-commit follow-up;
5. prove the live updater hash/version changes and `-version` reports the target;
6. interrupt the replacement helper and prove live remains intact while
   `.pending` remains recoverable;
7. run the process-level normal, defective-worker and kill-mid-swap matrix from
   `UPDATER_DESIGN.md` §4c.

Until that dated, candidate-bound evidence exists, the correct claim is:

> The updater implementation is complete and CI-verified; physical end-to-end
> acceptance is outstanding.
