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

The entry point serves `image_to_video` under the same switch, and `video_generate` takes a picture from the conversation as the source (`docs/MEDIA_EXECUTOR.md`, "Image-to-video"). It ran on the rig for the first time on 21 November (§7). The text-to-video model of §1 cannot do it: Wan 2.1 T2V 1.3B is text-only.

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
5. From the chat: "lav et billede af …", wait for the picture, then "lav en video af det billede" as the next message; the model is told to pass `source_image_job_id="latest"`, the reply must carry a video job reference, and the clip must start from that picture. Also once before any picture exists: the answer must be that there is no finished picture (`no_source_image`), not an invented clip. **Whether qwen3:14b reliably passes `latest` is a rig measurement** [measure]. Then the case the review asked about: make a picture in a second conversation, go back to the first and ask for a video of "det billede" — with an app that sends `conversation_image_jobs` the clip must start from the first conversation's picture, not the newer one. Measured by `scripts/media_chat_probe.py --suite two-conversations`: the clip's job reference names its source picture job (`source_job_id`), and the suite passes only when that is the first conversation's.

## 7. First rig run, 21 November 2026 (dev channel: not evidence)

Run from the dev appliance on `integration/media-chat` (`74b2895d`), 2× RTX 3060, Ollama pinned to GPU 0 (`CUDA_VISIBLE_DEVICES`, `OLLAMA_SCHED_SPREAD=false`, `OLLAMA_VULKAN=false`, context 8192), media on `cuda:1`. Everything below is [measured] unless tagged. Nothing here promotes a profile.

**What was installed**

- ComfyUI tag `v0.46.2`, commit `10cdd12609eb17e8a90f2a2dd811b1c82f6107e7`, in `C:\Kaliv\ComfyUI` with its own venv (`C:\Kaliv\comfy-venv`, torch 2.14.1+cu126). `/system_stats` reports `comfyui_version` `0.46.2`.
- The two templates are in the repository, byte for byte as they ran: [`deploy/media/comfy-templates/`](../deploy/media/comfy-templates/). Core nodes only.

| | Text-to-video | Image-to-video |
|---|---|---|
| Profile | `wan21-t2v-1p3b-gpu1`, port 8189 | `wan22-ti2v-5b-gpu1`, port 8190 |
| Template, SHA-256 | `wan21-t2v-1p3b.json`, `4cd0d604b4728159eb351f84992819eaf2730bad7b4187889697e2020b798369` | `wan22-ti2v-5b.json`, `62402da4ec636592c416cc05e7a8bd81be5baa9b205a403ebaae752ebe58e4d5` |
| Repository revision | `Comfy-Org/Wan_2.1_ComfyUI_repackaged` @ `d6258323e18f14c60d37899da97ca555f3118259` | `Comfy-Org/Wan_2.2_ComfyUI_Repackaged` @ `5df3a4a3ed0628002308022198249dbbbd045d09` |
| Size, frames, steps, fps | 832×480, 33, 20, 16 | 704×704, 49, 20, 24 |
| Sampler | `uni_pc` / `simple`, cfg 6, shift 8 | `uni_pc` / `simple`, cfg 5, shift 8 |
| `resources` | `min_usable_gib` 8, `reserve_gib` 1.0 | `min_usable_gib` 9, `reserve_gib` 1.0 |

Weight pins (`{path, bytes, sha256}`, the rig's own hashes; §2's cross-check hash for the 1.3B model matched):

