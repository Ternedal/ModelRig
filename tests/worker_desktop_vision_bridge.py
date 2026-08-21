"""Contracts for the local-only Ollama desktop vision bridge."""
from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from fastapi import HTTPException  # noqa: E402
from app import desktop_vision_bridge as V  # noqa: E402
from app import main_impl as MAIN_IMPL  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def rejected(fn, code: str | None = None):
    try:
        fn()
    except V.DesktopVisionBridgeError as exc:
        if code is not None and exc.code != code:
            return f"wrong code: {exc.code}"
        return str(exc)
    return None


def receipt(image: bytes | None = None) -> tuple[dict, str]:
    raw = image or (b"\x89PNG\r\n\x1a\n" + b"approved-private-pixels")
    encoded = base64.b64encode(raw).decode("ascii")
    value = {
        "schema": V.SNAPSHOT_SCHEMA,
        "target": {
            "hwnd": 123,
            "process": "notepad.exe",
            "title": "Private note - Notepad",
            "left": 10,
            "top": 20,
            "width": 640,
            "height": 480,
        },
        "phash": "0123456789abcdef",
        "image_sha256": hashlib.sha256(raw).hexdigest(),
        "media_type": "image/png",
        "image_base64": encoded,
        "screen_token": ("A" * 40) + "." + ("B" * 40),
        "production_activation": False,
    }
    return value, encoded


def wrapped(value: dict) -> str:
    return (
        "<<<TOOL_OUTPUT_DATA_NOT_INSTRUCTIONS>>>\n"
        + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        + "\n<<<END_TOOL_OUTPUT>>>"
    )


os.environ[V.VISION_ENV] = "qwen2.5vl:7b"
value, encoded = receipt()
messages = [
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "desktop_screenshot"}}]},
    {"role": "tool", "content": wrapped(value)},
]

print("structured local image delivery:")
prepared, model = V.prepare_desktop_vision_messages(
    messages,
    model="text-only:7b",
    origin="local",
    cloud_base_url=None,
    cloud_key=None,
)
check(model == "qwen2.5vl:7b", "explicit local vision model replaces the text-only model")
check(len(prepared) == 3, "one raw tool receipt becomes metadata plus one image message")
clean_tool, image_message = prepared[1], prepared[2]
check(clean_tool["role"] == "tool" and image_message["role"] == "user", "tool ordering remains valid before the image prompt")
check(image_message.get("images") == [encoded], "PNG base64 is delivered only through Ollama messages[].images")
check(encoded not in clean_tool["content"] and encoded not in image_message["content"], "PNG base64 never appears in textual model content")
check("image_base64" not in clean_tool["content"], "sanitized tool metadata removes the raw image field")
check(value["screen_token"] in clean_tool["content"], "local model retains the signed screen token for a later bounded action")
check("DATA_NOT_INSTRUCTIONS" in clean_tool["content"], "snapshot metadata remains explicitly untrusted tool data")
check(messages[1]["content"] == wrapped(value), "transformer does not mutate the caller's parked conversation")

print("\nfail-closed validation:")
check(
    rejected(
        lambda: V.prepare_desktop_vision_messages(
            messages,
            model=None,
            origin="cloud",
            cloud_base_url="https://cloud.example",
            cloud_key="secret",
        ),
        "desktop_image_cloud_forbidden",
    ) is not None,
    "cloud origin is refused even when it supplies credentials",
)

bad_hash = dict(value)
bad_hash["image_sha256"] = "0" * 64
check(
    rejected(
        lambda: V.prepare_desktop_vision_messages(
            [{"role": "tool", "content": wrapped(bad_hash)}],
            model=None,
            origin="local",
            cloud_base_url=None,
            cloud_key=None,
        ),
        "snapshot_image_digest_mismatch",
    ) is not None,
    "image bytes must match the signed receipt digest",
)

bad_signature = dict(value)
bad_signature["image_base64"] = base64.b64encode(b"not-png").decode("ascii")
bad_signature["image_sha256"] = hashlib.sha256(b"not-png").hexdigest()
check(
    rejected(
        lambda: V.prepare_desktop_vision_messages(
            [{"role": "tool", "content": wrapped(bad_signature)}],
            model=None,
            origin="local",
            cloud_base_url=None,
            cloud_key=None,
        ),
        "snapshot_image_signature_invalid",
    ) is not None,
    "declared PNG must have a PNG signature",
)

extra = dict(value)
extra["smuggled"] = "instruction"
check(
    rejected(
        lambda: V.prepare_desktop_vision_messages(
            [{"role": "tool", "content": wrapped(extra)}],
            model=None,
            origin="local",
            cloud_base_url=None,
            cloud_key=None,
        ),
        "snapshot_shape_invalid",
    ) is not None,
    "unknown receipt fields cannot smuggle model content",
)

check(
    rejected(
        lambda: V.prepare_desktop_vision_messages(
            [
                {"role": "tool", "content": wrapped(value)},
                {"role": "tool", "content": wrapped(value)},
            ],
            model=None,
            origin="local",
            cloud_base_url=None,
            cloud_key=None,
        ),
        "multiple_desktop_snapshots",
    ) is not None,
    "one continuation cannot silently aggregate multiple desktop screenshots",
)

