#!/usr/bin/env python3
"""Read-only, localhost-only Ollama inference diagnostic. NEVER release evidence.

No pulls, no runtime setting changes, no external endpoints, no model output
in reports. Measures one explicit installed model and bounded prompt lengths.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)

_MAX_REPLY = 1024 * 1024
_PROMPT = "Svar kort på dansk: Hvad er forskellen mellem CPU og GPU?"


class ProbeError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("Ollama redirected request; fail closed")


def _ensure_loopback(raw: str) -> str:
    try:
        url = urlsplit(raw)
        port = url.port
    except ValueError as exc:
        raise ProbeError("Invalid Ollama URL") from exc
    if (url.scheme != "http"
            or url.hostname not in ("127.0.0.1", "::1")
            or port is None or not 1 <= port <= 65535
            or url.username is not None or url.password is not None
            or url.path not in ("", "/")
            or url.query or url.fragment):
        raise ProbeError("Ollama endpoint must be a bare HTTP loopback IP and port")
    return raw.rstrip("/")


def _request_json(base: str, route: str, *, body: dict | None, timeout: float):
    if route not in ("/api/tags", "/api/ps", "/api/chat"):
        raise ProbeError("Unexpected endpoint")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    data = None if body is None else json.dumps(
        body, ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    request = Request(
        base + route, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read(_MAX_REPLY + 1)
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise ProbeError("Local Ollama request failed: " + type(exc).__name__) from exc
    if len(payload) > _MAX_REPLY:
        raise ProbeError("Local Ollama response exceeds size limit")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProbeError("Local Ollama returned invalid JSON") from exc
    if not isinstance(value, dict) or value.get("error"):
        raise ProbeError("Local Ollama returned an error object")
    return value


def _nonnegative_number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProbeError(f"Ollama {key} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ProbeError(f"Ollama {key} must be finite and nonnegative")
    return number


def _metrics(response: dict, wall_seconds: float, ordinal: int) -> dict:
    if response.get("done") is not True:
        raise ProbeError("Ollama response incomplete; not a successful measurement")
    counts = ("prompt_eval_count", "eval_count")
    times = ("load_duration", "prompt_eval_duration", "eval_duration")
    values = {key: _nonnegative_number(response.get(key), key)
              for key in (*counts, *times)}
    if not all(values[key].is_integer() for key in counts):
        raise ProbeError("Ollama token counts must be whole numbers")
    if values["eval_count"] and not values["eval_duration"]:
        raise ProbeError("Missing token-generation duration")
    if values["prompt_eval_count"] and not values["prompt_eval_duration"]:
        raise ProbeError("Missing prompt-evaluation duration")
    return {
        "run": ordinal,
        "wall_seconds": round(wall_seconds, 3),
        "load_seconds": round(values["load_duration"] / 1e9, 3),
        "prompt_tokens": int(values["prompt_eval_count"]),
        "prompt_seconds": round(values["prompt_eval_duration"] / 1e9, 3),
        "output_tokens": int(values["eval_count"]),
        "decode_seconds": round(values["eval_duration"] / 1e9, 3),
        "decode_tokens_per_second": (
            round(values["eval_count"] * 1e9 / values["eval_duration"], 2)
            if values["eval_duration"] else 0.0
        ),
    }


def _loaded_size(ps: dict, model: str) -> dict:
    models = ps.get("models")
    if not isinstance(models, list):
        raise ProbeError("Ollama process list is malformed")
    for item in models:
        if not isinstance(item, dict):
            raise ProbeError("Ollama process list contains invalid model entry")
        if item.get("name") == model or item.get("model") == model:
            vram = item.get("size_vram")
            return {
                "loaded": True,
                "reported_vram_bytes": (
                    int(_nonnegative_number(vram, "size_vram"))
                    if vram is not None else None
                ),
            }
    return {"loaded": False, "reported_vram_bytes": None}


def measure(
    base: str, model: str, *, runs: int = 3,
    num_predict: int = 96, num_ctx: int = 4096, timeout: float = 600,
) -> dict:
    base = _ensure_loopback(base)
    if not isinstance(model, str) or not model.strip() or len(model) > 128:
        raise ProbeError("A bounded model name is required")
    if any(ord(c) < 33 or ord(c) > 126 for c in model):
        raise ProbeError("Model name must be printable ASCII without whitespace")
    if not (1 <= runs <= 5 and 16 <= num_predict <= 256
            and 512 <= num_ctx <= 32768 and 10 <= timeout <= 1200):
        raise ProbeError("Invalid bounded benchmark options")
    tags = _request_json(base, "/api/tags", body=None, timeout=timeout)
    installed = tags.get("models")
    if not isinstance(installed, list) or model not in {
        x.get("name", x.get("model")) for x in installed if isinstance(x, dict)
    }:
        raise ProbeError("Model is not installed; benchmark refuses model pull")
    before = _loaded_size(
        _request_json(base, "/api/ps", body=None, timeout=timeout), model
    )
    records = []
    for index in range(runs):
        request = {
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": _PROMPT}],
            "options": {
                "num_predict": num_predict,
                "num_ctx": num_ctx,
                "temperature": 0.0,
            },
        }
        started = time.monotonic()
        body = _request_json(base, "/api/chat", body=request, timeout=timeout)
        records.append(_metrics(body, time.monotonic() - started, index + 1))
    after = _loaded_size(
        _request_json(base, "/api/ps", body=None, timeout=timeout), model
    )
    warm = records[1:] if len(records) > 1 else []
    return {
        "schema": "modelrig/ollama-local-perf-observation/v1",
        "authority": "DIAGNOSTIC_ONLY_NOT_RELEASE_EVIDENCE",
        "model": model,
        "ollama_loopback": base,
        "num_predict_limit": num_predict,
        "num_ctx": num_ctx,
        "first_request_may_already_be_warm": True,
        "loaded_before": before,
        "loaded_after": after,
        "measurements": records,
        "warm_decode_tps_median": (
            round(statistics.median(x["decode_tokens_per_second"] for x in warm), 2)
            if warm else None
        ),
        "note": (
            "Reported VRAM is not per-card offload proof. "
            "Check nvidia-smi and ollama ps on the physical rig; "
            "compare equal contexts and model quality separately."
        ),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:11435")
    p.add_argument("--model", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--num-predict", type=int, default=96)
    p.add_argument("--num-ctx", type=int, default=4096)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--json-out", type=Path)
    args = p.parse_args(argv)
    try:
        result = measure(
            args.url, args.model, runs=args.runs,
            num_predict=args.num_predict, num_ctx=args.num_ctx,
            timeout=args.timeout,
        )
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if args.json_out is not None:
            # Diagnostic output never clobbers files, especially not release evidence.
            if args.json_out.is_symlink():
                raise ProbeError("Report destination must not be a symlink")
            with args.json_out.open("x", encoding="utf-8") as output:
                output.write(encoded + "\n")
        print(encoded)
    except (ProbeError, FileExistsError, OSError) as exc:
        p.exit(2, f"LOCAL PROBE REFUSED: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