| Path under `models/` | Bytes | SHA-256 |
|---|---|---|
| `diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors` | 2838303560 | `be531024cd9018cb5b48c40cfbb6a6191645b1c792eb8bf4f8c1c6e10f924dc5` |
| `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6735906897 | `c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68` |
| `vae/wan_2.1_vae.safetensors` | 253815318 | `2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b` |
| `diffusion_models/wan2.2_ti2v_5B_fp16.safetensors` | 9999658848 | `456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e` |
| `vae/wan2.2_vae.safetensors` | 1409400960 | `e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156` |

**Times**

| | Directly against ComfyUI | Through the chat (executor's own time) |
|---|---|---|
| Text-to-video, 2.06 s clip | 150 s | 176–198 s; message to finished clip, median 205 s |
| Image-to-video, 2.04 s clip | 161 s | 240 s |

`media_chat_probe --suite video --stream --rounds 4`: 4/4 `video_generate`, 4/4 completed. `--suite two-conversations --stream --rounds 1`: all three cases passed, the clip was made from the first conversation's picture. Two video profiles on one GPU (two ports) took turns without a failure. **Not measured:** VRAM peak, host RAM, the full setting, more than one round of the two-conversation suite, and the Android and desktop bubbles with a clip.

**What the run found** (each is in the code or in this document now, unless it says otherwise)

1. **`SaveVideo` in 0.46.2 takes a compound format.** The API form is `"format": "mp4", "format.codec": "h264"`. `filename_prefix` must have no folder (the node's default is `video/ComfyUI`): the adapter takes one plain `.mp4` in the output root.
2. **ComfyUI ships a placeholder file in `models/embeddings/`** (`put_embeddings_or_textual_inversion_concepts_here`). `comfy_weights.check_lookup_is_unambiguous` refuses any unpinned file there, so the start is refused until it is deleted. Delete it as part of §5 step 2.
3. **Download into a folder of its own, then move the files** into `models/…`: the Hugging Face client leaves a `.cache` folder beside what it downloads.
4. **The resident proof was refused on Windows.** A venv's `Scripts\python.exe` is a starter; the interpreter that takes the lock is its child (proof pid 1904, spawned pid 5372). The supervisor now accepts a pid that is in the Job Object the child was started in. Run on the rig the same evening without any wrapper: loaded, three clips completed.
5. **ComfyUI was restarted for every clip** (`vram_short → closed → deferred → loaded`): the check before a job read a warm ComfyUI's own models as taken. Measured idle after a clip: `vram_free` 5.2–5.5 GiB of 12, `torch_vram_total` 64 MiB (so the models are not in torch's own figure, and a first fix that counted that figure changed nothing), `nvidia-smi` 6.2 GiB used. The supervisor now remembers what ComfyUI reports free when a job has finished and accepts the next job if the reading is no lower than that (512 MiB slack); lower is a shortage as before. Run on the rig the same evening: three clips in a row on one ComfyUI, 165 → 144 → 144 s (196–198 s before), message to finished clip 156 s median.
6. **A failed load said nothing.** The `failed_load` event now ends in a reason code (`resident_proof_mismatch`, `comfy_not_ready`, `comfy_exited_at_start`, `comfyui_version_mismatch`, or the exception's type), a failed job adds `job_error:<job>:<code>`, and ComfyUI's own output is kept in `<KALIV_COMFY_DIR>\cuda<N>\comfyui.log` (8 MiB, one earlier file kept).
7. **`KALIV_COMFY_WEIGHTS_CACHE`** was set (`C:\Kaliv\media-work\comfy\weights-cache.json`). Without it every ComfyUI start re-hashes 10–17 GB.
8. **The model chose `image_generate` for a video** when a persona was in force (6 of 11 right with the old rule). The rule now says that a video described in words needs no picture first (#2471): 4/4 through the worker, 12/12 directly against Ollama.
9. **The dev appliance does not start the executor**, and the executor block in `RIGDAG_MEDIE_I_CHAT.md` 1.2 must also carry the `KALIV_COMFY*` keys into the process.

## 8. Sound: LTX-2.3 (prepared, not run)

Anders, 21 November: a clip without sound is no use. Wan 2.1/2.2 render picture only, and the Wan versions with sound (2.5 and later) have no downloadable weights [source: comfy.org Wan workflow page; Runpod Wan 2.5 guide]. The candidate is **LTX-2.3**: picture and sound in one pass, text-to-video and image-to-video from the same files, native ComfyUI workflows with no custom nodes [source: docs.comfy.org LTX-2.3 tutorial]. The nodes it needs are in the rig's ComfyUI: `LTXAVTextEncoderLoader`, `LTXVAudioVAELoader`, `LTXVEmptyLatentAudio`, `LTXVConcatAVLatent`, `LTXVSeparateAVLatent`, `LTXVAudioVAEDecode`, and `CreateVideo` takes an `audio` input [repo: ComfyUI source at tag `v0.46.2`].

| File | Folder under `models/` | Size |
|---|---|---|
| `ltx-2.3-22b-dev-fp8.safetensors` | `checkpoints/` | 29.1 GB [source: `Lightricks/LTX-2.3-fp8` file listing] |
| `gemma_3_12B_it_fp4_mixed.safetensors` | `text_encoders/` | 9.45 GB [source: `Comfy-Org/ltx-2` file listing] |
| `ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors` | `loras/` | not looked up |

- **License: LTX-2 Community License**, not Apache. Free self-hosted use, including commercial, under USD 10 million annual revenue [source: ltx.io licence FAQ]. The profile's `license` is `ltx-2-community-license`.
- **Whether it is usable on a 12 GB card is a measurement.** The checkpoint is ten times the Wan 1.3B model and runs through ComfyUI's offloading to host RAM. NVIDIA's guide puts 540p at "12GB+"; Lightricks' own node pack asks for 32 GB [source: both]. Time per clip and peak host RAM are unknown [measure].
- **Host RAM limit.** The supervisor's Job Object lets one ComfyUI process commit 48 GiB. `KALIV_COMFY_HOST_MEMORY_GIB` (whole GiB, 1..64) raises it if the measurement says so [repo].
- **Two template rules were added for it** [repo: `comfy_workflow_template`]: an integer slot may sit on a `PrimitiveInt`'s `value` (the frame count goes to the video latent and the audio latent, the frame rate to three nodes, and a marker appears once), and a template whose schedule is part of the graph may leave the steps slot out (the distilled model runs a fixed list of sigmas).
- **The helper** `scripts/media_comfy_ltx23_setup.py` downloads the three files, submits the first stage of ComfyUI's own LTX-2.3 text-to-video graph (8 distilled steps, no spatial upscale, 768×512, 49 frames at 25 fps) to a running ComfyUI, samples ComfyUI's lowest free VRAM and host RAM while it renders, checks that the MP4 has a sound track, and only then hashes the weights and writes template and candidate profile (`ltx23-t2v-av-gpu1`, port 8191). `run --task image_to_video` does the same with the picture written into the video latent (`ltx23-i2v-av-gpu1`, port 8192, 640×640). Both graphs were submitted to a ComfyUI `v0.46.2` on a CPU with empty placeholder files: `/prompt` accepted them with no node errors, and execution stopped at loading the placeholder checkpoint, as it must. **Neither has rendered anything** [measure].
- The spatial upscale stage and the text encoder on the other card (`SelectCLIPDevice` is a core node in 0.46.2 [repo: ComfyUI source]) come after the first measurement, if it is worth going on.

## 9. What this document does not do

- It downloads nothing and changes no profile, environment file or supervisor default.
- It does not touch cloud or egress settings. Media never leaves the rig.
- §1–§6 claim no measured time: every time there is tagged [source] or [estimate]. §7 is the first measurement, on the dev channel.
