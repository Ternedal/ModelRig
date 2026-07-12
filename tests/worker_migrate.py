"""Tests for migrate_data.py -- must be safe (dry-run default, never clobber a
newer file, verify before removing)."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

passed = failed = 0
def check(cond, msg):
    global passed, failed
    if cond: passed += 1; print(f"  PASS: {msg}")
    else: failed += 1; print(f"  FAIL: {msg}")

from app import migrate_data as M, paths  # noqa: E402

with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as old:
    os.environ["KALIV_DATA_DIR"] = root
    # plant an old data file in a fake previous working dir
    src = os.path.join(old, "modelrig-rag.db")
    with open(src, "w") as f:
        f.write("OLD-INDEX-DATA")

    # monkeypatch candidate dirs to include our fake old dir
    M._candidate_dirs = lambda: [old]

    hits = M.find()
    check(any(s == src for s, _ in hits), "find: locates a data file in an old dir")

    # dry run must NOT move anything
    M.run(apply=False, keep=False)
    check(os.path.isfile(src), "dry-run: original left untouched")
    check(not os.path.exists(os.path.join(root, "modelrig-rag.db")), "dry-run: nothing written to root")

    # apply (move)
    M.run(apply=True, keep=False)
    dst = os.path.join(root, "modelrig-rag.db")
    check(os.path.isfile(dst), "apply: file moved into root")
    check(open(dst).read() == "OLD-INDEX-DATA", "apply: contents preserved")
    check(not os.path.isfile(src), "apply(move): original removed")

    # newer file in root must NOT be clobbered
    with open(dst, "w") as f:
        f.write("CURRENT-NEWER")
    time.sleep(0.01)
    src2 = os.path.join(old, "modelrig-rag.db")
    with open(src2, "w") as f:
        f.write("STALE-OLDER")
    os.utime(src2, (time.time() - 100, time.time() - 100))  # make it older
    M.run(apply=True, keep=False)
    check(open(dst).read() == "CURRENT-NEWER", "apply: a newer file in the root is NOT overwritten")

    del os.environ["KALIV_DATA_DIR"]

print(f"\n===== MIGRATE: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
