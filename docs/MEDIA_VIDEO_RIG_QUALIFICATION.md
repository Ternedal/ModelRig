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

## 6. Image-to-video: what it adds (#2366, #2459)

The entry point serves `image_to_video` under the same switch, and `video_generate` takes a picture from the conversation as the source (`docs/MEDIA_EXECUTOR.md`, "Image-to-video"). **Nothing of it has been run on the rig**, and the text-to-video model of §1 cannot do it: Wan 2.1 T2V 1.3B is text-only.

**A second profile, not a second task on the first.** A ComfyUI template renders exactly one task, and the adapter refuses a request for any other [repo: `comfy_video_adapter`]. So image-to-video is its own profile with its own template (the one with the `__KALIV_VIDEO_IMAGE__` slot on `LoadImage`), listing `tasks: ["image_to_video"]` only, and the text-to-video profile lists `["text_to_video"]` only. `video_generate` picks the profile by task: with one profile per task, nothing needs configuring; `KALIV_VIDEO_TOOL_PROFILE` only settles a choice between two profiles for the same task [repo: `image_generate_tool._choose_profile`].

**Model candidates for a 12 GB card:**

| | Wan 2.2 TI2V **5B** | Wan 2.1 Fun InP **1.3B** | Wan 2.1 / 2.2 I2V **14B** |
|---|---|---|---|
| What it is | One model for both text-to-video and image-to-video; in the official workflow the start image is an optional `Load image` node feeding `Wan22ImageToVideoLatent` [source: docs.comfy.org Wan2.2 tutorial] | Video between a first and a last frame; the lightweight variant "with lower VRAM requirements" [source: docs.comfy.org Wan2.1 Fun InP tutorial]. Whether it runs from a first frame alone is not stated [measure] | Image-to-video, separate 480P and 720P models [source: Comfy blog, Wan2.1 native support] |
| VRAM | "should fit well on 8GB vram with the ComfyUI native offloading" [source: docs.comfy.org] | no figure given [measure] | out of scope for 12 GB, as in §1 [estimate] |
| Diffusion model file | `wan2.2_ti2v_5B_fp16.safetensors` [source] | `wan2.1_fun_inp_1.3B_bf16.safetensors` [source] | not listed here |
| Other files | `wan2.2_vae.safetensors` (its own VAE, not §2's) and `umt5_xxl_fp8_e4m3fn_scaled.safetensors` (§2's text encoder) [source: docs.comfy.org Wan2.2 tutorial] | §2's text encoder and VAE, plus a CLIP vision file (`clip_vision_h.safetensors`) [source: the Fun tutorials' file listings; confirm against the workflow actually exported] | |
| Repository | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` [source] | `Comfy-Org/Wan_2.1_ComfyUI_repackaged` [source] | |
| License | Apache 2.0, commercial use allowed [source: docs.comfy.org Wan2.2 tutorial] | **confirm on the `alibaba-pai/Wan2.1-Fun-1.3B-InP` model card before use** | |

- **Recommendation: Wan 2.2 TI2V 5B, after §5 has passed for 1.3B text-to-video.** It is the only candidate here with a stated VRAM figure under 12 GB and a confirmed license, and one set of weights can back both profiles (two templates). Its cost is the one §1 already names: it fits through offloading, so host RAM and time are the open numbers [estimate; measure].
- **Fun InP 1.3B is the fallback** if 5B is too slow on a 3060: it is the size class already qualified in §5, but it is built for first-and-last-frame, it adds a fourth weight file to pin, and its license is not confirmed here.
- **Every weight file is pinned as in §2**, including the CLIP vision file if the template loads one: a model file the template names without a pin refuses the start [repo: `comfy_weights`].

**What the qualification adds to §5** (same steps, plus):

1. Export the image-to-video workflow in API format, with the `Load image` node enabled (for the 5B workflow it is bypassed by default [source]), and put `__KALIV_VIDEO_IMAGE__` on `LoadImage`'s `image` input; the other seven markers as in §5 step 4. The text-to-video template is a second export of the same workflow without that node.
2. A candidate image-to-video profile with its own `profile_id` and its own port: two video profiles on one port are refused with 78 [repo: `_check_comfy_ports`]. Two profiles on one GPU therefore mean two supervised ComfyUI instances taking turns on that card; whether that holds within the VRAM admission on a 3060 is not established [measure]. **The conservative start is one task per GPU**: text-to-video on `cuda:0`, image-to-video on `cuda:1`. Which arrangement to keep is Anders' decision after step 7's numbers.
3. Source pictures: generate one picture per size the image profile serves, then ask for a clip from each. A source larger than 4096 px per side or 64 MiB is refused before anything touches disk [repo: `docs/MEDIA_VIDEO_GENERATION.md`].
4. Negative cases, each must fail the job without stopping the executor: the source job of another owner, a source deleted from the gallery between submit and claim (`source_image_unavailable`), and a video job named as the source (`source_not_an_image`, refused at the tool).
5. From the chat: "lav et billede af …", wait for the picture, then "lav en video af det billede" as the next message; the model is told to pass `source_image_job_id="latest"`, the reply must carry a video job reference, and the clip must start from that picture. Also once before any picture exists: the answer must be that there is no finished picture (`no_source_image`), not an invented clip. **Whether qwen3:14b reliably passes `latest` is a rig measurement** [measure].

## 7. What this document does not do

- It downloads nothing and changes no profile, environment file or supervisor default.
- It does not touch cloud or egress settings. Media never leaves the rig.
- It claims no measured time. All times above are tagged [source] or [estimate].
