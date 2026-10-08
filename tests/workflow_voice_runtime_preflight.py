"""Contract tests for the read-only, live-worker voice preflight."""
from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "kaliv_voice_runtime_preflight",
    Path(__file__).resolve().parents[1] / "scripts" / "voice_runtime_preflight.py",
)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class Response:
    def __init__(self, value: bytes, status: int = 200):
        self.value = value
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int):
        return self.value[:limit]


def assert_restricted_loopback() -> None:
    assert tool.worker_base("http://127.0.0.1:8099") == "http://127.0.0.1:8099"
    assert tool.worker_base("http://[::1]:8099") == "http://[::1]:8099"
    assert tool.worker_base("http://localhost:8099/") == "http://localhost:8099"
    for unsafe in (
        "https://127.0.0.1:8099",
        "http://example.org:8099",
        "http://192.168.0.20:8099",
        "http://127.0.0.1",
        "http://user:secret@127.0.0.1:8099",
        "http://127.0.0.1:8099/admin",
        "http://127.0.0.1:8099?x=1",
        "http://127.0.0.1:8099#fragment",
        "http://127.0.0.1:99999",
    ):
        try:
            tool.worker_base(unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe worker URL accepted: {unsafe}")


def assert_remote_contract() -> None:
    def opener(request, timeout: int):
        assert request.full_url == "http://127.0.0.1:8099/voice/asr/status"
        assert request.get_method() == "GET"
        assert timeout == 4
        return Response(b'{"available":true,"device":"cuda"}')

    with patch.object(tool.urllib.request, "urlopen", opener):
        assert tool.query_worker(
            "http://127.0.0.1:8099", "/voice/asr/status"
        )["available"] is True

    for invalid in (b'{"available":"yes"}', b"[]", b"{", b'{"ok":true}'):
        with patch.object(tool.urllib.request, "urlopen", lambda *_args, **_kw: Response(invalid)):
            try:
                tool.query_worker("http://127.0.0.1:8099", "/voice/asr/status")
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid contract accepted: {invalid!r}")

    oversized = b"x" * (tool.MAX_STATUS_BYTES + 1)
    with patch.object(tool.urllib.request, "urlopen", lambda *_args, **_kw: Response(oversized)):
        try:
            tool.query_worker("http://127.0.0.1:8099", "/voice/asr/status")
        except ValueError as exc:
            assert "size limit" in str(exc)
        else:
            raise AssertionError("oversized status accepted")


def assert_runtime_is_authority() -> None:
    # Different local interpreter: remote-ready VoiceRig/Piper remains valid.
    result = tool.assess(
        asr={"available": True}, tts={"available": True},
        local_asr=False, local_piper=False, error=None, executable="python",
    )
    assert result["ready_for_live_voice_smoke"] is True
    assert result["release_gate_satisfied"] is False
    assert result["production_activation"] is False

    result = tool.assess(
        asr={"available": False}, tts={"available": True},
        local_asr=True, local_piper=False, error=None, executable="python",
    )
    assert result["ready_for_live_voice_smoke"] is False
    assert any("interpreter" in note for note in result["next_steps"])

    result = tool.assess(
        asr=None, tts=None, local_asr=False, local_piper=False,
        error="worker unreachable", executable="python",
    )
    assert result["ready_for_live_voice_smoke"] is False
    assert result["worker_reachable"] is False
    assert result["release_gate_satisfied"] is False


def assert_cli_contract() -> None:
    with patch.object(tool, "query_worker", side_effect=[
        {"available": False}, {"available": True}
    ]), patch.object(tool, "local_package", return_value=False):
        output = io.StringIO()
        with redirect_stdout(output):
            rc = tool.main(["--json"])
        result = json.loads(output.getvalue())
        assert rc == 1
        assert result["worker_asr_available"] is False
        assert result["worker_tts_available"] is True
        assert any("pip install faster-whisper" in note for note in result["next_steps"])
        assert result["production_activation"] is False


def main() -> None:
    assert_restricted_loopback()
    assert_remote_contract()
    assert_runtime_is_authority()
    assert_cli_contract()
    print("voice runtime preflight: loopback/contract/runtime/CLI gates PASS")


if __name__ == "__main__":
    main()
