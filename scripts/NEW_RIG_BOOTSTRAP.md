# New rig bootstrap

`bootstrap-new-rig.ps1` is the repeatable Windows bootstrap for a fresh rig. It
installs the common host tools, checks out ModelRig/VoiceRig/BodyRig, installs
the latest checksum- and provenance-verified ModelRig appliance release, runs
the repository's VoiceRig installer, prepares WSL for BodyRig, and writes one
machine-readable result report.

The script is intentionally safe to re-run. Existing ModelRig `modelrig.env`
configuration is preserved, active appliance binaries are updated through the
transactional updater, Git checkouts with local changes are never reset, and
BodyRig is pinned to its explicit V1 installation authority instead of a
floating branch.

## Recommended migration order

Keep the old rig intact, including the RTX 3060 that will be moved later.

### 1. Bootstrap the new machine

On the new rig, clone ModelRig and open an elevated PowerShell:

```powershell
cd C:\path\to\ModelRig
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-new-rig.ps1 `
  -Phase All `
  -SkipBodyRig
```

This brings up the base machine, ModelRig and VoiceRig without requiring the
additional GPU or BodyRig's licensed/model assets. A reboot/WSL initialization
can legitimately block the first run; resolve the reported prerequisite and
rerun the same command.

### 2. Export one complete state bundle from the old rig

The preferred migration operator now combines the independently verified
ModelRig/Kaliv and VoiceRig state migrations:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Export `
  -OutDir D:\RigMigration
```

On an old rig where VoiceRig is not at `C:\Rig\src\VoiceRig` or in a sibling
checkout, pass its repository explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Export `
  -VoiceRigRepo C:\path\to\VoiceRig `
  -OutDir D:\RigMigration
```

The complete operator creates one unique bundle directory containing:

- ModelRig/Kaliv archive + SHA-bound sidecar;
- VoiceRig archive + SHA-bound sidecar;
- `rig-migration.json`, which binds all four files by SHA-256.

ModelRig is held stopped after its DB snapshot while VoiceRig snapshots the
shared local voice/default files, removing the cross-system voice race. The old
ModelRig runtime is then restarted through recovery-first `KalivBootstrap` if it
was running before export.

If Agent 3 protected memory is active (`KALIV_AGENT3_MEMORY_STORE=protected`) and
a protected memory database exists, ModelRig export deliberately stops with a
blocker. Windows DPAPI current-user storage does not yet have a proven
cross-machine restore contract in ModelRig; use the dedicated T-033 physical
path when that proof exists rather than silently copying machine-bound
ciphertext.

Copy the **entire bundle directory** to the new machine. A directory without a
successfully written/verified `rig-migration.json` is diagnostic evidence only
and is not a cutover authority.

### 3. Configure non-portable inputs

The bundle never contains secret values. Configure required ModelRig/VoiceRig
credentials on the new machine separately before cutover.

BodyRig licensed/private assets are also deliberately not bundled. Keep their
paths in the local bootstrap config and run BodyRig only after the base machine
and final GPU topology are stable.

### 4. Verify the copied bundle

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Verify `
  -InstallRoot C:\Rig `
  -Bundle D:\RigMigration\rig-migration-YYYYMMDD-HHMMSS-xxxxxxxx
```

Verification checks the complete bundle hashes and then delegates to both child
operators for their full internal archive/sidecar verification. It does not stop
services.

### 5. Import both state domains

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\migrate-complete-rig.ps1 `
  -Action Import `
  -InstallRoot C:\Rig `
  -Bundle D:\RigMigration\rig-migration-YYYYMMDD-HHMMSS-xxxxxxxx `
  -MinimumGpuCount 1
```

The order is intentional: ModelRig/Kaliv state restores first, VoiceRig
profiles/jobs/default voice restore second, and one final
`bootstrap-new-rig.ps1 -Phase Validate` runs only after both have succeeded.
Existing target state is not overwritten unless `-ForceRestore` is explicit.
If one child import succeeds and the next fails, the complete operator reports a
**PARTIAL** import and does not claim cutover readiness.

See `scripts/COMPLETE_RIG_MIGRATION.md` for the full operator contract and
failure semantics. The lower-level `migrate-new-rig-state.ps1` and VoiceRig's
`migrate-state-windows.ps1` remain available for isolated diagnosis.

### 6. Move the additional GPU and validate again

After the state restore is green, move the planned RTX 3060 from the old rig to
the new machine. Validate the final GPU count and services again:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-new-rig.ps1 `
  -Phase Validate `
  -MinimumGpuCount 2
```

Use the actual expected NVIDIA GPU count if the final machine should contain a
different number.

Do not decommission the old rig until a real Kaliv client connection and an
audible VoiceRig TTS request have also passed on the physical new machine.

## Configuration

For repeatable machine-specific values, copy:

```powershell
Copy-Item .\scripts\bootstrap-new-rig.config.example.psd1 `
          .\scripts\bootstrap-new-rig.config.psd1
