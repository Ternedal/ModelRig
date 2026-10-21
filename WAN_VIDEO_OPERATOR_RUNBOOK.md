# Experimental Wan video: operator runbook

**Status:** isolated feature-branch prototype; not qualified on the rig. Do not
enable in production, merge into a release, or describe video generation as
working until the checks below pass.

## Hardware and storage admission

- The rig has two 12 GB GPUs. Their memory is **not** one shared 24 GB
  allocation. Select a Wan model/quantization and ComfyUI workflow that fits
  one device (or explicitly supports tested multi-GPU offload). Never assume
  a full-size Wan checkpoint will fit.
- Set `KALIV_MEDIA_ROOT` to a mounted external volume, not the Windows
  system drive. The worker requires free-space reserve
  `KALIV_MEDIA_MIN_FREE_GB` (default 20 GiB).
- Put all ComfyUI inputs, outputs, temporary files, user data and downloaded
  model weights on that external volume. Verify ComfyUI's effective model
  search paths separately: the launch-plan builder **does not** redirect
  checkpoints or automatically download models.
- Keep ComfyUI on `127.0.0.1:8188`; do not expose its API to the LAN.

## Provision a trusted ComfyUI API-format graph

1. Install a compatible Wan text-to-video pipeline in a separate ComfyUI
   environment. Confirm the installed node types, model paths, VRAM needs,
   and MP4 output node using ComfyUI's own API export.
2. Export the **API-format** workflow JSON, not the editor/UI JSON.
   Place it on the external media volume.
3. Replace exactly one direct input value for each of these five slots:

   | Slot literal | Required input key | Source |
   |---|---|---|
   | `__KALIV_VIDEO_PROMPT__` | `text` | validated prompt |
   | `__KALIV_VIDEO_WIDTH__` | `width` | validated width |
   | `__KALIV_VIDEO_HEIGHT__` | `height` | validated height |
   | `__KALIV_VIDEO_FPS__` | `fps` | validated FPS |
   | `__KALIV_VIDEO_FRAMES__` | `length` | FPS × duration + 1 |

   The slot names describe the **adapter contract**, not universally
   supported Wan node inputs. If the installed Wan workflow uses a different
   field (for example `num_frames` instead of `length`), adapt and test
   the operator-owned graph or the adapter before dispatch. Do not invent
   an unverified node graph.
4. Set `KALIV_COMFY_WORKFLOW_TEMPLATE` to the absolute path of that JSON
   file. The dispatcher rejects templates outside the media volume.

## Read-only admission before any generation

Run this from the repository root with the worker Python environment active,
**before** enqueueing a job. It does not launch ComfyUI, download models,
create directories, or allocate GPU memory:

```powershell
$env:PYTHONPATH = (Resolve-Path .\worker).Path
python -m app.video_preflight --json
if ($LASTEXITCODE -ne 0) { throw 'Wan preflight diagnostics failed; do not enqueue.' }
```

A zero exit code means only that configured storage, workflow structure,
ComfyUI node compatibility and GPU inventory passed their *read-only*
checks. The JSON `ready` field remains `false` until the operator separately
verifies physical external-drive identity, effective ComfyUI model/cache
paths, GPU memory fit and actual MP4 generation/playback. Never interpret
this diagnostic result as release acceptance. If ComfyUI is not already
running locally, node compatibility reports unavailable and the preflight
fails safely.

## One-shot operator sequence

From the repository root with the worker Python environment activated:

```powershell
$env:PYTHONPATH = (Resolve-Path .\worker).Path
python -m app.video_comfy_enqueue_once --prompt 'Clouds over the sea' --width 512 --height 320 --fps 16 --seconds 3
python -m app.video_comfy_dispatch_once
python -m app.video_comfy_collect_once
```

The dispatcher takes at most one queued job; the collector takes at most
one finished job. They are **not** a scheduler. The operator must configure
`COMFYUI_OUTPUT_DIRECTORY` on the external volume and ensure the ComfyUI
output node writes exactly one MP4 with a successful history record.
The first command explicitly creates a validated job in the external SQLite queue; the second submits it. No HTTP request can enqueue arbitrary workflow JSON.

## Physical storage and MP4 evidence (operator-only)

Before starting a generation, verify that the configured root really belongs to
an external disk. The code can reject a system-drive path or a junction pointing
back to it, but **cannot attest USB/SATA device identity**. On Windows, inspect
both the volume and its backing disk (run in PowerShell):

```powershell
$root = $env:KALIV_MEDIA_ROOT
if (-not $root -or -not (Test-Path -LiteralPath $root -PathType Container)) {
    throw 'KALIV_MEDIA_ROOT must name an existing external directory.'
}
$resolved = (Resolve-Path -LiteralPath $root).ProviderPath
$volume = Get-Volume -FilePath $resolved
$partition = Get-Partition -DriveLetter $volume.DriveLetter
$disk = $partition | Get-Disk
$disk | Format-List Number,FriendlyName,BusType,SerialNumber,IsBoot,IsSystem
if ($disk.IsBoot -or $disk.IsSystem) { throw 'Media root is on the OS disk.' }
Write-Host "Operator must confirm physical external disk identity: $resolved"
```

This is a diagnostic, not automatic approval: volume mount arrangements and
virtual disks may require manual inspection. Do not start a job if the disk
identity is ambiguous.

After generating an MP4, use `ffprobe` (if installed) to validate the actual
video stream rather than relying on the collector's MP4 header check:

```powershell
$mp4 = Read-Host 'Absolute path of generated MP4 on the external volume'
if (-not (Test-Path -LiteralPath $mp4 -PathType Leaf)) { throw 'MP4 missing' }
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    throw 'Install ffprobe before codec/playback qualification'
}
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,nb_frames -show_entries format=duration -of json -- $mp4
if ($LASTEXITCODE -ne 0) { throw 'MP4 probing failed' }
```

Inspect the JSON for the expected codec, dimensions, duration and frame count;
missing `nb_frames` is possible with some containers and must be checked via
decoding or frame counting instead. Then independently play the file on each
supported client. A successful `ffprobe` alone is not playback acceptance.

## Qualification gates

- Run the Python video unit tests and the repository's complete CI suite.
- Check that the actual ComfyUI graph accepts the five bound values, produces
  the expected number of frames, and writes one decodable H.264 MP4.
  The collector's `ftyp` check only checks a container signature; it does
  **not** prove codec, duration or decodability.
- Verify restart/retry behavior, failure handling, disk-full behavior and
  no internal-disk growth.
- Test gallery authentication and playback independently on Windows,
  Android and Quest. Gallery listing alone is not playback qualification.
- Keep VR/stereo generation disabled until a separately qualified pipeline
  can produce and validate the required projection and stereo metadata.

No real GPU generation, Android playback, Quest playback, or rig acceptance
has been verified by this runbook.
