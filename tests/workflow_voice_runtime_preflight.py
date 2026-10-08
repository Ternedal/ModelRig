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
    def opener(request):
        assert request.full_url == "http://127.0.0.1:8099/voice/asr/status"
        assert request.get_method() == "GET"
        return Response(b'{"available":true,"device":"cuda"}')

    with patch.object(tool, "_open_worker_status", opener):
        assert tool.query_worker(
            "http://127.0.0.1:8099", "/voice/asr/status"
        )["available"] is True

    for invalid in (b'{"available":"yes"}', b"[]", b"{", b'{"ok":true}'):
        with patch.object(tool, "_open_worker_status", lambda *_args, **_kw: Response(invalid)):
            try:
                tool.query_worker("http://127.0.0.1:8099", "/voice/asr/status")
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid contract accepted: {invalid!r}")

    oversized = b"x" * (tool.MAX_STATUS_BYTES + 1)
    with patch.object(tool, "_open_worker_status", lambda *_args, **_kw: Response(oversized)):
        try:
            tool.query_worker("http://127.0.0.1:8099", "/voice/asr/status")
        except ValueError as exc:
            assert "size limit" in str(exc)
        else:
            raise AssertionError("oversized status accepted")



def assert_proxy_and_redirect_isolation() -> None:
    """No proxy inheritance; deny even a redirect pointing to localhost."""
    from unittest.mock import Mock

    created = []
    expected = Response(b'{"available":true}')
    fake_opener = Mock()
    fake_opener.open.return_value = expected

    def fake_build_opener(*handlers):
        created.extend(handlers)
        return fake_opener

    req = tool.urllib.request.Request("http://127.0.0.1:8099/voice/asr/status")
    with patch.object(tool.urllib.request, "build_opener", fake_build_opener):
        assert tool._open_worker_status(req) is expected

    proxy = [h for h in created if isinstance(h, tool.urllib.request.ProxyHandler)]
    redirect = [h for h in created if isinstance(h, tool._NoWorkerRedirect)]
    assert len(proxy) == 1, "loopback probe must explicitly disable proxies"
    assert proxy[0].proxies == {}, "proxy handler must ignore HTTP_PROXY"
    assert len(redirect) == 1, "worker status probe must disable redirect following"
    assert redirect[0].redirect_request(req, None, 302, "redirect", {}, "https://remote.invalid/") is None
    assert redirect[0].redirect_request(req, None, 307, "redirect", {}, "http://127.0.0.1:8099/elsewhere") is None
    fake_opener.open.assert_called_once_with(req, timeout=4)


def assert_runtime_is_authority() -> None:
    # Different local interpreter: remote-ready VoiceRig/Piper remains valid.
    result = tool.assess(
        asr={"available": True}, tts={"available": True},
        local_asr=False, local_piper=False, errors={}, executable="python",
    )
    assert result["ready_for_live_voice_smoke"] is True
    assert result["release_gate_satisfied"] is False
    assert result["production_activation"] is False

    result = tool.assess(
        asr={"available": False}, tts={"available": True},
        local_asr=True, local_piper=False, errors={}, executable="python",
    )
    assert result["ready_for_live_voice_smoke"] is False
    assert any("interpreter" in note for note in result["next_steps"])

    result = tool.assess(
        asr=None, tts=None, local_asr=False, local_piper=False,
        errors={"asr": "worker unreachable", "tts": "worker unreachable"}, executable="python",
    )
    assert result["ready_for_live_voice_smoke"] is False
    assert result["worker_reachable"] is False
    assert result["release_gate_satisfied"] is False



def assert_partial_probe_failure_is_not_total_worker_outage() -> None:
    """A healthy ASR endpoint must survive a failing TTS status route."""
    partial = tool.assess(
        asr={"available": True}, tts=None,
        local_asr=False, local_piper=False,
        errors={"tts": "worker returned HTTP 503"},
        executable="python",
    )
    assert partial["worker_reachable"] is True
    assert partial["worker_asr_available"] is True
    assert partial["worker_tts_available"] is False
    assert partial["worker_asr_probe_error"] is None
    assert partial["worker_tts_probe_error"] == "worker returned HTTP 503"
    assert partial["ready_for_live_voice_smoke"] is False
    assert partial["release_gate_satisfied"] is False
    assert not any("pip install" in step for step in partial["next_steps"])

    # Both status routes must be queried, even when the first one fails.
    def checker(base, path):
        if path == tool.ENDPOINTS["asr"]:
            raise ValueError("worker returned HTTP 401")
        return {"available": True}
    with patch.object(tool, "query_worker", checker), patch.object(
        tool, "local_package", return_value=False
    ):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = tool.main(["--json"])
        report = json.loads(stdout.getvalue())
    assert status == 1
    assert report["worker_reachable"] is True
    assert report["worker_asr_probe_error"] == "worker returned HTTP 401"
    assert report["worker_tts_available"] is True
    assert not any("pip install faster-whisper" in s for s in report["next_steps"])



def assert_malformed_http_status_is_isolated() -> None:
    """Real BadStatusLine exception must not abort JSON or hide the TTS probe."""
    import http.client

    with patch.object(
        tool, "_open_worker_status",
        side_effect=[
            http.client.BadStatusLine("NOT_HTTP\\r\\n"),
            Response(b'{"available":true,"voice":"local"}'),
        ],
    ), patch.object(tool, "local_package", return_value=False):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = tool.main(["--json"])

    report = json.loads(output.getvalue())
    assert exit_code == 1
    assert report["worker_reachable"] is True
    assert report["worker_asr_available"] is False
    assert report["worker_tts_available"] is True
    assert report["worker_asr_probe_error"] == "worker returned a malformed HTTP response"
    assert report["worker_tts_probe_error"] is None
    assert report["ready_for_live_voice_smoke"] is False
    assert report["release_gate_satisfied"] is False
    assert report["production_activation"] is False
    assert not any("pip install faster-whisper" in note for note in report["next_steps"])


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
    assert_proxy_and_redirect_isolation()
    assert_runtime_is_authority()
    assert_partial_probe_failure_is_not_total_worker_outage()
    assert_malformed_http_status_is_isolated()
    assert_cli_contract()
    print("voice runtime preflight: loopback/proxy/redirect/contract/runtime/CLI PASS")


if __name__ == "__main__":
    main()