notepad .\scripts\bootstrap-new-rig.config.psd1
```

The local config file should not contain secrets. The important knobs are:

- `InstallRoot` (default `C:\Rig`);
- the Ollama model manifest;
- expected GPU count;
- BodyRig's SMPL, SMPL-X and SiTH diffusion-model locations.

The example keeps BodyRig pinned to:

```text
76c64a9546238663dedf750a1da4a230cc1e7fa4
```

Do not replace that with the current BodyRig `main` branch merely to make the
bootstrap look simpler. The BodyRig repository explicitly treats that exact
commit as the V1 rig-installation authority.

## Phases

`-Phase Base`
installs host prerequisites through winget, checks NVIDIA visibility, installs
the Ubuntu 22.04 WSL distribution when possible, and installs common WSL build
tools.

`-Phase Core`
updates the three source checkouts, installs the latest ModelRig release,
verifies `SHA256SUMS.txt` and every executable against release-bound SLSA
provenance, installs the matching startup/validation scripts, starts Ollama,
pulls the configured models, registers ModelRig recovery-first autostart, and
runs VoiceRig's own Windows installer.

`-Phase BodyRig`
runs BodyRig only when its prerequisites can be proven. It requires an NVIDIA
GPU/driver, initialized `Ubuntu-22.04`, CUDA 11.7 `nvcc` at
`/usr/local/cuda-11.7/bin/nvcc`, Conda, and the three model/asset paths from the
config. When ready it invokes BodyRig's own `setup-rig-windows.ps1` with
OpenPose provisioning, public checkpoint download and persistent environment
evidence.

`-Phase Validate`
reports NVIDIA GPUs and VRAM, Ollama health, ModelRig's repository validation,
VoiceRig readiness and BodyRig setup evidence.

`-Phase All`
runs all phases in order. A BodyRig prerequisite can remain `BLOCKED` while the
already completed base/Core work remains valid.

## Installed layout

Default layout:

```text
C:\Rig\
  bootstrap\
    bootstrap-*.log
    bootstrap-new-rig-latest.json
  src\
    ModelRig\
    VoiceRig\
    BodyRig\              # detached at the pinned BodyRig SHA
  ModelRig\
    modelrig.env
    modelrig-server-windows-x64.exe
    modelrig-supervisor-windows-x64.exe
    modelrig-updater-windows-x64.exe
    worker\
      modelrig-worker-windows-x64.exe
    scripts\
      kaliv-bootstrap.ps1
      kaliv-autostart.ps1
    deploy\
      validate-rig.ps1
```

VoiceRig keeps using its own repository-defined `%LOCALAPPDATA%\VoiceRig`
runtime/evidence layout.

## What the bootstrap deliberately does not migrate

GitHub is sufficient to reconstruct code and declared dependencies, but it is
not the source of truth for machine-local state. The bootstrap itself therefore
does not copy or invent:

- ModelRig/Kaliv mutable state;
- VoiceRig profiles/jobs/private resumable-job inputs;
- ModelRig/VoiceRig admin keys, tokens, approval secrets or other credentials;
- licensed SMPL/SMPL-X assets;
- a private/local SiTH diffusion model;
- arbitrary Ollama blobs that are not listed in the bootstrap model manifest;
- Stash API tokens or other credentials.

Portable ModelRig/Kaliv + VoiceRig state is handled by
`scripts/migrate-complete-rig.ps1`. The complete bundle composes the two
repository-owned archive formats rather than teaching the bootstrap to copy live
data. It never exports secret values. Protected Agent 3 memory remains blocked
from generic cross-machine export until its Windows DPAPI restore is physically
proven.

Keep the old rig untouched until the new rig has passed post-restore validation,
a real client connection and an audible VoiceRig TTS proof.

## BodyRig and Unity

The pinned BodyRig reference renderer declares Unity `6000.3.13f1`. The Base
phase installs Unity Hub when winget can provide it, but it does not silently
install or license a Unity editor. Install that exact editor through Unity Hub
if the reference-renderer development workflow is needed.

BodyRig also deliberately does not install CUDA 11.7 for WSL automatically.
The bootstrap verifies the exact `nvcc` path expected by BodyRig and reports a
clear blocker when it is absent. This avoids silently changing the pinned
high-fidelity build stack.

## Useful switches

```powershell
# Do not download large Ollama models yet
.\scripts\bootstrap-new-rig.ps1 -Phase All -SkipModelPulls

# Run VoiceRig setup without model warmup
.\scripts\bootstrap-new-rig.ps1 -Phase Core -SkipVoiceRigWarmup

# Install source/runtime but do not register ModelRig scheduled tasks
.\scripts\bootstrap-new-rig.ps1 -Phase Core -SkipAutostart

# Validate after adding the second NVIDIA GPU
.\scripts\bootstrap-new-rig.ps1 -Phase Validate -MinimumGpuCount 2
```

Exit codes:

- `0`: no failures and no blockers;
- `1`: at least one failure;
- `2`: no failure, but at least one prerequisite is blocked.

The latest structured report is always written to
`C:\Rig\bootstrap\bootstrap-new-rig-latest.json` unless `InstallRoot` is changed.
