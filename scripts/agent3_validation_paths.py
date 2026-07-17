from __future__ import annotations

from pathlib import Path

DEFAULT_REPORT_RELATIVE = Path("validation") / "agent3-rig-validation-latest.json"
DEFAULT_REPORT_TEXT = DEFAULT_REPORT_RELATIVE.as_posix()


def default_report_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_REPORT_RELATIVE
