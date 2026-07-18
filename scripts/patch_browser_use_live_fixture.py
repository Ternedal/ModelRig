from pathlib import Path

adapter = Path("worker/app/browser_use_adapter.py").read_text(encoding="utf-8")
for required in (
    '"accept_downloads",',
    '"permissions",',
    "accept_downloads=False,",
    "permissions=[],",
):
    if required not in adapter:
        raise SystemExit(f"adapter hardening missing: {required}")

test_path = Path("tests/worker_browser_use_runtime_guard.py")
test = test_path.read_text(encoding="utf-8")
old = '''check(clean_runtime.profile_kwargs["user_data_dir"] is None, "Browser Use owns profile temp path creation")\ncheck(clean_runtime.profile_kwargs["auto_download_pdfs"] is False, "automatic PDF downloads are disabled")\n'''
new = '''check(clean_runtime.profile_kwargs["user_data_dir"] is None, "Browser Use owns profile temp path creation")\ncheck(clean_runtime.profile_kwargs["accept_downloads"] is False, "adapter refuses browser downloads")\ncheck(clean_runtime.profile_kwargs["permissions"] == [], "adapter grants no browser permissions")\ncheck(clean_runtime.profile_kwargs["auto_download_pdfs"] is False, "automatic PDF downloads are disabled")\n'''
if old in test:
    test = test.replace(old, new)
elif new not in test:
    raise SystemExit("expected adapter profile assertions exactly once")
test_path.write_text(test, encoding="utf-8")
