# Experimental video and VR media pipeline

Status: design contract only; **not** a working video generator. This document does not change runtime behavior or V1 release gates.

## Isolation
- Feature branch: `feat/wan-video-generation`; do not merge into `main` until qualified.
- Default: disabled. ComfyUI is an optional local service, never started automatically.
- Do not claim that two 12 GB GPUs form one 24 GB VRAM pool.
- Wan model choice, quantization, offloading, actual VRAM use, throughput and licensing must be validated on the target rig.

## Proposed job API (not yet implemented)

`POST /media/jobs` with an authenticated JSON body:
```json
{
  "kind": "text_to_video",
  "prompt": "A rainy futuristic city",
  "output_profile": "flat_2d",
  "duration_seconds": 3,
  "width": 512,
  "height": 320,
  "fps": 16
}
```

`kind`: `text_to_video` or `image_to_video` (latter requires a previously uploaded, validated input image ID).
`output_profile`: `flat_2d`, `stereo_sbs`, `vr180`, `vr360`.
Initially **only flat_2d may be generated**. Other profiles must return an explicit unsupported-profile error until dedicated processing and QA exist.

Jobs: queued → running → completed / failed / cancelled. Expose status and cancellation through the existing authenticated job subsystem; persist provenance and actual generation parameters. Validate bounds, user permissions, path isolation, maximum queue depth, timeouts, and disk quotas. Never accept arbitrary ComfyUI graphs or file paths from clients. Maintain a server-side allowlisted workflow template. ComfyUI must bind to loopback; keep credentials and raw model service off the public network.

## VR playback contract

The consumer (SkyPlayer-Engine / Kaliv VR) needs a versioned media manifest, not a guessed projection:
```json
{
  "schema": "kaliv-media/v1",
  "media_type": "video",
  "projection": "flat",
  "stereo": "mono",
  "codec": "h264",
  "container": "mp4",
  "width": 512,
  "height": 320,
  "fps": 16,
  "duration_seconds": 3,
  "artifact_id": "<server-issued-id>"
}
```
Future profiles require validated projection/stereo metadata (equirectangular 360, VR180, left-right SBS). A depth estimate or SBS conversion is not equivalent to physically correct stereoscopic capture. No automatic relabeling of ordinary 2D footage as VR180/360.

## Acceptance gates
1. Unit tests for profile rejection, request limits, template isolation, cancellation, and malformed outputs.
2. ComfyUI integration tests for queued/polled/completed/failed/interrupted jobs.
3. Physical GPU memory and time measurements on each RTX 3060; Ollama concurrency behavior.
4. Decode and seek on Quest 2; verify aspect ratio, stereo eye order, projection, comfort and frame pacing.
5. Explicit owner approval before merging; keep the existing release untouched.
