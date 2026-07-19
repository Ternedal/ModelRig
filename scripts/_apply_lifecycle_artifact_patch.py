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

test_path = Path("tests/workflow_physical_validation_campaign.py")
test = test_path.read_text(encoding="utf-8")
recursive = '''def reports_with_artifacts(temp: Path) -> dict[str, dict]:
    reports = reports_with_artifacts(temp)'''
fixed = '''def reports_with_artifacts(temp: Path) -> dict[str, dict]:
    reports = valid_reports()'''
if test.count(recursive) != 1:
    raise SystemExit(f"recursive artifact helper count is {test.count(recursive)}")
test_path.write_text(test.replace(recursive, fixed), encoding="utf-8")

Path(".github/workflows/retry-lifecycle-artifacts-pr.yml").unlink(missing_ok=True)
Path("scripts/_apply_lifecycle_artifact_patch.py").unlink()
