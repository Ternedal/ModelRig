#!/usr/bin/env python3
"""Rig helper: try LTX-2.3 (video WITH sound) directly against a running ComfyUI, measure it,
and only then write the workflow template and a candidate profile.

Why: Wan 2.1/2.2 render silent clips (rig 21/11). LTX-2.3 renders picture and sound in one pass
with core nodes only, but its checkpoint is 29 GB on a 12 GB card, so whether it is usable on the
rig is a measurement, not a guess. Nothing here is evidence and no profile is promoted.

    python scripts/media_comfy_ltx23_setup.py download            # ~40 GB, into --download-dir
    python scripts/media_comfy_ltx23_setup.py run [--frames 49]   # needs ComfyUI on --url
    python scripts/media_comfy_ltx23_setup.py run --task image_to_video

`run` moves the downloaded files into ComfyUI's models folder, submits the graph, samples
ComfyUI's own memory figures while it renders, checks that the MP4 has a sound track, and on
success hashes the weights and writes template + profile. A refused graph or a failed render
writes nothing.

The graph is the first stage of ComfyUI's own "Text to Video (LTX-2.3)" template (8 distilled
steps, no spatial upscale): the smallest thing that can answer "does it run here, and how long".
Stdlib only, except `download`, which uses huggingface_hub.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

M = "__KALIV_VIDEO_%s__"
CHECKPOINT = "ltx-2.3-22b-dev-fp8.safetensors"
TEXT_ENCODER = "gemma_3_12B_it_fp4_mixed.safetensors"
LORA = "ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors"
# (repository, file in the repository, path under ComfyUI's models folder)
FILES = (
    ("Lightricks/LTX-2.3-fp8", CHECKPOINT, f"checkpoints/{CHECKPOINT}"),
    ("Comfy-Org/ltx-2", f"split_files/text_encoders/{TEXT_ENCODER}", f"text_encoders/{TEXT_ENCODER}"),
    ("Comfy-Org/ltx-2.3", f"split_files/loras/{LORA}", f"loras/{LORA}"),
)
# task -> (profile id, template file, port, default size, the picture used for the direct test)
TASKS = {
    "text_to_video": ("ltx23-t2v-av-gpu1", "ltx23-t2v-av.json", 8191, (768, 512)),
    # Pictures from the chat are square (1024x1024): a square clip keeps the whole motif.
    "image_to_video": ("ltx23-i2v-av-gpu1", "ltx23-i2v-av.json", 8192, (640, 640)),
}
PROFILE_ID, TEMPLATE_NAME = TASKS["text_to_video"][:2]
TEST_IMAGE = "example.png"  # ships in ComfyUI's input folder
# The distilled schedule of ComfyUI's template: part of the graph, so the template has no steps slot.
SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
NEGATIVE = "pc game, console game, video game, cartoon, childish, ugly"


def graph(task: str = "text_to_video") -> dict:
    """API-format graph with the Kaliv slot markers. Frames and fps sit on PrimitiveInt nodes
    because several nodes need them (video latent, audio latent, conditioning, the muxer).

    image_to_video adds the first-frame path of ComfyUI's own template: the picture is scaled to
    the clip's size, prepared, and written into the empty video latent (strength 0.7). Width and
    height then go to two nodes each, so they sit on PrimitiveInt nodes as well."""
    nodes = _text_to_video()
    if task == "image_to_video":
        nodes["24"] = {"class_type": "PrimitiveInt", "inputs": {"value": M % "WIDTH"}}
        nodes["25"] = {"class_type": "PrimitiveInt", "inputs": {"value": M % "HEIGHT"}}
        nodes["7"]["inputs"].update(width=["24", 0], height=["25", 0])
        nodes["26"] = {"class_type": "LoadImage", "inputs": {"image": M % "IMAGE"}}
        nodes["27"] = {"class_type": "ResizeImageMaskNode",
                       "inputs": {"input": ["26", 0], "resize_type": "scale dimensions",
                                  "resize_type.width": ["24", 0], "resize_type.height": ["25", 0],
                                  "resize_type.crop": "center", "scale_method": "lanczos"}}
        nodes["28"] = {"class_type": "LTXVPreprocess", "inputs": {"image": ["27", 0], "img_compression": 18}}
        nodes["29"] = {"class_type": "LTXVImgToVideoInplace",
                       "inputs": {"vae": ["1", 2], "image": ["28", 0], "latent": ["7", 0], "strength": 0.7,
                                  "bypass": False}}
        nodes["10"]["inputs"]["video_latent"] = ["29", 0]
    elif task != "text_to_video":
        raise ValueError(f"unknown task {task!r}")
    return nodes


def _text_to_video() -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CHECKPOINT}},
        "2": {"class_type": "LTXAVTextEncoderLoader",
              "inputs": {"text_encoder": TEXT_ENCODER, "ckpt_name": CHECKPOINT, "device": "default"}},
        "3": {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["1", 0], "lora_name": LORA, "strength_model": 0.5}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": M % "PROMPT"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": NEGATIVE}},
        "20": {"class_type": "PrimitiveInt", "inputs": {"value": M % "FRAMES"}},
        "21": {"class_type": "PrimitiveInt", "inputs": {"value": M % "FPS"}},
        # FLOAT on output 0, INT on output 1: ComfyUI's own way to hand one number to both kinds.
        "22": {"class_type": "ComfyMathExpression", "inputs": {"expression": "a", "values.a": ["21", 0]}},
        "6": {"class_type": "LTXVConditioning",
              "inputs": {"positive": ["4", 0], "negative": ["5", 0], "frame_rate": ["22", 0]}},
        "7": {"class_type": "EmptyLTXVLatentVideo",
              "inputs": {"width": M % "WIDTH", "height": M % "HEIGHT", "length": ["20", 0], "batch_size": 1}},
        "8": {"class_type": "LTXVAudioVAELoader", "inputs": {"ckpt_name": CHECKPOINT}},
        "9": {"class_type": "LTXVEmptyLatentAudio",
              "inputs": {"audio_vae": ["8", 0], "frames_number": ["20", 0], "frame_rate": ["22", 1], "batch_size": 1}},
        "10": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["7", 0], "audio_latent": ["9", 0]}},
        "11": {"class_type": "RandomNoise", "inputs": {"noise_seed": M % "SEED"}},
        "12": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "13": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS}},
        "14": {"class_type": "CFGGuider",
               "inputs": {"model": ["3", 0], "positive": ["6", 0], "negative": ["6", 1], "cfg": 1.0}},
        "15": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["11", 0], "guider": ["14", 0], "sampler": ["12", 0], "sigmas": ["13", 0],
                          "latent_image": ["10", 0]}},
        "16": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["15", 0]}},
        "17": {"class_type": "VAEDecodeTiled",
               "inputs": {"samples": ["16", 0], "vae": ["1", 2], "tile_size": 512, "overlap": 64,
                          "temporal_size": 4096, "temporal_overlap": 4}},
        "18": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["16", 1], "audio_vae": ["8", 0]}},
        "19": {"class_type": "CreateVideo", "inputs": {"images": ["17", 0], "audio": ["18", 0], "fps": ["22", 0]}},
        "23": {"class_type": "SaveVideo",
               "inputs": {"video": ["19", 0], "filename_prefix": "kaliv", "format": "mp4", "format.codec": "h264"}},
    }


def bound(values: dict, task: str = "text_to_video") -> dict:
    out = json.loads(json.dumps(graph(task)))
    for node in out.values():
        for key, value in node["inputs"].items():
            for name, filled in values.items():
                if value == M % name:
                    node["inputs"][key] = filled
    return out


def template_bytes(task: str = "text_to_video") -> bytes:
    return json.dumps(graph(task), indent=1).encode("ascii")


def profile(pins: list, revision: str, template_sha: str, *, width: int, height: int, frames: int, fps: int,
            task: str = "text_to_video") -> dict:
    profile_id, template_name, port, _size = TASKS[task]
    return {
        "schema": "kaliv-media-profile/v1", "profile_id": profile_id, "modality": "video",
        "tasks": [task], "backend": "comfyui", "pipeline": None,
        "model_id": "Lightricks/LTX-2.3-fp8", "revision": revision,
        # max_steps is not used: the template carries its own schedule (no steps slot).
        "limits": {"max_prompt_chars": 2000, "sizes": [[width, height]], "max_steps": 8, "max_frames": frames},
        "outputs": ["video/mp4"],
        "resources": {"min_usable_gib": 9, "reserve_gib": 1.0, "devices": ["cuda:1"], "cpu_offload": True},
        "qualification": "candidate", "license": "ltx-2-community-license",
        "backend_options": {"template_name": template_name, "template_sha256": template_sha, "fps": fps,
                            "max_render_seconds": 3600, "max_output_bytes": 268435456, "port": port,
                            "comfyui_version": "0.46.2", "weights": pins},
    }


def has_sound_track(data: bytes) -> bool:
    """An MP4 with sound has a track whose handler type is 'soun' (ISO 14496-12, hdlr box)."""
    at = 0
    while True:
        at = data.find(b"hdlr", at)
        if at < 0:
            return False
        if data[at + 12:at + 16] == b"soun":
            return True
        at += 4


def _call(url: str, path: str, body=None, timeout: float = 30):
    request = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def download(args) -> int:
    from huggingface_hub import hf_hub_download
    failed = 0
    for repo, name, _target in FILES:
        try:
            print("OK  ", hf_hub_download(repo, name, local_dir=args.download_dir), flush=True)
        except Exception as exc:  # a gated repository, the network: name it and go on
            failed += 1
            print("FEJL", repo, name, type(exc).__name__, str(exc)[:300], flush=True)
    return 1 if failed else 0


def _move_weights(args) -> bool:
    ok = True
    for _repo, name, target in FILES:
        source = Path(args.download_dir, *name.split("/"))
        destination = Path(args.models_dir, *target.split("/"))
        if source.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        present = destination.is_file()
        ok = ok and present
        print("VAEGT ", "ok     " if present else "MANGLER", target, flush=True)
    return ok


def _revision(args) -> str:
    """The repository commit the checkpoint was downloaded at (huggingface_hub keeps it beside the file)."""
    meta = Path(args.download_dir, ".cache", "huggingface", "download", CHECKPOINT + ".metadata")
    try:
        first = meta.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return "0" * 40
    return first if len(first) == 40 else "0" * 40


def run(args) -> int:
    if not _move_weights(args):
        print("STOP: vaegtene er ikke hentet (koer 'download' foerst)")
        return 1
    profile_id, template_name, _port, _size = TASKS[args.task]
    values = {"PROMPT": args.prompt, "WIDTH": args.width, "HEIGHT": args.height, "FRAMES": args.frames,
              "FPS": args.fps, "SEED": 1, "IMAGE": TEST_IMAGE}
    status, body = _call(args.url, "/prompt", {"prompt": bound(values, args.task)})
    if status != 200 or not body.get("prompt_id"):
        print("STOP: grafen blev afvist:", json.dumps(body.get("node_errors") or body.get("error"))[:3000])
        return 1
    prompt_id, started = body["prompt_id"], time.time()
    print(f"GRAF ok, render startet ({args.task}): {args.width}x{args.height}, {args.frames} billeder, {args.fps} fps", flush=True)
    entry, low_vram, low_ram, last = None, None, None, 0.0
    while time.time() - started < args.timeout:
        try:
            entry = _call(args.url, "/history/" + prompt_id)[1].get(prompt_id)
            stats = _call(args.url, "/system_stats")[1]
            vram = stats["devices"][0]["vram_free"]
            ram = stats["system"]["ram_free"]
            low_vram = vram if low_vram is None else min(low_vram, vram)
            low_ram = ram if low_ram is None else min(low_ram, ram)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            pass  # ComfyUI is busy or gone: the next round says which
        if entry:
            break
        if time.time() - last >= 30:
            last = time.time()
            print("  render ... %d s  laveste fri VRAM %s MiB, laveste fri RAM %s MiB"
                  % (time.time() - started, low_vram and low_vram >> 20, low_ram and low_ram >> 20), flush=True)
        time.sleep(5)
    elapsed = time.time() - started
    state = (entry or {}).get("status", {})
    print("RENDER", state.get("status_str"), "%d s" % elapsed)
    print("LAVESTE fri VRAM %s MiB, fri RAM %s MiB" % (low_vram and low_vram >> 20, low_ram and low_ram >> 20))
    print("OUTPUT", json.dumps((entry or {}).get("outputs"))[:600])
    if state.get("status_str") != "success":
        print(json.dumps(state.get("messages"))[:3000])
        print("STOP: render fejlede eller blev ikke faerdig - send linjerne ovenfor")
        return 1
    names = [item.get("filename") for output in entry["outputs"].values()
             for key in ("videos", "gifs", "images") for item in output.get(key, [])]
    sound = None
    if len(names) == 1 and isinstance(names[0], str):
        try:
            sound = has_sound_track(Path(args.output_dir, names[0]).read_bytes())
        except OSError:
            sound = None
    print("LYDSPOR:", {True: "ja", False: "NEJ", None: "kunne ikke laese filen"}[sound])
    if sound is not True:
        print("STOP: klippet har intet lydspor - intet skrevet")
        return 1

    pins = []
    for _repo, _name, target in FILES:
        digest, path = hashlib.sha256(), Path(args.models_dir, *target.split("/"))
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(16 << 20), b""):
                digest.update(chunk)
        pins.append({"path": target, "sha256": digest.hexdigest(), "bytes": path.stat().st_size})
        print("PIN   ", target, pins[-1]["bytes"], pins[-1]["sha256"], flush=True)
    revision = _revision(args)
    print("REVISION", revision, "" if revision.strip("0") else "(IKKE FUNDET - sig til)")
    raw = template_bytes(args.task)
    sha = hashlib.sha256(raw).hexdigest()
    made = profile(pins, revision, sha, width=args.width, height=args.height, frames=args.frames, fps=args.fps,
                   task=args.task)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
    try:
        from app.comfy_workflow_template import load_template
        from app.media_generation_profiles import parse_profile
        parse_profile(made)
        template = load_template(raw, sha, pinned_files=[pin["path"] for pin in pins])
        print("REPO-KONTROL ok: profil og skabelon godkendt, task =", template.task)
    except Exception as exc:
        print("STOP: repoets kontrol afviste: %s: %s" % (type(exc).__name__, exc))
        return 1
    Path(args.template_dir).mkdir(parents=True, exist_ok=True)
    Path(args.template_dir, template_name).write_bytes(raw)
    with open(Path(args.profile_dir, profile_id + ".json"), "w", encoding="ascii", newline="\n") as handle:
        json.dump(made, handle, indent=1)
    print("SKREVET skabelon", sha, "+ profil", profile_id)
    print("TID: %d s for %.1f s klip (%dx%d)" % (elapsed, args.frames / args.fps, args.width, args.height))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("download", "run"))
    parser.add_argument("--download-dir", default=r"C:\Kaliv\comfy-weights-ltx")
    parser.add_argument("--models-dir", default=r"C:\Kaliv\ComfyUI\models")
    parser.add_argument("--output-dir", default=r"C:\Kaliv\ComfyUI\output", help="the running ComfyUI's output folder")
    parser.add_argument("--template-dir", default=r"C:\ModelRig\comfy-templates")
    parser.add_argument("--profile-dir", default=r"C:\ModelRig\media-profiles")
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--task", choices=sorted(TASKS), default="text_to_video")
    parser.add_argument("--width", type=int, help="default: 768 (text) or 640 (image)")
    parser.add_argument("--height", type=int, help="default: 512 (text) or 640 (image)")
    parser.add_argument("--frames", type=int, default=49, help="8n+1; 49 is about 2 s at 25 fps")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--prompt", default="A paper boat drifts across a still pond in soft morning light, "
                        "small ripples spread from its bow; quiet water lapping and distant birdsong.")
    args = parser.parse_args(argv)
    args.width = args.width or TASKS[args.task][3][0]
    args.height = args.height or TASKS[args.task][3][1]
    if args.task == "image_to_video" and args.prompt == parser.get_default("prompt"):
        args.prompt = "The scene comes alive with gentle natural motion, slow camera push-in; soft ambient sound."
    if args.command == "run" and (args.width % 32 or args.height % 32 or args.frames % 8 != 1):
        parser.error("width and height must be multiples of 32, frames 8n+1")
    return download(args) if args.command == "download" else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
