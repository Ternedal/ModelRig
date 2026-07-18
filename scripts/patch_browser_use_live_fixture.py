from pathlib import Path

path = Path("worker/app/browser_use_adapter.py")
text = path.read_text(encoding="utf-8")

old_fields = '''        "downloads_path",\n        "auto_download_pdfs",\n        "captcha_solver",\n'''
new_fields = '''        "downloads_path",\n        "accept_downloads",\n        "permissions",\n        "auto_download_pdfs",\n        "captcha_solver",\n'''
if text.count(old_fields) != 1:
    raise SystemExit("expected BrowserProfile field block exactly once")
text = text.replace(old_fields, new_fields)

old_profile = '''                downloads_path=None,\n                auto_download_pdfs=False,\n                captcha_solver=False,\n'''
new_profile = '''                downloads_path=None,\n                accept_downloads=False,\n                permissions=[],\n                auto_download_pdfs=False,\n                captcha_solver=False,\n'''
if text.count(old_profile) != 1:
    raise SystemExit("expected BrowserProfile construction block exactly once")
text = text.replace(old_profile, new_profile)

path.write_text(text, encoding="utf-8")
