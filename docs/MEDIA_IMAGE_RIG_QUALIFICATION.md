# Images on the rig: engine pins, profile template and qualification

This is #2275 backlog item 4, the image counterpart of `docs/MEDIA_VIDEO_RIG_QUALIFICATION.md`. It covers what the rig needs before the diffusers image path in `media_executor_main` (`docs/MEDIA_EXECUTOR.md`) may serve a job.

**Status (17 Nov 2026):** steps 1 to 6 and step 7's first measurements were run on the rig by Anders, in the development channel (not evidence; see #2275, 6958719351 and the follow-ups). Every statement is tagged with what it rests on:

- **[source]**: a cited upstream page;
- **[repo]**: this repository's code;
- **[checked]**: checked here, offline, against the pinned packages;
- **[estimate]**: reasoning, not a measurement;
- **[measure]**: something the qualification below must establish.

No profile ships enabled, and nothing in this document changes a default.

## 1. The engine: pinned versions

**The pins.** `deploy/media-image-requirements.txt` pins:

| Package | Version |
|---|---|
| `torch` | 2.8.0 (CUDA 12.6 wheel) |
| `diffusers` | 0.35.2 |
| `transformers` | 4.56.2 |
| `accelerate` | 1.10.1 |
| `safetensors` | 0.6.2 |
| `huggingface-hub` | 0.35.3 |

`worker/app/media_image_env.PINNED_VERSIONS` holds the same list, and a test keeps the two equal.

- **The file lives outside `worker/requirements*.txt` on purpose.** The release build installs from those files, and `tests/workflow_media_generation_boundary.py` keeps GPU libraries out of them [repo].
- **They install together.** `pip check` reports no conflict [checked, on Linux with the CPU wheel of torch 2.8.0].
- **The CUDA wheels exist.** `torch-2.8.0+cu126` is published for `cp311-win_amd64` and `cp311-manylinux_2_28_x86_64` [checked: download.pytorch.org/whl/cu126 index].
- **Every allowlisted pipeline does what the adapter relies on in diffusers 0.35.2** [checked by source inspection]. This covers `QwenImagePipeline`, `StableDiffusionXLPipeline` and `FluxPipeline`:
  - `__call__` takes `prompt`, `num_inference_steps`, `width`, `height`, `generator` and `callback_on_step_end`;
  - it resets `self._interrupt = False` and checks `if self.interrupt` between steps;
  - the class has `enable_model_cpu_offload`.

  This replaces the assumption in `docs/MEDIA_EXECUTOR.md` ("to be verified on the pinned diffusers in rig R5") for the code itself. That a cancel actually stops a render on the GPU is still **[measure]**.

## 2. Which model first: SDXL base 1.0

| | SDXL base 1.0 (template) | FLUX.1 [dev]/[schnell] | Qwen-Image |
|---|---|---|---|
| Pipeline (allowlisted) | `StableDiffusionXLPipeline` | `FluxPipeline` | `QwenImagePipeline` |
| Parameters | about 3.5B in total, with a 2.6B UNet [estimate from the published architecture] | 12B transformer [estimate, from memory] | about 27B in total: a 20B MMDiT plus a 7B Qwen2.5-VL text encoder [source: NVIDIA build model card] |
| bf16 weights | about 7 GB [estimate] | about 24 GB [estimate] | about 54 GB [estimate from 27B] |
| Fits a 12 GB RTX 3060 without offload | yes, with margin at 1024² [estimate] | no | no |
| Licence | CreativeML Open RAIL++-M. The model card front matter says `license: openrail++` and has no gating [source: HF README] | dev: non-commercial; schnell: Apache 2.0 [from memory, re-check the model cards] | Apache 2.0 upstream; NVIDIA's hosted copy is under its own Open Model License [source: NVIDIA build model card] |

**Why SDXL first:**
- It is the only allowlisted pipeline that fits one 12 GB card in bf16 without CPU offload.
- The profile's `cpu_offload: true` would let FLUX or Qwen run, but it needs much more host RAM, and it is slower by an amount that must be measured. That is a later candidate, not the first one.

## 3. The profile template

