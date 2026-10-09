"""Fail-closed, network-free tests of the opt-in V1 rig smoke."""
from __future__ import annotations
import importlib.util
import hashlib
import json
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "kaliv_v1_rig_smoke",
    Path(__file__).resolve().parents[1] / "scripts" / "kaliv_v1_rig_smoke.py")
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
SHA = "0b2ff455116f4f28a1a41704d9cb81503f17d2df"
ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_bytes()
VERSION_BLOB = hashlib.sha1(b"blob " + str(len(VERSION)).encode("ascii") + b"\0" + VERSION).hexdigest()
TREE_LINE = ("100644 blob " + VERSION_BLOB + "\tVERSION\0").encode("utf-8")


class Response:
    status = 200
    def __init__(self, value):
        self.data = json.dumps(value).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, size):
        return self.data[:size]


def opener(req):
    assert req.get_method() == "GET"
    assert req.full_url.startswith(("http://127.0.0.1:8080/", "http://127.0.0.1:8099/"))
    if req.full_url.endswith("/healthz"):
        return Response({"status": "ok", "service":
                         "modelrig-server" if ":8080/" in req.full_url else "modelrig-worker"})
    if req.full_url.endswith(("/voice/asr/status", "/voice/tts/status")):
        return Response({"available": True})
    raise AssertionError("unexpected route")


def git_ok(args, **_):
    assert "--no-replace-objects" in args
    assert "core.fsmonitor=false" in args
    if "--show-toplevel" in args:
        root = Path(args[args.index("-C") + 1]).resolve()
        return SimpleNamespace(returncode=0, stdout=str(root) + "\n")
    if "rev-parse" in args:
        return SimpleNamespace(returncode=0, stdout=SHA + "\n")
    if "ls-tree" in args:
        assert "-r" in args and "-z" in args
        return SimpleNamespace(returncode=0, stdout=TREE_LINE)
    assert "ls-files" in args and "-z" in args
    if "--stage" in args:
        return SimpleNamespace(
            returncode=0,
            stdout=("100644 " + VERSION_BLOB + " 0\tVERSION\0").encode("utf-8"),
        )
    assert "--others" in args and "--exclude-standard" in args
    return SimpleNamespace(returncode=0, stdout=b"")


def run():
    return tool.smoke(root=ROOT, expected_sha=SHA,
                      backend_url="http://127.0.0.1:8080",
                      worker_url="http://127.0.0.1:8099")


with patch.object(tool.voice, "_open_worker_status", opener), patch.object(
    tool.subprocess, "run", side_effect=git_ok):
    report = run()
assert report["source"]["status"] == "PASS"
assert report["source"]["tracked_bytes_match"] is True
assert report["ready_for_real_voice_fixture_tests"] is True
assert all(v["status"] == "PASS" for v in report["probes"].values())
assert all(v == "NOT_TESTED" for v in report["physical_gates"].values())
assert report["release_gate_satisfied"] is False
assert report["production_activation"] is False

for unsafe in ("https://127.0.0.1:8099", "http://example.org:8099",
               "http://127.0.0.1:8099/extra",
               "http://user:password@127.0.0.1:8099"):
    try:
        tool.smoke(root=ROOT, expected_sha=SHA,
                   backend_url="http://127.0.0.1:8080", worker_url=unsafe)
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe remote/redirect-capable URL accepted")

