from __future__ import annotations

import subprocess

sha = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
print(f"T023_TREE_SHA={sha}")
raise SystemExit(1)
