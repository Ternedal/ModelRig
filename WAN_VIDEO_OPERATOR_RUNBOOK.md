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
