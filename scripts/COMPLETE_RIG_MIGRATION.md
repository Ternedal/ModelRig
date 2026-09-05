# Complete AI-rig migration

`migrate-complete-rig.ps1` is the preferred old-rig -> new-rig state operator.
It composes the independently verified ModelRig/Kaliv and VoiceRig migration
operators into one bundle and one final validation flow.

It deliberately does **not** copy secrets or licensed/private BodyRig assets.
Those remain explicit operator inputs. BodyRig now has a separate evidence-only
parity operator that records hashes/counts for the runtime assets without
copying their bytes.

## What the bundle contains

A complete bundle contains:

- one checksum-verified ModelRig/Kaliv state archive plus its migration sidecar;
- one checksum-verified VoiceRig state archive plus its migration sidecar;
- `rig-migration.json`, which binds both archives and both sidecars by SHA-256;
- no secret values.

The VoiceRig archive may contain private source audio/video only when a queued,
running or paused voice-build job needs those files to resume. The bundle
manifest records that condition and the verifier warns about it.

The bundle does **not** contain:

- ModelRig/VoiceRig API keys, tokens, passwords or credentials;
- VoiceRig `.env`;
- BodyRig licensed SMPL/SMPL-X assets;
- BodyRig's private/local SiTH diffusion model;
- machine-derived VoiceRig model readiness/runtime caches;
- rebuildable Ollama model blobs outside the bootstrap model manifest.

## 1. Prepare the old rig

Update the ModelRig and VoiceRig checkouts first. The complete operator needs the
migration operators now present on both `main` branches.

If the old rig uses the new standard layout, VoiceRig is auto-discovered at:

```text
C:\Rig\src\VoiceRig
```

A sibling `VoiceRig` checkout next to the ModelRig checkout is also
auto-discovered. Otherwise pass `-VoiceRigRepo` explicitly.

Do not remove hardware, uninstall software or delete old state before export.
The old rig remains the source of truth until physical new-rig validation is
complete.

## 2. Export one complete bundle

From a current ModelRig checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Export `
  -OutDir D:\RigMigration
```

If VoiceRig lives somewhere else on the old rig:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Export `
  -VoiceRigRepo C:\path\to\VoiceRig `
  -OutDir D:\RigMigration
```

The operator creates a unique directory such as:

```text
D:\RigMigration\rig-migration-20260904-193000-a1b2c3d4\
  rig-migration.json
  kaliv-backup-YYYYMMDD-HHMMSS.tar.gz
  kaliv-backup-YYYYMMDD-HHMMSS.tar.gz.migration.json
  voicerig-migration-YYYYMMDD-HHMMSS.tar.gz
  voicerig-migration-YYYYMMDD-HHMMSS.tar.gz.migration.json
```

Copy the **entire directory**. Do not copy only the `.tar.gz` files.

### Export consistency boundary

The complete operator asks the ModelRig state operator to create its consistent
DB snapshot and keep ModelRig stopped. It then invokes the VoiceRig operator,
which stops VoiceRig while snapshotting VoiceRig profiles/jobs and the shared
ModelRig voice/default files. ModelRig therefore cannot change the shared voice
state during that snapshot. When the complete bundle has been generated and
verified, the old ModelRig runtime is restarted through recovery-first
`KalivBootstrap` if it was running before export.

If complete export fails, `rig-migration.json` is not a valid cutover authority.
The directory is retained only as diagnostic evidence.

### Capture BodyRig private-input evidence before changing the old rig

If BodyRig is already provisioned/READY on the old machine, capture an
**evidence-only** manifest before moving hardware or deleting model files:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bodyrig-private-input-inventory.ps1 `
  -Action Capture `
  -BodyRigRepo C:\Rig\src\BodyRig `
  -OutFile D:\RigMigration\bodyrig-private-inputs.json
```

This file contains no SMPL, SMPL-X or diffusion-model payload bytes. It records
SHA-256 and byte/file counts for the assets the installed runtime actually uses:

- the installed recovery SMPL file;
- the installed SiTH `data/body_models/smplx` tree inside WSL;
- the live SiTH diffusion-model tree inside WSL.

The diffusion model is rehashed live and must still match BodyRig's validated
SiTH setup report. This deliberately catches a stale report or a model that was
changed after setup. Copy `bodyrig-private-inputs.json` to the new rig together
with the normal migration material.

If BodyRig was never READY on the old rig, there is no valid source runtime to
compare and this step should remain explicitly unproven rather than fabricating
evidence from source download directories.

## 3. Bootstrap the new rig before importing state

On the new machine, clone/update ModelRig and run the normal bootstrap first.
Keeping BodyRig out of the first pass avoids making licensed assets or the later
GPU move prerequisites for ModelRig/VoiceRig recovery:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-new-rig.ps1 `
  -Phase All `
  -SkipBodyRig
```