for invalid in ("main", SHA.upper(), "a" * 39, SHA + "0"):
    try:
        tool.checkout_identity(ROOT, invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("mutable/noncanonical SHA accepted")

with patch.object(tool.subprocess, "run", side_effect=git_ok):
    assert tool.checkout_identity(ROOT, "f" * 40)["status"] == "BLOCKED"
def git_untracked(args, **kwargs):
    if "ls-files" in args and "--others" in args:
        return SimpleNamespace(returncode=0, stdout=b"unknown-file.txt\0")
    return git_ok(args, **kwargs)

with patch.object(tool.subprocess, "run", side_effect=git_untracked):
    assert tool.checkout_identity(ROOT, SHA)["status"] == "BLOCKED"


def no_asr(req):
    if req.full_url.endswith("/voice/asr/status"):
        return Response({"available": False})
    return opener(req)

with patch.object(tool.voice, "_open_worker_status", no_asr), patch.object(
    tool.subprocess, "run", side_effect=git_ok):
    report = run()
assert report["probes"]["asr"] == {"status": "BLOCKED", "available": False}
assert report["ready_for_real_voice_fixture_tests"] is False


def bad_backend(req):
    if ":8080/" in req.full_url:
        return Response({"status": "ok", "service": "unknown"})
    return opener(req)

with patch.object(tool.voice, "_open_worker_status", bad_backend), patch.object(
    tool.subprocess, "run", side_effect=git_ok):
    report = run()
assert report["probes"]["backend"]["status"] == "BLOCKED"
assert report["ready_for_real_voice_fixture_tests"] is False
# Docs must bind against independently reviewed release evidence, NEVER self-authorize
# a clean but wrong checkout by reading the expected SHA from its own HEAD.
docs = code_of(Path(__file__).resolve().parents[1] / "docs" / "KALIV_V1_RIG_SMOKE.md")
assert "independently reviewed" in docs
assert "$expectedModelRigSha = (git rev-parse HEAD)" not in docs
assert "--expected-modelrig-sha $expectedModelRigSha" in docs
assert "git --no-replace-objects" in docs
# Git index flags can hide changed source. An empty status is not proof
# that the actual disk bytes match the exact HEAD tree.
with tempfile.TemporaryDirectory() as td:
    path = Path(td)
    (path / "VERSION").write_bytes(b"hidden mutation")
    with patch.object(tool.subprocess, "run", side_effect=git_ok):
        verdict = tool.checkout_identity(path, SHA)
    assert verdict["matches_expected"] is True
    assert verdict["clean"] is False
    assert verdict["tracked_bytes_match"] is False
    assert verdict["status"] == "BLOCKED"

def git_empty_tree(args, **kwargs):
    if "ls-tree" in args:
        return SimpleNamespace(returncode=0, stdout=b"")
    return git_ok(args, **kwargs)

with patch.object(tool.subprocess, "run", side_effect=git_empty_tree):
    assert tool.checkout_identity(ROOT, SHA)["status"] == "BLOCKED"

# A child directory is not the target Git repository root.
def git_wrong_top(args, **kwargs):
    if "--show-toplevel" in args:
        return SimpleNamespace(returncode=0, stdout=str(ROOT.parent) + "\n")
    return git_ok(args, **kwargs)

with patch.object(tool.subprocess, "run", side_effect=git_wrong_top):
    assert tool.checkout_identity(ROOT, SHA)["status"] == "BLOCKED"

# The inspected checkout may change after the first proof but before HTTP GETs.
with patch.object(tool, "checkout_identity", side_effect=[
    {"status": "PASS"}, {"status": "BLOCKED"}
]), patch.object(tool.voice, "_open_worker_status", opener):
    assert run()["ready_for_real_voice_fixture_tests"] is False

# An unsafe Windows reparse/junction path must be rejected before Git probes.
with patch.object(tool, "safe_root", return_value=False):
    with patch.object(tool.subprocess, "run", side_effect=AssertionError("no Git allowed")):
        assert tool.checkout_identity(ROOT, SHA)["status"] == "BLOCKED"


# A standalone PR worktree must be able to inspect the frozen V1 checkout
# separately, without copying an untracked script into its clean Git tree.
with tempfile.TemporaryDirectory() as temp_dir:
    target = Path(temp_dir).resolve()
    result = {"ready_for_real_voice_fixture_tests": True,
              "release_gate_satisfied": False, "production_activation": False}
    with patch.object(tool, "smoke", return_value=result) as run_probe:
        with redirect_stdout(StringIO()):
            assert tool.main(["--expected-modelrig-sha", SHA,
                              "--checkout-root", str(target)]) == 0
    assert run_probe.call_args.kwargs["root"] == target
    assert run_probe.call_args.kwargs["expected_sha"] == SHA
    with patch.object(tool, "smoke", side_effect=AssertionError("should not probe")):
        try:
            with redirect_stdout(StringIO()):
                tool.main(["--expected-modelrig-sha", SHA,
                           "--checkout-root", "relative/path"])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("relative checkout root accepted")
assert "--checkout-root" in docs
print("kaliv V1 rig smoke contract PASS")
