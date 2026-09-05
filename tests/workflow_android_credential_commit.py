"""Android setup must only claim credentials after a confirmed durable commit.

Run: python tests/workflow_android_credential_commit.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

root = Path(__file__).resolve().parents[1]
store = code_of(root / "android/app/src/main/java/dk/ternedal/modelrig/data/TokenStore.kt")
ui = code_of(root / "android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt")

checks = {
    "rig connection has an explicit commit result": "fun saveRigConnection" in store,
    "cloud configuration has an explicit commit result": "fun saveCloudConfiguration" in store,
    "credential transactions use synchronous commit": store.count("return editor.commit()") >= 2,
    "setup no longer assigns rig token through apply-backed property": "store.token =" not in ui,
    "setup no longer assigns cloud key through apply-backed property": "store.cloudKey =" not in ui,
    "all rig setup paths use the transactional boundary": ui.count("store.saveRigConnection(") >= 3,
    "profile apply branches directly on persistence": "if (store.saveRigConnection(profile.serverUrl, profile.deviceToken))" in ui,
    "reconnect and pairing branch on persistence": ui.count("val saved = store.saveRigConnection(") >= 2 and ui.count("if (saved)") >= 3,
    "cloud setup uses the transactional boundary": "store.saveCloudConfiguration(" in ui,
    "credential clears return confirmed results": "fun clearRig(): Boolean" in store and "fun clearCloud(): Boolean" in store,
    "setup clear buttons branch on commit results": "if (store.clearRig())" in ui and "if (store.clearCloud())" in ui,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")
print(f"\n===== ANDROID CREDENTIAL COMMIT CONTRACT: {len(checks) - len(failed)} passed, {len(failed)} failed =====")
raise SystemExit(1 if failed else 0)
