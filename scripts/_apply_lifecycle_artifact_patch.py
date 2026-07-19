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
test = test.replace(recursive, fixed)

old_temp = '''    with tempfile.TemporaryDirectory(dir=ROOT, prefix="campaign-test-") as temp_dir:
        temp = Path(temp_dir)'''
new_temp = '''    artifact_parent = ROOT / "validation" / "appliance-lifecycle-evidence"
    artifact_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=artifact_parent,
        prefix="campaign-test-",
    ) as temp_dir:
        temp = Path(temp_dir)'''
if test.count(old_temp) != 1:
    raise SystemExit(f"campaign temp fixture count is {test.count(old_temp)}")
test_path.write_text(test.replace(old_temp, new_temp), encoding="utf-8")

Path(".github/workflows/retry-lifecycle-artifacts-pr.yml").unlink(missing_ok=True)
Path("scripts/_apply_lifecycle_artifact_patch.py").unlink()
