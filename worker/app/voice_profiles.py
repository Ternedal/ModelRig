"""Portable `.mrvoice` profiles produced by VoiceRig.

This module is deliberately optional. The existing Piper backend remains the
fallback when no installed `.mrvoice` profile exists, and Chatterbox is imported
lazily only when a profile is actually selected.

GPU policy is designed for a single 12 GB card shared with ASR/Ollama:
- prefer CUDA for Chatterbox when available;
- serialize synthesis;
- release an idle CUDA model after a short grace period;
- on CUDA OOM, retry once on CPU instead of killing the spoken turn.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import wave
import zipfile
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

_FORMAT = "modelrig-voice"
_FORMAT_VERSION = 1
_ENGINE = "chatterbox-multilingual"
_MODEL = "v3"
_REQUIRED_PAYLOADS = {"reference.wav", "conditioning.pt", "preview.wav"}
_ALLOWED_TOP_LEVEL = {"manifest.json", "checksums.json", *_REQUIRED_PAYLOADS}

# RLock matters for the explicit idle=0 setting: scheduling an immediate unload
# happens while synthesis still owns this lock. A plain Lock would deadlock.
_MODEL_LOCK = threading.RLock()
_MODELS: dict[str, Any] = {}
_UNLOAD_TIMER: threading.Timer | None = None
_LAST_CUDA_USE = 0.0


def voices_dir() -> Path:
    value = os.getenv("MODELRIG_VOICES_DIR", "~/.kaliv/voices")
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _max_package_bytes() -> int:
    try:
        mb = int(os.getenv("MRVOICE_MAX_MB", "128"))
    except ValueError:
        mb = 128
    return max(1, mb) * 1024 * 1024


def _validate_member_name(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("invalid path in .mrvoice package")
    if name not in _ALLOWED_TOP_LEVEL and not name.startswith("references/"):
        raise ValueError(f"unknown file in .mrvoice package: {name}")


def validate_package(package: Path) -> dict:
    """Validate the v1 package before any model code sees its contents."""
    limit = _max_package_bytes()
    if not package.is_file():
        raise ValueError(".mrvoice package not found")
    if package.stat().st_size > limit:
        raise ValueError(".mrvoice package is larger than the configured limit")

    with zipfile.ZipFile(package, "r") as zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("duplicate files in .mrvoice package")
        if sum(info.file_size for info in infos) > limit:
            raise ValueError("uncompressed .mrvoice package is larger than the configured limit")
        for info in infos:
            _validate_member_name(info.filename)
            if info.file_size > limit:
                raise ValueError(f"oversized member in .mrvoice package: {info.filename}")

        required = {"manifest.json", "checksums.json", *_REQUIRED_PAYLOADS}
        missing = required.difference(names)
        if missing:
            raise ValueError(f"missing .mrvoice files: {sorted(missing)}")

        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("format") != _FORMAT or manifest.get("format_version") != _FORMAT_VERSION:
            raise ValueError("unsupported .mrvoice format")
        engine = manifest.get("engine") or {}
        if engine.get("name") != _ENGINE or engine.get("model") != _MODEL:
            raise ValueError("unsupported .mrvoice engine")
        expected_files = {
            "reference": "reference.wav",
            "conditioning": "conditioning.pt",
            "preview": "preview.wav",
        }
        if (manifest.get("files") or {}) != expected_files:
            raise ValueError("invalid .mrvoice file map")

        checksums = json.loads(zf.read("checksums.json"))
        payloads = {name for name in names if name not in {"manifest.json", "checksums.json"}}
        if set(checksums) != payloads:
            raise ValueError("checksums do not cover exactly all .mrvoice payloads")
        for name, expected in checksums.items():
            actual = hashlib.sha256(zf.read(name)).hexdigest()
            if actual != expected:
                raise ValueError(f"checksum mismatch in {name}")
        return manifest


def _profiles() -> list[Path]:
    return sorted(voices_dir().glob("*.mrvoice"), key=lambda p: p.name.lower())


def default_profile_path() -> Path | None:
    root = voices_dir()
    marker = root / "default.txt"
    if marker.is_file():
        try:
            name = marker.read_text(encoding="utf-8").strip()
        except OSError:
            name = ""
        if name and Path(name).name == name and name.endswith(".mrvoice"):
            candidate = root / name
            if candidate.is_file():
                return candidate
    profiles = _profiles()
    return profiles[0] if len(profiles) == 1 else None


def list_profiles() -> list[dict]:
    selected = default_profile_path()
    result: list[dict] = []
    for package in _profiles():
        try:
            manifest = validate_package(package)
            result.append({
                "id": manifest.get("id"),
                "name": manifest.get("name"),
                "language": manifest.get("language"),
                "package": package.name,
                "default": package == selected,
                "valid": True,
            })
        except Exception as exc:  # noqa: BLE001 - status path must stay diagnostic
            result.append({
                "id": None,
                "name": package.stem,
                "language": None,
                "package": package.name,
                "default": package == selected,
                "valid": False,
                "detail": str(exc),
            })
    return result


def _chatterbox_available() -> bool:
    try:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: F401
        return True
    except Exception:
        return False


def is_available() -> bool:
    return default_profile_path() is not None and _chatterbox_available()


def _preferred_device() -> str:
    requested = os.getenv("MRVOICE_DEVICE", "auto").strip().lower()
    if requested not in {"auto", "cpu", "cuda"}:
        requested = "auto"
    if requested == "cpu":
        return "cpu"
    try:
        import torch
    except Exception:
        if requested == "cuda":
            raise RuntimeError("MRVOICE_DEVICE=cuda but torch/CUDA is unavailable")
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("MRVOICE_DEVICE=cuda but CUDA is unavailable")
    return "cuda" if torch.cuda.is_available() else "cpu"


def status() -> dict:
    package = default_profile_path()
    available = bool(package) and _chatterbox_available()
    device = None
    detail = None
    if package is None:
        detail = "no .mrvoice profile installed"
    elif not _chatterbox_available():
        detail = "chatterbox-tts not installed"
    else:
        try:
            device = _preferred_device()
        except RuntimeError as exc:
            available = False
            detail = str(exc)
    manifest = None
    if package is not None:
        try:
            manifest = validate_package(package)
        except Exception as exc:  # noqa: BLE001
            available = False
            detail = str(exc)
    return {
        "ok": available,
        "backend": "mrvoice",
        "voice": manifest.get("name") if manifest else None,
        "voice_id": manifest.get("id") if manifest else None,
        "package": package.name if package else None,
        "device": device,
        "detail": detail,
    }


def _idle_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("MRVOICE_GPU_IDLE_SECONDS", "30")))
    except ValueError:
        return 30.0


def _drop_model(device: str) -> None:
    model = _MODELS.pop(device, None)
    if model is not None:
        del model
    if device == "cuda":
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass


def _unload_cuda_model() -> None:
    global _UNLOAD_TIMER
    with _MODEL_LOCK:
        idle = _idle_seconds()
        elapsed = time.monotonic() - _LAST_CUDA_USE
        if "cuda" in _MODELS and elapsed >= idle:
            _drop_model("cuda")
            _logger.info("mrvoice Chatterbox CUDA model unloaded after %.1fs idle", elapsed)
        _UNLOAD_TIMER = None


def _schedule_cuda_unload() -> None:
    global _UNLOAD_TIMER
    if _UNLOAD_TIMER is not None:
        _UNLOAD_TIMER.cancel()
        _UNLOAD_TIMER = None
    idle = _idle_seconds()
    if idle <= 0:
        _unload_cuda_model()
        return
    timer = threading.Timer(idle + 0.1, _unload_cuda_model)
    timer.daemon = True
    _UNLOAD_TIMER = timer
    timer.start()


def _get_model(device: str):
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    if device not in _MODELS:
        _MODELS[device] = ChatterboxMultilingualTTS.from_pretrained(
            device=device,
            t3_model="v3",
        )
    return _MODELS[device]


def _materialize(package: Path, manifest: dict) -> Path:
    root = voices_dir() / ".cache" / str(manifest["id"])
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package, "r") as zf:
        for name in ("reference.wav", "conditioning.pt"):
            target = root / name
            raw = zf.read(name)
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest():
                temp = target.with_suffix(target.suffix + ".tmp")
                temp.write_bytes(raw)
                os.replace(temp, target)
    return root


def _load_conditionals(model, cache: Path, device: str) -> None:
    """Use saved conditioning when compatible, otherwise rebuild from reference."""
    try:
        from chatterbox.mtl_tts import Conditionals
        model.conds = Conditionals.load(
            cache / "conditioning.pt",
            map_location=device,
        ).to(device)
        return
    except Exception as exc:  # noqa: BLE001 - reference fallback is intentional
        _logger.warning("mrvoice conditioning could not be loaded; rebuilding: %s", exc)
    model.prepare_conditionals(str(cache / "reference.wav"), exaggeration=0.5)
    if model.conds is None:
        raise RuntimeError("Chatterbox produced no conditioning from .mrvoice reference")


def _duration(path: Path) -> tuple[int, float]:
    try:
        with wave.open(str(path), "rb") as f:
            sr = f.getframerate()
            frames = f.getnframes()
        return sr, round(frames / sr, 2) if sr else 0.0
    except wave.Error:
        try:
            import torchaudio
            info = torchaudio.info(str(path))
            sr = int(info.sample_rate)
            return sr, round(info.num_frames / sr, 2) if sr else 0.0
        except Exception:
            return 0, 0.0


def _synthesize_on(device: str, text: str, out_path: Path, package: Path, manifest: dict) -> dict:
    import torchaudio as ta

    model = _get_model(device)
    cache = _materialize(package, manifest)
    _load_conditionals(model, cache, device)
    defaults = manifest.get("defaults") or {}
    wav = model.generate(
        text,
        language_id=manifest.get("language") or "da",
        exaggeration=float(defaults.get("exaggeration", 0.5)),
        cfg_weight=float(defaults.get("cfg_weight", 0.5)),
        temperature=float(defaults.get("temperature", 0.8)),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ta.save(str(out_path), wav, model.sr)
    sr, duration = _duration(out_path)
    return {
        "out_path": str(out_path),
        "sample_rate": sr or int(model.sr),
        "duration": duration,
        "voice": manifest.get("name") or package.stem,
        "voice_id": manifest.get("id"),
        "backend": "mrvoice",
        "device": device,
    }


def _is_cuda_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "out of memory" in text and ("cuda" in text or "gpu" in text):
        return True
    try:
        import torch
        return isinstance(exc, torch.cuda.OutOfMemoryError)
    except Exception:
        return False


def synthesize_to_wav(text: str, out_path: str) -> dict:
    global _LAST_CUDA_USE
    package = default_profile_path()
    if package is None:
        raise RuntimeError("no .mrvoice profile installed")
    manifest = validate_package(package)
    preferred = _preferred_device()
    target = Path(out_path)

    with _MODEL_LOCK:
        try:
            result = _synthesize_on(preferred, text, target, package, manifest)
        except Exception as exc:
            if preferred != "cuda" or not _is_cuda_oom(exc):
                raise
            _logger.warning("mrvoice CUDA OOM; retrying this synthesis on CPU")
            _drop_model("cuda")
            result = _synthesize_on("cpu", text, target, package, manifest)
        if result.get("device") == "cuda":
            _LAST_CUDA_USE = time.monotonic()
            _schedule_cuda_unload()
        return result
