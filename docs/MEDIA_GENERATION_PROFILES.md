# Media generation: model profiles and GPU lease

ModelRig #2296. This is the generator side of Kaliv media:
- model profiles;
- the exclusive GPU lease and VRAM admission;
- the job store;
- the profile-driven runner;
- one diffusers image adapter.

The gallery server, media store, asset retrieval and routes are a separate slice (#2313). The two sides meet only at `ArtifactSink` in `worker/app/media_generation_contract.py`.

**Status: default-off, not rig-qualified.**
- Nothing in this layer runs on worker start.
- No model or profile ships with ModelRig.
- Model names below are candidates, not supported or qualified functionality.

## What runs, and when

A generator runs only if **all** of these hold:

1. An operator wrote a profile file (JSON, below) into a profile directory.
2. `KALIV_MEDIA_PROFILES_ENABLED` lists that profile id (comma-separated).
3. The profile is `rig-qualified`, **or** `KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES=1` is set as well.
4. Loading is offline: `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. The weights must already be on disk, and `from_pretrained` runs with `local_files_only=True` at the pinned revision.
5. The device's physical GPU is known. `KALIV_GPU_DEVICE_UUIDS` maps `cuda:N` to a GPU UUID (`nvidia-smi -L`), and `CUDA_DEVICE_ORDER=PCI_BUS_ID` is set.
6. The GPU lease for that UUID is free.
7. With the lease held, torch's `cuda:N` reports that UUID, and the device has `min_usable_gib` free above `reserve_gib`.

The lease is held for as long as the model is loaded: budget, load, inference and the resident lifetime, until `close()`. Another generator **that takes this lease**, such as a second image executor or (next slice) the Wan/ComfyUI adapter, gets `GpuBusy` for that GPU instead of loading on top of it.

**Scope (decision 6491161681).** The lease coordinates only processes that take it. Ollama, a WSL2 instance and any worker that does not use `gpu_lease` are **not** covered. Whole-rig GPU exclusivity is **unproven** and not claimed until a common arbiter, or explicit coordination, and physical tests exist.

## GPU lease

- `KALIV_GPU_LEASE_DIR` is an existing absolute, non-symlink, **local** directory, not on removable media, so the lease works while the media volume is missing.
  - On POSIX it must be owned by the running user and not group- or world-writable.
  - On Windows its ACLs are not checked by this code; that is a stated limit.
- Lock files are named after the GPU UUID (`GPU-….lock`), not after a CUDA index, which can change with `CUDA_VISIBLE_DEVICES` or ordering.
- The lease is an OS file lock on that file:
  - `fcntl.flock` on Linux and `msvcrt.locking` on Windows;
  - the OS releases it when the holding process exits or is killed, so there is never a stale lease.
- **Verified:** on Linux, with real processes, including SIGKILL of the holder (`tests/worker_gpu_lease.py`).
- **Not verified:**
  - the Windows `msvcrt` path is untested until it runs on the rig;
  - torch's UUID string format against `nvidia-smi` is untested on the rig. Torch reports it without the `GPU-` prefix; the code normalises both.

## Profile file

Schema `kaliv-media-profile/v1`. Unknown keys, backends, pipelines, tasks or MIME types are refused, and one invalid file fails the whole directory.

~~~json
{
  "schema": "kaliv-media-profile/v1",
  "profile_id": "sdxl-base",
  "modality": "image",
  "tasks": ["text_to_image"],
  "backend": "diffusers",
  "pipeline": "StableDiffusionXLPipeline",
  "model_id": "<repository id or local name>",
  "revision": "<pin the exact 40-hex commit you downloaded>",
  "limits": {"max_prompt_chars": 1000, "sizes": [[1024, 1024]], "max_steps": 40, "max_frames": null},
  "outputs": ["image/png"],
  "resources": {"min_usable_gib": 8, "reserve_gib": 2, "devices": ["cuda:1"], "cpu_offload": false},
  "qualification": "candidate",
  "license": "<the model's licence id>"
}
~~~

The placeholders above are rejected on purpose: a revision must be 40 lower-case hex characters.

- **Backends:**
  - `diffusers` serves image profiles;
  - `comfyui` serves video profiles (Wan), and its adapter is the next slice.
- **Diffusers pipelines (allowlist):** `QwenImagePipeline`, `StableDiffusionXLPipeline`, `FluxPipeline`. The adapter never loads any other class.
- **Licence:** recorded per profile. Some candidate models carry non-commercial licences; that is the operator's responsibility to respect.

## Not in this slice

The executor process that drives these adapters is described in `docs/MEDIA_EXECUTOR.md` (G2, default-off).


- the executor process and its wiring to the media store (once `ArtifactSink` has an implementation on the gallery side);
- image-to-image (it needs input bytes from the media store);
- the Wan/ComfyUI video adapter (submit/poll), which uses the same lease;
- any route.
