"""Run the isolated Development Control Plane test suite in shared CI.

The control plane remains under ``devcontrol/``. This bridge contains no runtime
integration; it only makes the isolated suite part of the existing PR and release
gates, which auto-discover ``tests/workflow_*.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "devcontrol/tests",
            "-v",
        ],
        cwd=ROOT,
        env=env,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
