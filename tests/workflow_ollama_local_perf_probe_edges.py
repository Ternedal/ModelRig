"""Additional offline edge-case coverage for Ollama latency diagnostics.

No network, GPU, Ollama process, or user files are accessed.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / "scripts" / "ollama_local_perf_probe.py"
spec = importlib.util.spec_from_file_location("modelrig_perf_probe_edge", script)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def must_refuse(fn, message):
    try:
        fn()
    except probe.ProbeError as exc:
        assert message in str(exc), str(exc)
    else:
        raise AssertionError(f"Expected refusal: {message}")


# Redirects must not silently change the loopback destination.
must_refuse(
    lambda: probe._NoRedirect().redirect_request(
        None, None, 302, "Moved", {}, "http://example.org/"
    ),
    "redirected",
)

# Incomplete, non-integral, or inconsistent timing data cannot count as success.
valid = dict(
    done=True, load_duration=0, prompt_eval_count=1,
    prompt_eval_duration=1_000_000, eval_count=1,
    eval_duration=1_000_000,
)
for replacement, expected in (
    ({"eval_count": 1.5}, "whole numbers"),
    ({"eval_duration": 0}, "duration"),
    ({"prompt_eval_duration": 0}, "duration"),
    ({"load_duration": -1}, "finite"),
):
    must_refuse(lambda patch_values=replacement: probe._metrics(
        {**valid, **patch_values}, 0.01, 1
    ), expected)

must_refuse(lambda: probe._loaded_size({"models": None}, "fixture:7b"), "malformed")
must_refuse(lambda: probe._loaded_size({"models": [None]}, "fixture:7b"), "invalid")

# Verify no model response content is included in successful metric extraction.
sample = {**valid, "message": {"content": "PRIVATE NEVER SERIALIZE"}}
metrics = probe._metrics(sample, 0.1, 1)
assert "PRIVATE NEVER SERIALIZE" not in json.dumps(metrics)

# The request path must reject unrecognized API routes before attempting I/O.
must_refuse(
    lambda: probe._request_json("http://127.0.0.1:11435", "/api/pull",
                                body=None, timeout=10),
    "Unexpected endpoint",
)
print("Ollama local performance probe edge-case contract PASS")
