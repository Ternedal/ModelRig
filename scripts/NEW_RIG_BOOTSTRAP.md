# New rig bootstrap

`bootstrap-new-rig.ps1` is the repeatable Windows bootstrap for a fresh rig. It
installs the common host tools, checks out ModelRig/VoiceRig/BodyRig, installs
the latest checksum-verified ModelRig appliance release, runs the repository's
VoiceRig installer, prepares WSL for BodyRig, and writes one machine-readable
result report.

The script is intentionally safe to re-run. Existing ModelRig `modelrig.env`
configuration is preserved, release binaries are replaced only after SHA-256
verification, Git checkouts with local changes are never reset, and BodyRig is
pinned to its explicit V1 installation authority instead of a floating branch.

## Recommended migration order

Keep the old rig intact, including the RTX 3060 that will be moved later.

On the new rig, clone ModelRig and open an elevated PowerShell:

```powershell
cd C:\path\to\ModelRig
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-new-rig.ps1 `
  -Phase All `
  -SkipBodyRig
```

This brings up the base machine, ModelRig and VoiceRig without requiring the
second GPU or BodyRig's licensed/model assets.

After the extra RTX 3060 has been moved, validate the GPU count and services:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-new-rig.ps1 `
  -Phase Validate `
  -MinimumGpuCount 2
```

Use the actual expected NVIDIA GPU count if the final machine should contain a
different number.

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
verifies each release executable against `SHA256SUMS.txt`, installs the matching
release startup/validation scripts, starts Ollama, pulls the configured models,
registers ModelRig recovery-first autostart, and runs VoiceRig's own Windows
installer.

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
not the source of truth for machine-local state. This bootstrap therefore does
not copy or invent:

- ModelRig pairing/device tokens, admin keys, scheduler approval secrets or
  other secrets;
- an existing RAG database/corpus or other mutable ModelRig data;
- private VoiceRig user data;
- licensed SMPL/SMPL-X assets;
- a private/local SiTH diffusion model;
- arbitrary Ollama blobs that are not listed in the bootstrap model manifest;
- Stash API tokens or other credentials.

Those are migration/restore inputs, not installation dependencies. Keep the old
rig untouched until the new rig passes validation.

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
