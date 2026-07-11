"""Tests for paths.py -- the data-root anchoring that prevents the working-dir
footgun (relative data files splitting/emptying when the worker is launched from
a different folder; the same class of bug that caused the phone 401)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

passed = failed = 0
def check(cond, msg):
    global passed, failed
    if cond: passed += 1; print(f"  PASS: {msg}")
    else: failed += 1; print(f"  FAIL: {msg}")

from app import paths  # noqa: E402

# A relative default must become absolute -- the whole point.
r = paths.resolve("./modelrig-rag.db")
check(os.path.isabs(r), "resolve: a relative default becomes an absolute path")
check(os.path.basename(r) == "modelrig-rag.db", "resolve: basename preserved")
check(os.path.dirname(r) == paths.data_root(), "resolve: anchored under data_root")

# The env override must win verbatim -- backwards compatible with existing setups.
os.environ["KALIV_TEST_DB"] = "/custom/abs/x.db"
check(paths.resolve("./x.db", env="KALIV_TEST_DB") == "/custom/abs/x.db",
      "resolve: env override wins verbatim")
os.environ["KALIV_TEST_DB"] = "relative/still/honoured.db"
check(paths.resolve("./x.db", env="KALIV_TEST_DB") == "relative/still/honoured.db",
      "resolve: an explicit env value is honoured even if relative (caller asked)")
del os.environ["KALIV_TEST_DB"]

# An already-absolute path passes through untouched.
check(paths.resolve("/already/abs.db") == "/already/abs.db",
      "resolve: absolute path untouched")

# KALIV_DATA_DIR relocates the whole root.
with tempfile.TemporaryDirectory() as td:
    os.environ["KALIV_DATA_DIR"] = td
    check(paths.data_root() == td, "data_root: KALIV_DATA_DIR wins")
    check(paths.resolve("./a.db") == os.path.join(td, "a.db"),
          "resolve: files land under KALIV_DATA_DIR")
    del os.environ["KALIV_DATA_DIR"]

# data_root is created if missing.
with tempfile.TemporaryDirectory() as td:
    target = os.path.join(td, "made", "by", "kaliv")
    os.environ["KALIV_DATA_DIR"] = target
    root = paths.data_root()
    check(os.path.isdir(root), "data_root: creates the directory if missing")
    del os.environ["KALIV_DATA_DIR"]

# The three real data files all resolve absolute (the actual footgun sites).
for default, env in [("./modelrig-rag.db", "MODELRIG_DB"),
                     ("./kaliv-audit.db", "KALIV_AUDIT_DB"),
                     ("./kaliv-tools-state.json", "KALIV_TOOLS_STATE")]:
    # ensure no override leaks from the environment for this assertion
    old = os.environ.pop(env, None)
    check(os.path.isabs(paths.resolve(default, env=env)),
          f"resolve: {os.path.basename(default)} is anchored absolute")
    if old is not None: os.environ[env] = old

print(f"\n===== PATHS: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
