# Text-to-video on the rig: model manifest, memory profile and qualification

This is #2275 Task C (6753013948). It describes what the rig needs for the gated text-to-video path in `media_executor_main` (`docs/MEDIA_EXECUTOR.md`, "Video").

**Nothing here has been run on the rig.** Every statement is tagged with what it rests on:

- **[source]** a cited upstream page;
- **[repo]** this repository's code;
- **[estimate]** reasoning, not a measurement;
- **[measure]** something the qualification below must establish.

`KALIV_MEDIA_VIDEO` stays unset until Anders enables it after this qualification.

## 1. Recommendation: Wan 2.1 T2V 1.3B first

| | Wan 2.1 T2V **1.3B** (recommended first) | Wan 2.2 TI2V **5B** (second candidate) |
|---|---|---|
| License | Apache 2.0 [source: Wan-AI/Wan2.1-T2V-1.3B model card] | Apache 2.0, commercial use allowed [source: docs.comfy.org Wan2.2 tutorial] |
| VRAM | "requires only 8.19 GB VRAM" [source: model card] | "should fit well on 8GB vram with the ComfyUI native offloading" [source: docs.comfy.org] |
| Speed reference | "5-second 480P video on an RTX 4090 in about 4 minutes (without optimization techniques like quantization)" [source: model card] | not stated |
| Resolution | 480P supported; 720P possible but "generally less stable" [source: model card] | higher resolution, heavier per frame [estimate] |
| Fit for 2× RTX 3060 12 GB | Fits per GPU with margin [estimate from the 8.19 GB figure] | Fits only with offloading, which costs host RAM and time [estimate] |

**Why 1.3B first:**
- It is the smallest licensed model that has an official VRAM figure under 12 GB.
- The repo's profile limits and tests already use its shape: 832×480, up to 81 frames, 16 fps, up to 30 steps [repo: `tests/worker_media_generation_profiles.py`].
- 5B is the next step once 1.3B is qualified. Wan 2.1/2.2 **14B** does not fit a 12 GB card without heavy offloading and is out of scope [estimate; the files are 14.3–32.8 GB, source: Comfy-Org repackaged listing].

## 2. Weight manifest (Wan 2.1 T2V 1.3B through ComfyUI)

