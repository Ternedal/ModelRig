#!/usr/bin/env python3
"""Opt-in, loopback-only Ollama token-latency benchmark (never a release gate).

No configuration changes, model pull, remote calls, artifact persistence by
default, or physical GPU qualification. Uses the local Ollama /api/generate
streaming endpoint to report the actual token-generation timing and TTFT.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "modelrig/ollama-local-inference-benchmark/v1"
DEFAULT_PROMPT = (
    "Skriv tre korte punkter på dansk om hvordan man måler svarhastighed "
    "på en sprogmodel reproducerbart."
)
MAX_EVENT_BYTES = 65536
MAX_EVENTS = 2048
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


class BenchmarkError(ValueError):
    pass


def local_target(base_url: str) -> tuple[str, int]:
    """No proxy, redirects, DNS, remote hosts, credentials or URL path."""
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise BenchmarkError("invalid Ollama endpoint") from exc
    if (parsed.scheme != "http" or host not in LOOPBACK_HOSTS
            or port is None or not (1 <= port <= 65535)
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise BenchmarkError(
            "Ollama benchmark requires literal loopback http://127.0.0.1:PORT "
            "or http://[::1]:PORT (no credentials/path/query)"
        )
    return host, port


def _positive_integer(value: object, label: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise BenchmarkError(f"{label} must be a valid nonnegative integer")
    return value


def measure_once(
    target: tuple[str, int], model: str, *,
    num_ctx: int, num_predict: int, prompt: str, timeout: int,
) -> dict[str, float | int]:
    payload = json.dumps({
        "model": model, "prompt": prompt, "stream": True,
        "options": {
            "temperature": 0, "num_ctx": num_ctx, "num_predict": num_predict,
        },
    }, ensure_ascii=False).encode("utf-8")
    conn = http.client.HTTPConnection(target[0], target[1], timeout=timeout)
    start = time.monotonic_ns()
    first_token_ns: int | None = None
    final: dict | None = None
    events = 0
    try:
        conn.request("POST", "/api/generate", body=payload, headers={
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
        })
        response = conn.getresponse()
        if response.status != 200:
            raise BenchmarkError(f"local Ollama returned HTTP {response.status}")
        while True:
            line = response.readline(MAX_EVENT_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_EVENT_BYTES:
                raise BenchmarkError("oversized Ollama stream event")
            events += 1
            if events > MAX_EVENTS:
                raise BenchmarkError("Ollama stream event count exceeded bound")
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError) as exc:
                raise BenchmarkError("invalid Ollama stream JSON") from exc
            if not isinstance(event, dict):
                raise BenchmarkError("Ollama stream event must be a JSON object")
            if "error" in event:
                raise BenchmarkError("Ollama reported an inference error")
            if event.get("response") and first_token_ns is None:
                if not isinstance(event["response"], str):
                    raise BenchmarkError("Ollama token content is not text")
                first_token_ns = time.monotonic_ns()
            if event.get("done") is True:
                final = event
                break
            if "done" in event and event["done"] is not False:
                raise BenchmarkError("Ollama done marker is invalid")
        end = time.monotonic_ns()
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise BenchmarkError("local Ollama inference was unavailable or timed out") from exc
    finally:
        conn.close()

    if final is None or first_token_ns is None:
        raise BenchmarkError("Ollama did not complete with at least one generated token")
    count = _positive_integer(final.get("eval_count"), "eval_count")
    duration = _positive_integer(final.get("eval_duration"), "eval_duration")
    prompt_count = _positive_integer(
        final.get("prompt_eval_count"), "prompt_eval_count", allow_zero=True
    )
    load_ns = _positive_integer(
        final.get("load_duration"), "load_duration", allow_zero=True
    )
    return {
        "ttft_ms": round((first_token_ns - start) / 1e6, 2),
        "wall_ms": round((end - start) / 1e6, 2),
        "generation_tokens_per_second": round(count * 1e9 / duration, 2),
        "generated_tokens": count,
        "prompt_tokens": prompt_count,
        "model_load_ms": round(load_ns / 1e6, 2),
    }


def _percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(len(values) * fraction) - 1)]


def benchmark(*, base_url: str, model: str, warmup: int = 1,
              repetitions: int = 3, num_ctx: int = 8192,
              num_predict: int = 96, timeout: int = 180,
              prompt: str = DEFAULT_PROMPT) -> dict:
    target = local_target(base_url)
    if (not isinstance(model, str) or len(model) > 128 or not model
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in model)):
        raise BenchmarkError("model name must be a bounded, nonempty string")
    if (type(warmup) is not int or not 0 <= warmup <= 3
            or type(repetitions) is not int or not 1 <= repetitions <= 12
            or type(num_ctx) is not int or not 128 <= num_ctx <= 32768
            or type(num_predict) is not int or not 8 <= num_predict <= 512
            or type(timeout) is not int or not 10 <= timeout <= 900
            or not isinstance(prompt, str) or not 1 <= len(prompt) <= 2048):
        raise BenchmarkError("invalid bounded benchmark settings")
    measures = []
    for run in range(warmup + repetitions):
        result = measure_once(
            target, model, num_ctx=num_ctx, num_predict=num_predict,
            prompt=prompt, timeout=timeout,
        )
        if run >= warmup:
            measures.append(result)
    ttft = [float(m["ttft_ms"]) for m in measures]
    wall = [float(m["wall_ms"]) for m in measures]
    tps = [float(m["generation_tokens_per_second"]) for m in measures]
    return {
        "schema": SCHEMA,
        "status": "MEASURED_LOCAL_OLLAMA_ONLY",
        "model": model,
        "endpoint": f"http://{('[' + target[0] + ']') if ':' in target[0] else target[0]}:{target[1]}",
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "warmup_excluded": warmup,
        "repetitions": repetitions,
        "num_ctx": num_ctx,
        "num_predict_limit": num_predict,
        "ttft_ms_p50": round(statistics.median(ttft), 2),
        "ttft_ms_p95_nearest_rank": round(_percentile(ttft, 0.95), 2),
        "wall_ms_p50": round(statistics.median(wall), 2),
        "generation_tps_median": round(statistics.median(tps), 2),
        "runs": measures,
        "modelrig_end_to_end_proven": False,
        "gpu_attribution_proven": False,
        "release_ready": False,
        "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:11435")
    parser.add_argument("--model", required=True)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=96)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = benchmark(
            base_url=args.base_url, model=args.model,
            warmup=args.warmup, repetitions=args.repetitions,
            num_ctx=args.num_ctx, num_predict=args.num_predict,
            timeout=args.timeout,
        )
        if args.output is not None:
            # Writing is opt-in; no secret prompt, completion or remote data
            # is ever included in the report.
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(report, indent=2, sort_keys=True) + chr(10))
    except (BenchmarkError, OSError) as exc:
        print(json.dumps({
            "schema": SCHEMA, "status": "BLOCKED", "reason": str(exc),
            "release_ready": False, "production_activation": False,
        }), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
