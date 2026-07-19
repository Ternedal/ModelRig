"""The freeze check must correctly gate a validation candidate (F-919, F-922).

freeze_check exists so a rig session validates a coherent, CI-green candidate --
not a half-applied tree, not a local-only commit, not a build whose CI is red.
It is only worth anything if its verdicts are right, so its coherence logic is
driven here against synthetic git states in a throwaway repo. The CI-status half
needs the live GitHub API and a token, so it is exercised for its offline
behaviour (no token -> warning, not a crash), not against real CI.

Run: python3 tests/workflow_freeze_check.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "freeze_check", ROOT / "scripts" / "freeze_check.py")
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _make_repo(clean=True, version="1.58.0", with_origin=True):
    """A throwaway git repo with a VERSION file and a scripts/version_tool stub."""
    d = Path(tempfile.mkdtemp(prefix="freeze-"))
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t.t")
    _git(d, "config", "user.name", "t")
    (d / "VERSION").write_text(version + "\n")
    scripts = d / "scripts"
    scripts.mkdir()
    # A version_tool stub whose `check` mirrors the real one's contract: exit 0
    # when consistent. We control consistency via an env the stub reads.
    (scripts / "version_tool.py").write_text(
        "import sys, os\n"
        "sys.exit(0 if os.environ.get('STUB_VT_OK','1')=='1' else 1)\n")
    (d / "freeze_check.py").write_text("# placeholder\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "init")
    if with_origin:
        # A local bare "origin" and a pushed main: the on-main blocker (F-1005
        # upgraded it from a note) must be satisfiable in the harness, and its
        # absence must be testable.
        bare = Path(tempfile.mkdtemp(prefix="freeze-origin-")) / "o.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        _git(d, "remote", "add", "origin", str(bare))
        _git(d, "push", "-q", "origin", "HEAD:main")
        _git(d, "fetch", "-q", "origin")
    if not clean:
        (d / "dirty.txt").write_text("uncommitted\n")
    return d


def _runs(**names):
    """A fake Actions response: names maps workflow -> (status, conclusion)."""
    return {"workflow_runs": [
        {"name": n, "status": st, "conclusion": co}
        for n, (st, co) in names.items()
    ]}


def run_in(repo, token=None, api=None):
    """Run freeze_check.main() as if cwd were `repo`; return exit code + output."""
    import io
    import contextlib
    old_cwd = os.getcwd()
    old_env = dict(os.environ)
    # Point the module's file-relative paths at the throwaway repo by monkey-
    # patching __file__-derived dirname via chdir + a stubbed scripts dir.
    buf = io.StringIO()
    try:
        os.chdir(repo)
        # freeze_check reads VERSION and version_tool relative to its own
        # __file__, so temporarily repoint that at the throwaway scripts dir.
        fc_dir = str(repo / "scripts")
        _orig_dirname = os.path.dirname

        def _patched_dirname(p):
            # the module computes os.path.dirname(__file__); return our stub dir
            if p == fc.__file__:
                return fc_dir
            return _orig_dirname(p)

        os.path.dirname = _patched_dirname
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("GH_TOKEN", None)
        if token:
            os.environ["GITHUB_TOKEN"] = token
        _orig_api = fc._api
        if api is not None:
            fc._api = api
        with contextlib.redirect_stdout(buf):
            code = fc.main()
        return code, buf.getvalue()
    finally:
        fc._api = _orig_api
        os.path.dirname = _orig_dirname
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)


# --- F-1005: no token means NOT FROZEN -- the evidence IS the freeze ---------
_clean = _make_repo(clean=True)
_code, _out = run_in(_clean, token=None)
check(_code == 1,
      "a coherent candidate WITHOUT a token is NOT FROZEN (exit 1) -- FROZEN "
      "declared without exact-head CI evidence is the hollow verdict F-1005 "
      "names")
check("CI status cannot be verified" in _out
      and "FROZEN requires exact-head CI evidence" in _out,
      "and it says plainly what is missing and how to supply it, rather "
      "than silently claiming green")

# --- a dirty working tree is a hard blocker ---------------------------------
_dirty = _make_repo(clean=False)
_code, _out = run_in(_dirty, token=None)
check(_code == 1,
      "an uncommitted working tree is NOT FROZEN (exit 1) -- the candidate must "
      "be exactly the committed state")
check("working tree not clean" in _out,
      "and the reason is legible")

# --- inconsistent version stamps are a hard blocker -------------------------
_badvt = _make_repo(clean=True)
old = dict(os.environ)
try:
    os.environ["STUB_VT_OK"] = "0"  # make the version_tool stub report drift
    _code, _out = run_in(_badvt, token=None)
finally:
    os.environ.clear()
    os.environ.update(old)
check(_code == 1,
      "version stamps that disagree are NOT FROZEN (exit 1) -- a half-bumped "
      "candidate is not coherent")
check("version stamps disagree" in _out,
      "and the reason names the version drift")

# --- the check never mutates the repo ---------------------------------------
_probe = _make_repo(clean=True)
_before = _git(_probe, "rev-parse", "HEAD").stdout.strip()
run_in(_probe, token=None)
_after = _git(_probe, "rev-parse", "HEAD").stdout.strip()
check(_before == _after,
      "freeze_check does not move HEAD or commit anything -- it is read-only")

# --- the green path: token + both workflows verified -> FROZEN ----------------
_ok = _make_repo(clean=True)
_code, _out = run_in(
    _ok, token="tkn",
    api=lambda url, token: _runs(ci=("completed", "success"),
                                 codeql=("completed", "success")))
check(_code == 0 and "FROZEN" in _out,
      "with a token and ci+codeql verified green on this exact head, the "
      "candidate is FROZEN (exit 0)")
check("ci was GREEN" in _out and "codeql was GREEN" in _out,
      "and BOTH workflows are named as verified -- codeql is part of the "
      "evidence now, not just ci")

# --- every degraded CI state blocks ------------------------------------------
for name, api, needle in [
    ("codeql missing", lambda u, t: _runs(ci=("completed", "success")),
     "no codeql run found"),
    ("ci still running", lambda u, t: _runs(ci=("in_progress", None),
                                            codeql=("completed", "success")),
     "still running"),
    ("ci red", lambda u, t: _runs(ci=("completed", "failure"),
                                  codeql=("completed", "success")),
     "did not pass"),
]:
    _r = _make_repo(clean=True)
    _code, _out = run_in(_r, token="tkn", api=api)
    check(_code == 1 and needle in _out,
          f"{name} on the exact head is NOT FROZEN -- waiting or fixing is "
          "the only path to the verdict")

def _boom(url, token):
    import urllib.error
    raise urllib.error.URLError("offline")

_r = _make_repo(clean=True)
_code, _out = run_in(_r, token="tkn", api=_boom)
check(_code == 1 and "could not read CI status" in _out,
      "an unreadable Actions API is NOT FROZEN -- fail closed, never "
      "fail open")

# --- not on origin/main is a BLOCKER now, not a note -------------------------
_local = _make_repo(clean=True, with_origin=False)
_code, _out = run_in(
    _local, token="tkn",
    api=lambda u, t: _runs(ci=("completed", "success"),
                           codeql=("completed", "success")))
check(_code == 1 and "FAIL  candidate commit is not on origin/main" in _out,
      "a local-only candidate is NOT FROZEN even with green CI -- evidence "
      "must point at code others can see (upgraded from a note, F-1005)")

print(f"\n===== FREEZE CHECK: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