Source for every file: Hugging Face `Comfy-Org/Wan_2.1_ComfyUI_repackaged`, `split_files/…` [source: docs.comfy.org "Wan Video" tutorial and the repository's file listing].

| ComfyUI folder | File | Displayed size | SHA-256 |
|---|---|---|---|
| `models/diffusion_models/` | `wan2.1_t2v_1.3B_fp16.safetensors` | 2.84 GB | `be531024cd9018cb5b48c40cfbb6a6191645b1c792eb8bf4f8c1c6e10f924dc5` (as shown on the file's HF page; **confirm on the rig**) |
| `models/text_encoders/` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6.74 GB | **pin on the rig** |
| `models/vae/` | `wan_2.1_vae.safetensors` | not captured | **pin on the rig** |

- **The pin is the rig's own hash.** The profile's `weights` pins are `{path, sha256, bytes}`, relative to `models/` [repo: `docs/MEDIA_VIDEO_GENERATION.md`, G3]. They come from `Get-FileHash` on the downloaded files (§5, step 3), never from this table. The table's hash is only a cross-check.
- **Text encoder: use fp8, not fp16.** `umt5_xxl_fp16.safetensors` is 11.4 GB [source: listing] and leaves no room on a 12 GB card [estimate].
- **Lookup must be unambiguous.** Only these three model files may exist under `models/` with these names. There must be no `extra_model_paths.yaml` and no links anywhere in the models tree. Otherwise the start is refused [repo: `comfy_weights.check_lookup_is_unambiguous`].
- **Licence record.** The profile's `license` field is `apache-2.0`.

## 3. Memory profile: 2× RTX 3060 12 GB

- **One executor per GPU.** `KALIV_MEDIA_EXECUTOR_DEVICES=cuda:0,cuda:1`. Each executor has its own ComfyUI: its own port (`8188`, `8189`) and its own folders. The supervisor gives every executor the same environment, so one `KALIV_COMFY_DIR` is set and each executor uses `KALIV_COMFY_DIR\cuda<N>\` in it, chosen by `--device`. Every executor checks all enabled ComfyUI video profiles, on every GPU, before it opens the queue. A profile that lists more than one GPU, or two profiles on one port, is refused with 78 [repo].
- **There is no model parallelism.** A job runs on one card [repo: one ComfyUI per GPU lease].
- **VRAM per job** [estimate, to be replaced by §5, step 7]:

| Part | Estimate | Note |
|---|---|---|
| Diffusion model (fp16) | ~2.8 GiB | file size |
| Text encoder (fp8) | ~6.3 GiB while encoding | ComfyUI's memory management can unload it after encoding [measure: is it unloaded on the pinned version?] |
| VAE + latents + activations at 832×480×33 | 1–2 GiB | grows with frames |
| Peak | 9–11 GiB if the text encoder stays loaded; ~5 GiB if it is unloaded | 12 GB card: tight in the first case |

- **Profile resources to start with:**
  - `min_usable_gib: 10` and `reserve_gib: 1.5`;
  - `devices: ["cuda:0"]` (one profile file per GPU, each with its own port);
  - VRAM admission refuses or defers below that [repo: G4, `VRAM_MAX_WAIT_S` 10 min].
- **Host RAM.** The text encoder is offloaded to system RAM, and the supervisor's Job Object caps ComfyUI at `host_memory_gib` (default 48) [repo]. Check that the rig has 16 GB or more free for one ComfyUI, and 32 GB or more for two [estimate; measure].
- **Chat on the same rig.** Ollama does not take the GPU lease [repo: `docs/MEDIA_VIDEO_GENERATION.md`]. While a chat model is loaded on a card, VRAM admission defers video on it. Pinning chat to one card and video to the other is the simplest arrangement [estimate].

## 4. Minimum viable settings

| Setting | Minimum viable (first qualification) | Full |
|---|---|---|
| Size | 832×480 | 832×480 (720P is "less stable" on 1.3B [source]) |
| Frames | 33 (about 2 s at 16 fps; Wan uses 4k+1 frame counts [estimate from the 81-frame default]) | 81 (about 5 s) |
| Steps | 20 | 30 (profile `max_steps`) |
| fps | 16 | 16 |
| `max_render_seconds` | 1800 | 1800; tighten once measured |
| `max_output_bytes` | 512 MiB (sink maximum) [repo] | same |

**Render time** [estimate]:
- The source states about 4 min for 5 s at 480P on an RTX 4090. An RTX 3060 has a fraction of that card's tensor throughput, so 5 s at 480P is expected to take on the order of 12–20 min.
- The minimum setting has 33/81 of the frames and 20/30 of the steps. That puts it on the order of 3–6 min, with a large uncertainty.
- §5, step 7 replaces these numbers.

## 5. Qualification on the rig (Anders runs this; nothing here is automatic)

These steps change the rig and download about 10 GB of Apache-2.0 weights. Run them only once Anders has decided to.

1. **ComfyUI at a pinned commit.**
   - Install it in its own folder and its own venv, outside the work area and outside the media volume.
   - Record the commit, and the version that `/system_stats` reports; that version is the profile's `comfyui_version` [repo: G3].

   ```powershell
   git clone https://github.com/comfyanonymous/ComfyUI C:\Kaliv\ComfyUI
   git -C C:\Kaliv\ComfyUI rev-parse HEAD
   ```

2. **Weights.**
   - Download the three files from §2 into `C:\Kaliv\ComfyUI\models\{diffusion_models,text_encoders,vae}`.
   - Use real copies, not links. Nothing else of these names may be anywhere under `models\`.
3. **Pins.**

   ```powershell
   Get-ChildItem C:\Kaliv\ComfyUI\models -Recurse -File | Get-FileHash -Algorithm SHA256 | Select-Object Hash, Path
   (Get-Item C:\Kaliv\ComfyUI\models\diffusion_models\wan2.1_t2v_1.3B_fp16.safetensors).Length
   ```

   Put `{path, sha256, bytes}` for each of the three files into the profile.
4. **Template.**
   - In the pinned ComfyUI, build or load the Wan 2.1 text-to-video workflow from core nodes only: diffusion model loader, CLIP loader, VAE loader, the two text encodes, an empty video latent, the sampler, VAE decode, and a core video save to MP4. Run with `--disable-all-custom-nodes` [repo: rig item 3].
   - Export it as API format.
   - Replace exactly seven values with `__KALIV_VIDEO_PROMPT__`, `…_WIDTH__`, `…_HEIGHT__`, `…_FPS__`, `…_FRAMES__`, `…_STEPS__` and `…_SEED__`, under the allowed input names [repo: `comfy_workflow_template.SLOTS`].
   - Keep `filename_prefix` ASCII [repo: `docs/MEDIA_WORK_AREA.md`].
   - Then `Get-FileHash` the template, which gives the profile's `template_sha256`.
5. **Work area.**
   - Create `"$Work\comfy\cuda0\{input,output,temp,user}"` and the same for `cuda1`, private to the executor account [repo: `docs/MEDIA_WORK_AREA.md`]. `KALIV_COMFY_DIR` is `$Work\comfy`.
   - Run `scripts/media_work_area_preflight.py`.
6. **Profile and switches.**
   - Write one candidate profile per GPU (`wan21-t2v-1p3b-gpu0` on port 8188 and `…-gpu1` on port 8189). They are identical apart from `devices`, `port` and `profile_id`.
   - Set `KALIV_COMFY_PYTHON`, `KALIV_COMFY_MAIN`, `KALIV_COMFY_DIR`, `KALIV_COMFY_TEMPLATE_DIR`, `KALIV_MEDIA_PROFILES_ENABLED`, `KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES=1`, and **then** `KALIV_MEDIA_VIDEO=1`.
7. **Measure.**
   - Run three jobs at the minimum setting and one at the full setting on each GPU. Record wall time from the executor's `kaliv-media-event` lines.
   - At the same time, record the VRAM peak:

   ```powershell
   nvidia-smi --query-gpu=index,uuid,memory.used,memory.total --format=csv -l 1 | Tee-Object vram.csv
   ```

   - Replace every [estimate] in §3 and §4 with the measured value.
8. **Run the rig checks.** Everything in `docs/MEDIA_VIDEO_GENERATION.md`, "Must be proven on the rig before any activation". This includes the outbound-network firewall rule for ComfyUI, which is §2, Anders' decision.
9. **Promote.** Only after 7 and 8 pass may a profile become `rig-qualified` [repo: profile schema]. Video stays off until Anders says otherwise.

## 6. What this document does not do

- It downloads nothing and changes no profile, environment file or supervisor default.
- It does not cover image-to-video, which is not served by the entry point.
- It does not touch cloud or egress settings. Media never leaves the rig.
- It claims no measured time. All times above are tagged [source] or [estimate].