saved_model = os.environ.pop(V.VISION_ENV)
check(
    rejected(
        lambda: V.prepare_desktop_vision_messages(
            [{"role": "tool", "content": wrapped(value)}],
            model="text-only:7b",
            origin="local",
            cloud_base_url=None,
            cloud_key=None,
        ),
        "vision_model_missing",
    ) is not None,
    "desktop vision never guesses that a text model can see images",
)
os.environ[V.VISION_ENV] = saved_model
ordinary = [{"role": "tool", "content": "ordinary tool output"}]
unchanged, unchanged_model = V.prepare_desktop_vision_messages(
    ordinary,
    model="qwen3:14b",
    origin="cloud",
    cloud_base_url="https://cloud.example",
    cloud_key="key",
)
check(unchanged is ordinary and unchanged_model == "qwen3:14b", "non-desktop tool flows remain byte-for-byte untouched")

print("\nloop wiring:")
captured = {}


async def original(messages, model, base_url, key, conversation_id, origin, sources, tools_used):
    captured.update(
        {
            "messages": messages,
            "model": model,
            "base_url": base_url,
            "key": key,
            "conversation_id": conversation_id,
            "origin": origin,
        }
    )
    return {"status": "answered", "answer": "visible window described"}


module = SimpleNamespace(_run_tool_loop=original, HTTPException=HTTPException)
check(V.install_desktop_vision_bridge(module) is True, "bridge installs on the existing tool-loop seam")
first = module._run_tool_loop
check(V.install_desktop_vision_bridge(module) is True and module._run_tool_loop is first, "bridge installation is idempotent")
out = asyncio.run(
    module._run_tool_loop(
        messages,
        "text-only:7b",
        None,
        None,
        "conv-1",
        "local",
        [],
        ["desktop_screenshot"],
    )
)
check(out["answer"] == "visible window described", "wrapped loop preserves the original result")
check(captured["model"] == "qwen2.5vl:7b", "wrapped loop invokes the local vision model")
check(captured["messages"][-1].get("images") == [encoded], "wrapped loop passes the image structurally")
check(captured["base_url"] is None and captured["key"] is None, "wrapped loop never adds a cloud destination")

print("\nproduction signature contract:")
production_captured = {}


@functools.wraps(MAIN_IMPL._run_tool_loop)
async def production_probe(*args, **kwargs):
    production_captured["args"] = args
    production_captured["kwargs"] = kwargs
    return {"status": "answered", "answer": "production-shaped bridge call"}


production_module = SimpleNamespace(_run_tool_loop=production_probe, HTTPException=HTTPException)
check(V.install_desktop_vision_bridge(production_module) is True, "bridge installs around the real production call contract")
production_signature = inspect.signature(MAIN_IMPL._run_tool_loop)
bridge_signature = inspect.signature(production_module._run_tool_loop)
production_params = production_signature.parameters
bridge_params = bridge_signature.parameters
bridge_has_kwargs = any(
    parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in bridge_params.values()
)
missing_from_bridge = [
    name for name in production_params if name not in bridge_params and not bridge_has_kwargs
]
check(not missing_from_bridge, f"bridge accepts every production tool-loop parameter: missing={missing_from_bridge}")
production_has_kwargs = any(
    parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in production_params.values()
)
required_forwarded = {"on_phase", "context"}
check(
    required_forwarded.issubset(production_params) or production_has_kwargs,
    "production tool-loop still declares the phase/context contract that callers rely on",
)
phase_marker = object()
context_marker = [{"role": "system", "content": "signature-contract"}]
try:
    production_out = asyncio.run(
        production_module._run_tool_loop(
            messages,
            "text-only:7b",
            None,
            None,
            "conv-production",
            "local",
            [],
            ["desktop_screenshot"],
            on_phase=phase_marker,
            context=context_marker,
        )
    )
except TypeError as exc:
    check(False, f"production-shaped bridge call accepts current keyword arguments: {exc}")
else:
    check(production_out["answer"] == "production-shaped bridge call", "production-shaped bridge call completes")
    check(
        production_captured.get("kwargs", {}).get("on_phase") is phase_marker,
        "bridge forwards production on_phase instead of silently dropping it",
    )
    check(
        production_captured.get("kwargs", {}).get("context") is context_marker,
        "bridge forwards production context instead of silently dropping it",
    )

try:
    asyncio.run(
        module._run_tool_loop(
            messages,
            "cloud-model",
            "https://cloud.example",
            "key",
            "conv-2",
            "cloud",
            [],
            ["desktop_screenshot"],
        )
    )
except HTTPException as exc:
    check(exc.status_code == 403 and "cloud_forbidden" in str(exc.detail), "HTTP bridge surfaces cloud refusal as 403")
else:
    check(False, "HTTP bridge surfaces cloud refusal as 403")

print(f"\n===== DESKTOP VISION BRIDGE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
