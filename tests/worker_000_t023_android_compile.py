from __future__ import annotations

import os
import subprocess
from pathlib import Path

android = Path(__file__).resolve().parents[1] / "android"
sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
if sdk:
    (android / "local.properties").write_text(f"sdk.dir={sdk}\n", encoding="utf-8")
result = subprocess.run(
    ["./gradlew", ":app:compileDebugKotlin", "--no-daemon", "--console=plain"],
    cwd=android,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
print(result.stdout)
raise SystemExit(result.returncode)