A reboot/WSL initialization can legitimately make the first bootstrap report a
blocker. Resolve the reported prerequisite and rerun; the bootstrap is designed
to be repeatable.

Reconfigure required secrets on the new machine separately. They are not in the
migration bundle.

## 4. Verify the copied bundle

After the new rig has ModelRig and VoiceRig installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Verify `
  -InstallRoot C:\Rig `
  -Bundle D:\RigMigration\rig-migration-20260904-193000-a1b2c3d4
```

Verification checks:

1. the complete bundle schema;
2. SHA-256 of both child archives and both sidecars;
3. the ModelRig archive's internal inventory/checksums and migration sidecar;
4. the VoiceRig archive's internal inventory/checksums, `.mrvoice` packages,
   resumable-job inputs and migration sidecar.

`Verify` does not stop either service.

## 5. Import ModelRig + VoiceRig state

On a fresh/bootstrap-created new rig:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Import `
  -InstallRoot C:\Rig `
  -Bundle D:\RigMigration\rig-migration-20260904-193000-a1b2c3d4 `
  -MinimumGpuCount 1
```

The import order is intentional:

1. verify the complete bundle again;
2. restore ModelRig/Kaliv state without running the child operator's intermediate
   full-rig validation;
3. restore VoiceRig profiles/jobs/default voice;
4. run **one final** `bootstrap-new-rig.ps1 -Phase Validate` after both systems
   have been restored.

Each child restore keeps its own fail-closed semantics. If ModelRig succeeds but
VoiceRig fails, the complete operator reports a **PARTIAL** import and must not
be treated as cutover-ready. It does not pretend to roll back already restored
state.

Existing target state is never silently overwritten. On an intentionally
disposable new-rig test state only, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Import `
  -InstallRoot C:\Rig `
  -Bundle D:\RigMigration\rig-migration-20260904-193000-a1b2c3d4 `
  -MinimumGpuCount 1 `
  -ForceRestore
```

Do not use `-ForceRestore` on a machine whose current rig state matters.

## 6. Move the additional GPU and validate again

Only after the new rig has bootstrapped and restored successfully should the
planned RTX 3060 be removed from the old rig and installed in the new one.
Then rerun validation using the **actual final NVIDIA GPU count**. For a final
two-GPU machine:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-new-rig.ps1 `
  -Phase Validate `
  -MinimumGpuCount 2
```

Do not use `2` if the final machine is supposed to contain another number of
NVIDIA GPUs.

## 7. BodyRig and private assets

BodyRig is intentionally outside the portable state bundle. Its V1 bootstrap is
pinned to the repository's explicit installation authority and still requires
operator-provided licensed/private assets:

- SMPL model path;
- SMPL-X source path;
- SiTH diffusion model path inside WSL;
- the pinned WSL/CUDA/Conda prerequisites checked by the bootstrap.

Configure those paths in the local bootstrap config and run the BodyRig phase
only after the base machine and GPU topology are stable:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-new-rig.ps1 `
  -Phase BodyRig
```

If source-rig BodyRig evidence was captured in step 2, verify the newly
provisioned **runtime bytes** against it:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bodyrig-private-input-inventory.ps1 `
  -Action Verify `
  -BodyRigRepo C:\Rig\src\BodyRig `
  -Manifest D:\RigMigration\bodyrig-private-inputs.json
```

The verifier ignores machine-specific path differences. It requires identical
SHA-256 and byte/file counts for the installed SMPL file, installed SMPL-X WSL
tree and live SiTH diffusion model. A mismatch is a blocker; do not paper over
it by editing the evidence JSON.

The inventory is deliberately not a redistribution mechanism. It never copies
licensed/private model payloads and explicitly records
`payload_bytes_included=false`.

## Cutover definition

Do not decommission or repurpose the old rig merely because import returned
success. Cutover requires all of the following on the physical new machine:

- final expected NVIDIA GPU count visible;
- Ollama healthy and configured models available;
- ModelRig validation green;
- VoiceRig readiness/service green;
- migrated VoiceRig profiles visible and intended default voice active;
- a real Kaliv client can connect/authenticate;
- an audible VoiceRig TTS request succeeds;
- when BodyRig is part of this cutover and source evidence exists, BodyRig
  private-input parity is verified;
- BodyRig either passes its physical setup/renderer proof or is explicitly
  accepted as a later blocked workstream.

Until then, keep the old rig intact as rollback/source-of-truth.
