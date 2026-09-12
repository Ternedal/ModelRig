from pathlib import Path

path = Path("worker/app/agent3/planner.py")
text = path.read_text(encoding="utf-8")
old = '''    def _reviewed_start_error(reason: str, message: str, status_code: int = 409) -> HTTPException:\n        return HTTPException(\n            status_code=status_code,\n            detail={"reason": reason, "message": message},\n        )\n'''
new = '''    def _reviewed_start_error(reason: str, message: str, status_code: int = 409) -> HTTPException:\n        return HTTPException(\n            status_code=status_code,\n            detail=message,\n            headers={"X-ModelRig-Agent3-Reason": reason},\n        )\n'''
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one reviewed Start error helper, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
