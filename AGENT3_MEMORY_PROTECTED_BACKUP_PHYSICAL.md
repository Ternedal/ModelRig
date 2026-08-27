# T-033 physical protected-memory backup/restore

**Status:** dormant Windows-rig operator and evidence gate. Nothing in this flow
runs at worker startup, touches the active memory database, merges a branch,
publishes a release or activates production.

## Why two Windows users are required

Windows DPAPI `current_user` is not proven by a same-user roundtrip alone. The
physical campaign therefore has two independent phases:

1. the owner Windows SID creates, migrates, backs up and restores a dedicated
   private/secret fixture;
2. another Windows SID receives only the ciphertext bundle and must fail to
   restore it.

The final collector rejects a probe made by the owner SID, an unexpected
cross-user success, a visible failed-restore destination or an unbounded/unknown
error result.

## Start the same-user phase

On the exact candidate Windows rig, double-click:

```text
START_AGENT3_MEMORY_BACKUP_PHYSICAL.cmd
```

or run:

```powershell
.\START_AGENT3_MEMORY_BACKUP_PHYSICAL.cmd prepare --operator Anders
```

The operator checks out the exact physical-operator branch, requires a clean and
version-consistent candidate, and records its version, Git SHA, worker code
fingerprint and identity source.

It creates a **dedicated fixture database** under:

```text
validation\agent3-memory-protected-backup-physical\<campaign-id>\
```

The fixture contains one public control plus one private and one secret random
canary. The private source reference is also random. Raw protected values exist
only in process memory while the same-user checks run.

The wizard then:

- migrates the fixture with real Windows DPAPI current-user protection;
- normalizes SQLite/WAL state;
- creates and independently verifies the ciphertext-only backup bundle;
- restores to a new absent database path;
- reopens exactly the private and secret canaries through
  `LOCAL_MANAGEMENT` access;
- scans the source database family, bundle, restored database family, request
  and log in UTF-8, UTF-16LE and UTF-16BE form;
- stores only SHA-256 hashes and memory ids in `state.json`;
- stages the ciphertext bundle plus a candidate-bound request below Public
  Documents for the second Windows account.

A green same-user phase is **not** a green T-033 report.

## Run the cross-user probe

The first phase prints the generated canonical campaign id, for example:

```text
t033-20260824-104800-abcd1234
```

For the current-head proof adapter, that id is enough to derive both Public
paths. Run exactly one process under a genuinely separate Windows account/SID,
for example from the owner session with `runas`:

```powershell
runas /user:<ANDEN-BRUGER> "python \"<repo>\scripts\proof_t033_current.py\" probe --campaign-id t033-20260824-104800-abcd1234"
```

`--campaign-id` is deliberately strict and accepts only the canonical
`t033-YYYYMMDD-HHMMSS-<8 lowercase hex>` form. It cannot contain slashes,
backslashes, traversal segments or alternate output paths. The adapter derives:

```text
%PUBLIC%\Documents\Kaliv-T033\<campaign-id>\request.json
%PUBLIC%\Documents\Kaliv-T033\<campaign-id>\probe.json
```

and then delegates to the **same existing physical probe**. It does not weaken,
replace or reinterpret the T-033 evidence contract.

The legacy explicit-path form remains available for diagnostics/backward
compatibility:

```powershell
python .\scripts\proof_t033_current.py probe `
  --request <public-request.json> `
  --output <public-probe.json>
```

Do not mix `--campaign-id` with explicit request/output paths; campaign-id mode
is intentionally exclusive and fail-closed.

The probe:

- verifies the same exact candidate and backup database SHA-256;
- rejects the owner SID;
- attempts restore with the second account's real DPAPI current-user key;
- accepts only a protected-memory/DPAPI denial;
- requires the failed restore destination to remain absent;
- writes no canary value and carries `production_activation=false`.

An unexpected successful restore is red.

## Collect the physical report

After the cross-user `runas` process finishes, the owner session can rerun the
proof campaign. It finds the existing exact-SHA state and probe and performs the
normal collect path; it must not create a fresh campaign just to rediscover the
probe.

For a direct/manual collect, the same campaign id can be used instead of copying
both absolute paths:

```powershell
python .\scripts\proof_t033_current.py collect `
  --campaign-id t033-20260824-104800-abcd1234
```

The adapter then derives:

```text
validation\agent3-memory-protected-backup-physical\<campaign-id>\state.json
%PUBLIC%\Documents\Kaliv-T033\<campaign-id>\probe.json
```

and delegates to the unchanged collector. The legacy explicit-path form is still
accepted by the underlying operator.

The operator must type this exact phrase:

```text
JEG HAR KØRT T-033 BACKUP RESTORE PÅ WINDOWS RIGGEN
```

A blank Enter, `ja` or a partial phrase cannot produce a report.

The independent gate does not trust a producer success bit. It rechecks:

- exact candidate identity in state and probe;
- campaign and candidate freshness (maximum 12-hour campaign, 24-hour age);
- distinct valid owner/probe Windows SIDs;
- all required same-user checks;
- zero sensitive plaintext matches;
- exact artifact inventory, repository confinement, file regularity, byte counts
  and SHA-256;
- backup digest parity between the same-user state and cross-user probe;
- bounded DPAPI denial and absent cross-user destination;
- `production_activation=false` everywhere.

The final schema is:

```text
kaliv-agent3-memory-protected-backup-physical/v1
```

## Evidence boundary

The campaign-id mode is **operator ergonomics only**. The same physical Windows
DPAPI current-user proof, exact candidate binding, distinct-SID requirement,
manual attestation and independent gate remain authoritative. A passing CI
contract test for campaign-id plumbing is not T-033 physical evidence.

CI is not the physical Windows rig. CI can test the state machine, mutations and
real DPAPI on an ephemeral Windows runner. It cannot honestly claim that the
actual ModelRig Windows profile and a second real profile were used. T-033 remains
open until this operator creates a green report on the exact physical candidate.
