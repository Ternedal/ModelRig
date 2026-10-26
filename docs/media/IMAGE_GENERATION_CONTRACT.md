# Image generation integration contract (draft)

Status: proposed; no runtime activation.

## Architecture
- Worker owns model execution and job lifecycle. Backend authenticates requests and proxies media access.
- Clients (Android, desktop, Quest) use the same authenticated job and media contract.
- Image generation is independent of Ollama text generation. Select the concrete Qwen Image runtime only after GPU feasibility tests.

## Proposed API (not implemented)
- POST /api/v1/media/images/jobs -> 202 {job_id,status:"queued"}
- GET /api/v1/media/images/jobs/{job_id} -> status/progress/error/result
- POST /api/v1/media/images/jobs/{job_id}/cancel
- GET /api/v1/media/assets/{asset_id} -> authenticated image stream

## Request constraints
- prompt required, bounded length; width/height/steps bounded by backend policy.
- idempotency key for retries; no raw filesystem paths in requests or responses.
- statuses: queued, running, completed, failed, cancelled.
- never claim completed before output file has been flushed and atomically published.

## Storage and safety
- Explicit configured absolute MEDIA_ROOT on external disk; refuse generation when absent, inaccessible, or located on system volume.
- Atomic temp-file-to-final rename within same volume; SHA-256 and byte size recorded.
- Asset IDs are opaque; no traversal, symlink escapes, or direct client file access.
- Quotas: max concurrent jobs, max queued jobs, per-job timeout, free-space floor.
- Delete partial outputs on cancellation/failure. Keep metadata durable across restarts.
- Token-scoped access to jobs and assets. Log IDs, timings, and errors, never raw prompts by default.

## GPU policy
- Default single generation job; serialize with other heavy GPU work.
- Benchmark on both 12 GB GPUs before selecting quantization/offload.
- A combined 24 GB VRAM is not a single 24 GB allocation; multi-GPU requires explicit support.

## Acceptance tests
1. No external media disk -> clear rejection, zero writes to system disk.
2. Queue -> running -> completed, verified SHA-256 and downloadable image.
3. Cancel queued/running, restart recovery, timeout, and disk-full handling.
4. Unauthorized and cross-device asset reads denied.
5. Android, desktop, Quest can display the same authenticated asset.
6. Chat/ASR/TTS smoke tests remain green under configured GPU scheduling.

## Release gate
No main merge or release until implementation, CI, real-rig GPU tests, and client integration pass.
