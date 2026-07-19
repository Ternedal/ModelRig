#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import textwrap

workflow = Path(".github/workflows/bind-lifecycle-artifacts-pr.yml")
source = workflow.read_text(encoding="utf-8")
start = "          python - <<'PY'\n"
end = "\n          PY\n"
if source.count(start) != 1 or source.count(end) != 1:
    raise SystemExit("embedded lifecycle patch markers are not unique")
body = source.split(start, 1)[1].split(end, 1)[0]
exec(compile(textwrap.dedent(body), "<lifecycle-artifact-patch>", "exec"))
Path("scripts/_apply_lifecycle_artifact_patch.py").unlink()
