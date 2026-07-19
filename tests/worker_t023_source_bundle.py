from __future__ import annotations

import base64
import io
import tarfile
from pathlib import Path

PATHS = [
    "worker/app/agent3/core.py",
    "worker/app/agent3/integration.py",
    "worker/app/agent3/planner.py",
    "worker/app/agent3/api.py",
    "android/app/src/main/java/dk/ternedal/modelrig/net/Agent3Client.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent3Screen.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/Agent3Client.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3DevApp.kt",
]

buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
    for name in PATHS:
        archive.add(Path(name), arcname=name)

print("T023_SOURCE_BUNDLE_BEGIN")
print(base64.b64encode(buffer.getvalue()).decode("ascii"))
print("T023_SOURCE_BUNDLE_END")
print(f"t023 source bundle: {len(PATHS)} files")
