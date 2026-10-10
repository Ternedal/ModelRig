"""Pure offline and negative tests for localhost-only Ollama performance probe."""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ollama_local_perf_probe.py"
spec = importlib.util.spec_from_file_location("local_perf_probe", SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def rejected(action, message: str):
    try:
        action()
    except probe.ProbeError as exc:
        assert message in str(exc), (message, str(exc))
    else:
        raise AssertionError(f"unsafe probe accepted: {message}")


assert probe._ensure_loopback("http://127.0.0.1:11435") == (
    "http://127.0.0.1:11435"
)
assert probe._ensure_loopback("http://[::1]:11435") == (
    "http://[::1]:11435"
)
for candidate in (
    "https://127.0.0.1:11435",
    "http://localhost:11435",
    "http://10.0.0.1:11435",
    "http://127.0.0.2:11435",
    "http://127.0.0.1:11435/api/tags",
    "http://127.0.0.1:11435/?token=secret",
    "http://127.0.0.1:11435#fragment",
    "http://admin:pass@127.0.0.1:11435",
    "http://127.0.0.1@evil.example:11435",
    "http://127.0.0.1",
    "file:///etc/passwd",
):
    rejected(lambda url=candidate: probe._ensure_loopback(url), "loopback")

rejected(lambda: probe._metrics({"done": False}, 1, 1), "incomplete")
rejected(lambda: probe._metrics({"done": True}, 1, 1), "numeric")
for dangerous in (True, -1, float("nan"), float("inf")):
    rejected(
        lambda v=dangerous: probe._nonnegative_number(v, "token count"),
        "numeric" if dangerous is True else "finite",
    )

sample = {
    "done": True,
    "load_duration": 1_000_000_000,
    "prompt_eval_count": 30,
    "prompt_eval_duration": 2_000_000_000,
    "eval_count": 64,
    "eval_duration": 4_000_000_000,
    "message": {"role": "assistant", "content": "PRIVATE CONTENT NEVER EXPORTED"},
}
results = []
def fake_request(base, route, *, body, timeout):
    assert base == "http://127.0.0.1:11435"
    assert timeout == 30
    if route == "/api/tags":
        assert body is None
        return {"models": [{"name": "fixture:7b"}]}
    if route == "/api/ps":
        assert body is None
        return {"models": [{"name": "fixture:7b", "size_vram": 4_000_000_000}]}
    assert route == "/api/chat"
    assert body["model"] == "fixture:7b"
    assert body["stream"] is False
    assert body["options"]["num_predict"] == 32
    assert body["options"]["num_ctx"] == 1024
    assert len(body["messages"]) == 1
    results.append(json.loads(json.dumps(body)))
    return sample

with patch.object(probe, "_request_json", side_effect=fake_request):
    report = probe.measure(
        "http://127.0.0.1:11435", "fixture:7b",
        runs=3, num_predict=32, num_ctx=1024, timeout=30,
    )
assert len(results) == 3
assert report["authority"] == "DIAGNOSTIC_ONLY_NOT_RELEASE_EVIDENCE"
assert report["loaded_before"]["loaded"] is True
assert report["loaded_after"]["reported_vram_bytes"] == 4_000_000_000
assert report["warm_decode_tps_median"] == 16.0
assert all(x["decode_tokens_per_second"] == 16.0 for x in report["measurements"])
assert "PRIVATE CONTENT" not in json.dumps(report)
assert report["measurements"][0]["load_seconds"] == 1.0
assert report["measurements"][0]["prompt_seconds"] == 2.0
assert report["measurements"][0]["decode_seconds"] == 4.0

def uninstalled(base, route, *, body, timeout):
    assert route == "/api/tags", "MUST NOT invoke generation or pull"
    return {"models": []}

with patch.object(probe, "_request_json", side_effect=uninstalled):
    rejected(
        lambda: probe.measure("http://127.0.0.1:11435", "missing:7b"),
        "not installed",
    )
for kwargs in (
    {"runs": 0},
    {"runs": 6},
    {"num_predict": 4096},
    {"num_ctx": 131072},
    {"timeout": 9999},
):
    with patch.object(probe, "_request_json") as called:
        rejected(
            lambda kw=kwargs: probe.measure(
                "http://127.0.0.1:11435", "fixture:7b", **kw
            ),
            "bounded",
        )
        called.assert_not_called()

print("Loopback-only Ollama read-only performance probe contract PASS")
