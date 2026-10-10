"""Offline safety and shape tests for loopback-only Ollama microbenchmark."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "scripts" / "ollama_inference_benchmark.py"
spec = importlib.util.spec_from_file_location("ollama_inference_benchmark", FILE)
assert spec and spec.loader
benchmark = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = benchmark
spec.loader.exec_module(benchmark)


class FakeResponse:
    def __init__(self, data, *, status=200):
        self.status = status
        self.lines = iter(
            (json.dumps(event).encode("utf-8") + b"\n")
            if not isinstance(event, bytes) else event
            for event in data
        )

    def readline(self, limit):
        line = next(self.lines, b"")
        return line[:limit]  # Detect max-line overflow through returned bytes.


class FakeConnection:
    calls = []
    events = None
    status = 200

    def __init__(self, host, port, timeout):
        self.calls.append(("connect", host, port, timeout))
        self.host, self.port = host, port

    def request(self, verb, path, body, headers):
        self.calls.append(("request", verb, path, json.loads(body)))
        assert verb == "POST" and path == "/api/generate"
        assert headers["Content-Type"] == "application/json"

    def getresponse(self):
        return FakeResponse(self.events, status=self.status)

    def close(self):
        self.calls.append(("close",))


SUCCESS = [
    {"model": "gemma4:26b", "response": "Hej", "done": False},
    {"model": "gemma4:26b", "response": "!", "done": False},
    {
        "model": "gemma4:26b", "done": True,
        "eval_count": 30, "eval_duration": 1_500_000_000,
        "prompt_eval_count": 15, "load_duration": 400_000_000,
    },
]


def reject(fn, phrase):
    try:
        fn()
    except benchmark.BenchmarkError as exc:
        assert phrase in str(exc), (phrase, str(exc))
    else:
        raise AssertionError("unsafe Ollama benchmark input unexpectedly passed")


for url in (
    "http://localhost:11435", "https://127.0.0.1:11435",
    "http://10.0.0.1:11435", "http://127.0.0.1:11435/api/tags",
    "http://127.0.0.1:11435?x=y", "http://evil@127.0.0.1:11435",
    "http://127.0.0.1:0", "http://127.0.0.1:99999",
    "http://127.0.0.1:11435/#frag", "file:///etc/passwd",
):
    reject(lambda: benchmark.local_target(url), "loopback" if "99999" not in url else "invalid")

assert benchmark.local_target("http://127.0.0.1:11435") == ("127.0.0.1", 11435)
assert benchmark.local_target("http://[::1]:11435") == ("::1", 11435)
assert benchmark.local_target("http://127.0.0.1:11435/") == ("127.0.0.1", 11435)

with patch.object(benchmark.http.client, "HTTPConnection", FakeConnection):
    FakeConnection.calls = []
    FakeConnection.events = SUCCESS
    FakeConnection.status = 200
    result = benchmark.benchmark(base_url="http://127.0.0.1:11435",
                                 model="gemma4:26b", warmup=1, repetitions=3)
    assert len([x for x in FakeConnection.calls if x[0] == "request"]) == 4
    assert len([x for x in FakeConnection.calls if x[0] == "close"]) == 4
    assert result["generation_tps_median"] == 20.0
    assert result["repetitions"] == 3 and len(result["runs"]) == 3
    assert result["ttft_ms_p95_nearest_rank"] >= result["ttft_ms_p50"] >= 0
    assert all(run["model_load_ms"] == 400.0 for run in result["runs"])
    assert result["endpoint"] == "http://127.0.0.1:11435"
    assert result["prompt_sha256"] == hashlib.sha256(
        benchmark.DEFAULT_PROMPT.encode("utf-8")
    ).hexdigest()
    for prop in ("modelrig_end_to_end_proven", "gpu_attribution_proven",
                 "release_ready", "production_activation"):
        assert result[prop] is False
    assert "response" not in json.dumps(result) and "prompt" not in result

    for unsafe, marker in (
        ([{"done": True, "eval_count": 2, "eval_duration": 1,
           "prompt_eval_count": 0, "load_duration": 0}], "at least one"),
        ([{"response": "A", "done": False}], "did not complete"),
        ([{"response": "A", "done": 1}], "done marker"),
        ([{"error": "secret failure"}], "inference error"),
        ([{"response": 123, "done": False}], "not text"),
        (SUCCESS[:-1] + [{"done": True, "eval_count": True,
                            "eval_duration": 12, "prompt_eval_count": 12,
                            "load_duration": 0}], "eval_count"),
        ([b"{" + b"x" * (benchmark.MAX_EVENT_BYTES + 1) + b"}\n"],
         "oversized"),
    ):
        FakeConnection.events = unsafe
        reject(lambda: benchmark.measure_once(
            ("127.0.0.1", 11435), "gemma4:26b",
            num_ctx=8192, num_predict=96,
            prompt=benchmark.DEFAULT_PROMPT, timeout=120,
        ), marker)
    # An event stream that survives socket read deadlines by trickling bytes
    # must still stop at the absolute end-to-end measurement deadline.
    FakeConnection.events = SUCCESS
    with patch.object(benchmark.time, "monotonic_ns",
                      side_effect=[0, 11_000_000_000]):
        reject(lambda: benchmark.measure_once(
            ("127.0.0.1", 11435), "gemma4:26b",
            num_ctx=8192, num_predict=96,
            prompt=benchmark.DEFAULT_PROMPT, timeout=10,
        ), "overall timeout")
    FakeConnection.events = SUCCESS
    FakeConnection.status = 302
    reject(lambda: benchmark.measure_once(
        ("127.0.0.1", 11435), "gemma4:26b",
        num_ctx=8192, num_predict=96,
        prompt=benchmark.DEFAULT_PROMPT, timeout=120,
    ), "HTTP 302")
    FakeConnection.status = 200

    for bad in ("bad\nheader", "", "\t"):
        reject(lambda: benchmark.benchmark(
            base_url="http://127.0.0.1:11435", model=bad,
        ), "model name")
    for altered in (
        {"warmup": 4}, {"repetitions": 0}, {"num_ctx": 64},
        {"num_predict": 1024}, {"timeout": 0},
    ):
        reject(lambda: benchmark.benchmark(
            base_url="http://127.0.0.1:11435", model="gemma4:26b", **altered,
        ), "settings")

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "report.json"
        assert benchmark.main(["--model", "gemma4:26b", "--warmup", "0",
                               "--repetitions", "1", "--output", str(path)]) == 0
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["release_ready"] is False and saved["repetitions"] == 1
        assert saved["schema"] == benchmark.SCHEMA
        assert path.read_bytes().endswith(b"\n")
        # Never overwrite even when output filename already exists.
        assert benchmark.main(["--model", "gemma4:26b", "--warmup", "0",
                               "--repetitions", "1", "--output", str(path)]) == 2

print("PASS: local Ollama inference benchmark; no external network or release authority")
