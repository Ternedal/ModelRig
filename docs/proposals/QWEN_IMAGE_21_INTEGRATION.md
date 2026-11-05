# Qwen-Image 2.1 integration — implementation plan

Status: proposal, isolated from V1 release. No runtime changes or activation.

## Goal
Enable local text-to-image and image editing from Kaliv through ModelRig, keeping Ollama for language models. Qwen-Image 2.1 has native ComfyUI support. Do not assume Ollama supports this image architecture.

## Hardware constraints
Target: Windows 11 + WSL2, two RTX 3060 GPUs with **12 GB VRAM each**. Do not treat these as one 24 GB CUDA device. Begin with a quantized/low-VRAM ComfyUI workflow and CPU offloading. Benchmark memory, latency and image quality before choosing model format, resolution or offloading strategy.

## Architecture
Kaliv client -> authenticated ModelRig image-job API -> gated ComfyUI adapter -> loopback-only ComfyUI -> local image artifact store -> authenticated result retrieval.

## API proposal
- POST /api/images/jobs: prompt, mode (generate/edit), reference artifact IDs, dimensions, seed. Return job ID.
- GET /api/images/jobs/{id}: queued/running/succeeded/failed, progress and error.
- GET /api/images/jobs/{id}/result: authorized artifact download.
- POST /api/images/jobs/{id}/cancel: cancellation.

API names and shapes are proposals, not implemented routes.

## Security requirements
- Default-off feature flag; do not modify V1 release flags or main.
- Bind ComfyUI to loopback, never expose it directly to LAN/mobile.
- Authenticate and authorize requests at ModelRig boundary; enforce user ownership of inputs/results.
- Limit prompt length, dimensions, reference count, concurrency, GPU memory budget and request duration.
- Validate uploaded image types by decoded content, cap bytes and pixels, strip sensitive metadata as appropriate.
- Do not allow arbitrary workflow JSON, custom node installation, external URLs, or filesystem paths from client input.
- Use a fixed, version-pinned, audited ComfyUI workflow and dependencies.
- Protect output storage against path traversal and enforce retention/deletion.
- Handle worker restart, job cancellation, timeouts, GPU OOM and cleanup.
- Keep generated content explicitly labeled; verify model license before any commercial distribution.

## Implementation stages
1. Audit existing ModelRig API/auth/artifact conventions and release boundaries.
2. Build isolated ComfyUI adapter with dependency-injected HTTP transport and fixture-based tests.
3. Add asynchronous job manager, persistence, limits, cancellation and lifecycle tests.
4. Integrate API through existing authentication and approval policy.
5. Add opt-in Kaliv UI for prompt, references, job status and gallery.
6. Run physical 12 GB VRAM tests on one GPU first, then evaluate two-GPU scheduling as independent workers.
7. Complete security review, license review and release qualification before activation.

## Acceptance criteria
- Existing V1 release and main untouched.
- Default-off mode has no ComfyUI dependency at startup.
- No unauthenticated job creation or artifact retrieval.
- Invalid inputs and resource limits rejected predictably.
- Tests cover success, error, timeout, cancellation and cleanup.
- Physical performance and VRAM use measured, not assumed.

References:
- https://github.com/QwenLM/Qwen-Image-2.1
- https://comfy.org/qwen-image-2.1/
