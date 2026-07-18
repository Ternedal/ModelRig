"""Android setup must only claim credentials after a confirmed durable commit.

Run: python tests/android_credential_commit_contract.py
"""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
store = (root / "android/app/src/main/java/dk/ternedal/modelrig/data/TokenStore.kt").read_text(encoding="utf-8")
ui = (root / "android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt").read_text(encoding="utf-8")

checks = {
    "rig connection has an explicit commit result": "fun saveRigConnection" in store,
    "cloud configuration has an explicit commit result": "fun saveCloudConfiguration" in store,
    "credential transactions use synchronous commit": store.count("return editor.commit()") >= 2,
    "setup no longer assigns rig token through apply-backed property": "store.token =" not in ui,
    "setup no longer assigns cloud key through apply-backed property": "store.cloudKey =" not in ui,
    "all rig setup paths use the transactional boundary": ui.count("store.saveRigConnection(") >= 3,
    "cloud setup uses the transactional boundary": "store.saveCloudConfiguration(" in ui,
    "UI branches on confirmed persistence": ui.count("if (saved)") >= 4,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")
print(f"\n===== ANDROID CREDENTIAL COMMIT CONTRACT: {len(checks) - len(failed)} passed, {len(failed)} failed =====")
raise SystemExit(1 if failed else 0)