`deploy/media-profiles/sdxl-base-1.0.json.example` is a complete `kaliv-media-profile/v1`:
- `qualification: "candidate"`, `devices: ["cuda:1"]`, `cpu_offload: false`;
- `min_usable_gib: 8`, `reserve_gib: 1.0`;
- the five SDXL sizes around 1 MP;
- at most 40 steps;
- render defaults `guidance_scale: 6.0` and a negative prompt against the usual SDXL base failures (anatomy, text, watermarks). Both are `backend_options` the adapter passes to the pipeline for every job of the profile; leave them out to get the pipeline's own defaults.

**Why 8 / 1.0 and not 10 / 1.5 [measured, rig, 17 Nov 2026]:** on an idle RTX 3060 12 GB under Windows, `torch.cuda.mem_get_info()` reports **10.99 GiB free of 12.00**. The admission rule is `free - reserve_gib >= min_usable_gib`, so 10 / 1.5 needs 11.5 GiB free and can never pass on this card: two jobs were deferred and failed with `gpu_unavailable` after `VRAM_MAX_WAIT_S`. With 8 / 1.0 (needs 9 GiB free) the same jobs rendered. SDXL base in bf16 at 1024² stays well inside that.

**It cannot be enabled by accident:**
- a profile directory loads only `*.json`;
- its `revision` is a placeholder that the profile parser refuses;
- even when pinned, a candidate profile needs `KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES=1` and an entry in `KALIV_MEDIA_PROFILES_ENABLED` [repo; `tests/worker_media_image_env.py`].

**Why `cuda:1`:** it leaves `cuda:0` for video or chat. Change it if the rig is arranged differently.

## 4. Qualification on the rig (Anders runs this; nothing here is automatic)

**Before you start.** Step 3 downloads model weights, about 7 to 14 GB depending on the files [estimate]. That is a network action on the rig: run it only once you have decided to. **Media never leaves the rig.**

1. **Media venv,** separate from the frozen worker and from ComfyUI's environment:

   ```powershell
   py -3.11 -m venv C:\Kaliv\media-venv
   C:\Kaliv\media-venv\Scripts\python -m pip install --index-url https://download.pytorch.org/whl/cu126 torch==2.8.0
   C:\Kaliv\media-venv\Scripts\python -m pip install -r deploy\media-image-requirements.txt
   C:\Kaliv\media-venv\Scripts\python -m pip freeze > "$env:TEMP\media-venv-freeze.txt"
   ```

2. **Environment check.** It is read-only and runs without weights:

   ```powershell
   C:\Kaliv\media-venv\Scripts\python scripts\media_image_env_check.py
   ```

   - **Expected:** `"ok": true`, with both RTX 3060 at capability 8.6 and bf16 supported, every version equal to its pin, and the three pipelines passing.
   - **Exit code:** 1 means at least one check failed, and its `detail` says which.

3. **Weights,** in the diffusers layout that the adapter loads with `local_files_only`:

   ```powershell
   C:\Kaliv\media-venv\Scripts\huggingface-cli download stabilityai/stable-diffusion-xl-base-1.0 --exclude "*.fp16.*" "*.bin" "*.onnx*" "*.msgpack" "sd_xl_*"
   ```

   - The adapter loads the default (fp32) safetensors and casts them to bf16. It has no `variant` option today, so the fp16 files are not used [repo]. Adding `variant: "fp16"` would halve the download, but that is a code change outside this slice.
   - The exact exclude list is an **[estimate]**. Step 5 proves the snapshot is complete.

4. **Pin.** Copy the template to the profile directory as `sdxl-base-1-0.json`, then replace `revision` with the commit that the cache resolved:

   ```powershell
   Get-Content "$env:USERPROFILE\.cache\huggingface\hub\models--stabilityai--stable-diffusion-xl-base-1.0\refs\main"
   ```

