#!/usr/bin/env python3
"""Read-only voice readiness check against the ACTUAL running ModelRig worker.

Does not load a model, install packages, change config, write evidence or qualify
a release. Run with the same Python interpreter used by the worker, if possible.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import importlib.util
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_STATUS_BYTES = 16 * 1024
ENDPOINTS = {"asr": "/voice/asr/status", "tts": "/voice/tts/status"}


def worker_base(url: str) -> str:
    """Refuse network/proxy/auth surprises: this tool probes loopback only."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query or parsed.fragment
    ):
        raise ValueError("worker URL must be plain HTTP loopback without credentials or path")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid worker port") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("worker URL requires an explicit valid port")
    return url.rstrip("/")


def local_package(module: str) -> bool:
    """Inspect only this interpreter; never import CUDA/voice or load a model."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, AttributeError):
        return False


class _NoWorkerRedirect(urllib.request.HTTPRedirectHandler):
    """A loopback-only probe must not follow a worker-supplied Location header."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_worker_status(request: urllib.request.Request):
    """Ignore proxy environment and block redirects, including to other hosts."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoWorkerRedirect(),
    )
    return opener.open(request, timeout=4)


def query_worker(base: str, path: str) -> dict:
    request = urllib.request.Request(
        base + path, method="GET", headers={"Accept": "application/json"}
    )
    try:
        with _open_worker_status(request) as response:
            if response.status != 200:
                raise ValueError(f"worker returned HTTP {response.status}")
            raw = response.read(MAX_STATUS_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"worker returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("worker is unreachable on the specified loopback port") from None
    if len(raw) > MAX_STATUS_BYTES:
        raise ValueError("worker status response exceeds size limit")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("worker returned invalid JSON") from None
    if not isinstance(payload, dict) or type(payload.get("available")) is not bool:
        raise ValueError("worker returned an invalid voice availability contract")
    return payload


def assess(*, asr: dict | None, tts: dict | None, local_asr: bool,
           local_piper: bool, error: str | None, executable: str) -> dict:
    # The RUNNING worker is authority. A local package check is diagnostic only:
    # the operator may have started this script from a different virtualenv.
    asr_ok = asr is not None and asr["available"] is True
    tts_ok = tts is not None and tts["available"] is True
    guidance: list[str] = []
    if error:
        guidance.append("Check that the worker is listening on 127.0.0.1:8099 (or pass --worker-url).")
    else:
        if not asr_ok:
            if local_asr:
                guidance.append(
                    "ASR exists in the inspected Python, but NOT the running worker. "
                    "Check the worker PID/interpreter and restart only that worker after verifying its environment."
                )
            else:
                guidance.append(
                    f'Install ASR in the WORKER virtualenv (not another Python): '
                    f'"{executable}" -m pip install faster-whisper'
                )
        if not tts_ok:
            if local_piper:
                guidance.append(
                    "Piper imports locally but running worker TTS is unavailable; "
                    "check worker interpreter, VoiceRig selection and voice model configuration."
                )
            else:
                guidance.append(
                    f'For a Piper fallback, in the WORKER virtualenv: '
                    f'"{executable}" -m pip install piper-tts'
                )
                guidance.append(
                    "If using VoiceRig instead of Piper, verify its selected provider and running sidecar."
                )
        if asr_ok and tts_ok:
            guidance.append(
                "Dependencies are visible in the running worker. Next: run a REAL "
                "WAV transcription and voice baseline; this probe never loads ASR/TTS models."
            )
    return {
        "schema": "kaliv-voice-runtime-preflight/v1",
        "worker_reachable": error is None,
        "worker_error": error,
        "worker_asr_available": asr_ok,
        "worker_tts_available": tts_ok,
        "inspected_python": executable,
        "inspected_python_has_faster_whisper": local_asr,
        "inspected_python_has_piper": local_piper,
        "ready_for_live_voice_smoke": error is None and asr_ok and tts_ok,
        "release_gate_satisfied": False,
        "production_activation": False,
        "next_steps": guidance,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-url", default="http://127.0.0.1:8099")
    parser.add_argument("--json", action="store_true", help="print a machine-readable report")
    args = parser.parse_args(argv)
    try:
        base = worker_base(args.worker_url)
    except ValueError as exc:
        parser.error(str(exc))

    asr = tts = None
    error = None
    try:
        asr = query_worker(base, ENDPOINTS["asr"])
        tts = query_worker(base, ENDPOINTS["tts"])
    except ValueError as exc:
        error = str(exc)

    verdict = assess(
        asr=asr, tts=tts, local_asr=local_package("faster_whisper"),
        local_piper=local_package("piper"), error=error,
        executable=sys.executable,
    )
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        print("Kaliv voice runtime preflight — READ ONLY / NOT a release PASS")
        print(f"Inspected Python: {verdict['inspected_python']}")
        print(f"Worker reachable: {verdict['worker_reachable']}")
        print(f"Running ASR available: {verdict['worker_asr_available']}")
        print(f"Running TTS available: {verdict['worker_tts_available']}")
        for step in verdict["next_steps"]:
            print(" - " + step)
    return 0 if verdict["ready_for_live_voice_smoke"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