5. **Check the profile against the cache:**

   ```powershell
   C:\Kaliv\media-venv\Scripts\python scripts\media_image_env_check.py --profile <profile dir>\sdxl-base-1-0.json
   ```

   `snapshot:sdxl-base-1-0` must be ok: every component named in `model_index.json` is present with its config, and every model component has the default weights that `from_pretrained` loads without a `variant` [repo]:
   - `diffusion_pytorch_model.safetensors` for a diffusers component, `model.safetensors` for a transformers one;
   - or, when sharded, the `.index.json` and every shard it names.

   Variant files such as `*.fp16.safetensors` do not count, and pickle `.bin` weights are not accepted, even though the loader could fall back to them.

6. **Switches.** These are in `docs/MEDIA_EXECUTOR.md` and the R17 layout in `docs/MEDIA_R17_DEPLOYMENT_PROOF.md`:
   - `KALIV_MEDIA_EXECUTOR_PYTHON=C:\Kaliv\media-venv\Scripts\python.exe`
   - `KALIV_MEDIA_EXECUTOR_DEVICES=cuda:1`
   - `KALIV_MEDIA_PROFILE_DIR`
   - `KALIV_MEDIA_PROFILES_ENABLED=sdxl-base-1-0`
   - `KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES=1`
   - then `KALIV_MEDIA_EXECUTOR=1`.

7. **Measure.** All of these are **[measure]**:
   - one job at 1024×1024 with 30 steps, then the same again warm;
   - the wall time from the executor's `kaliv-media-event` lines;
   - the VRAM peak (`nvidia-smi --query-gpu=index,memory.used --format=csv -l 1`);
   - that a cancel during the render ends it and publishes nothing.

   **First measurements [measured, rig, 17 Nov 2026, dev channel]** — cuda:1 (RTX 3060 12 GB), 1024×1024, 30 steps, bf16, no negative prompt (2.0.20 code):

   | | SDXL base 1.0 | RealVisXL V4.0 (same pipeline, candidate profile) |
   |---|---|---|
   | denoising | 19.9 s = 1.51 it/s | 19.8 s = 1.52 it/s |
   | job, cold (load in the same claim) | 30.7 s | 30.1 s |
   | job, warm (model resident) | — | 21.4 s |
   | VRAM resident after load | — | 7 743 MiB |
   | VRAM during denoising | — | 9 715 MiB |
   | **VRAM peak (VAE decode)** | — | **10 967 MiB** |

   The VAE-decode peak leaves ~1.3 GB on a 12 GB card: fine while the GPU is dedicated to images, not enough for 1216×832 or a chat model on the same card [estimate]. `vae.enable_tiling()` is the candidate fix; it is not in the adapter yet and must be measured. Cancel-during-render is still **[measure]**.

8. **Promote.** Only after 7 may the profile become `rig-qualified`.

**Route status.** The submit/status/cancel routes (`POST /api/v1/media/jobs`, `GET …/{id}`, `POST …/{id}/cancel`) and the gallery API are on main and were used from the Android app in the first rig run; the earlier note that steps 7 and 8 were blocked on them is obsolete.

**Development channel.** `START_DEV_APPLIANCE.cmd` starts backend and worker, **not** the executor (no supervisor runs in that channel). Start it by hand, as the same account and the same elevation you administer it from, from `worker\` with the media venv:

```powershell
# env: the media keys from modelrig.env, plus the three the executor needs itself
$env:KALIV_MEDIA_EXECUTOR = "1"; $env:HF_HUB_OFFLINE = "1"; $env:TRANSFORMERS_OFFLINE = "1"
Push-Location <checkout>\worker; & C:\Kaliv\media-venv\Scripts\python.exe -u -m app.media_executor_main --device cuda:1; Pop-Location
```

Exit 73 means another executor already holds that GPU's lock; one started from an elevated window is invisible to a non-elevated one, so stop it from a window of the same elevation. Exit 75 with `media_volume_marker_missing` means the volume marker (`docs/MEDIA_VOLUME.md`) was not written.

**Prompt language [observed, rig]:** SDXL is trained on English. Danish prompts gave visibly worse and stranger results than the same subject in English. Until the worker translates locally (proposal on #2275), write prompts in English.

## 5. What this does not do

- It downloads nothing, enables nothing and changes no default, profile, environment file or supervisor setting.
- Its measured figures are the free VRAM in §3 and the §4.7 table; everything else is tagged [estimate] or [measure].
- It does not touch cloud or egress settings.
