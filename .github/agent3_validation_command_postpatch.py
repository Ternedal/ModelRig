from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one integration anchor, got {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# The harness is imported directly by a legacy CLI contract via importlib. In
# that mode Python does not automatically put scripts/ on sys.path, so make the
# sibling shared-path module resolvable in both direct execution and spec loading.
harness = ROOT / "scripts" / "agent3_rig_validation.py"
replace_once(
    harness,
    "from typing import Any\n\nfrom agent3_validation_paths import DEFAULT_REPORT_TEXT\n",
    '''from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from agent3_validation_paths import DEFAULT_REPORT_TEXT
''',
)

# Use the shared POSIX-style relative path in the PowerShell command too.
# Windows accepts it through Join-Path and it avoids a second escaping contract.
wrapper = ROOT / "scripts" / "run-agent3-rig-validation.ps1"
lines = wrapper.read_text(encoding="utf-8").splitlines()
matched = 0
for index, line in enumerate(lines):
    if "$ReportPath = Join-Path $repoRoot" in line and "agent3-rig-validation-latest.json" in line:
        lines[index] = '    $ReportPath = Join-Path $repoRoot "validation/agent3-rig-validation-latest.json"'
        matched += 1
if matched != 1:
    raise SystemExit(f"PowerShell default report line drifted: {matched} matches")
wrapper.write_text("\n".join(lines) + "\n", encoding="utf-8")

# Replace the one newly-added assertion block semantically. The first draft
# accidentally embedded \a as a Python escape while trying to assert a Windows
# backslash. Assert the actual shared value instead.
contract = ROOT / "tests" / "worker_agent3_validation_path_contract.py"
lines = contract.read_text(encoding="utf-8").splitlines()
message_index = next(
    (i for i, line in enumerate(lines) if "PowerShell operator command uses the shared report location" in line),
    None,
)
if message_index is None:
    raise SystemExit("new path contract message not found")
start = message_index
while start >= 0 and lines[start].strip() != "check(":
    start -= 1
end = message_index
while end < len(lines) and lines[end].strip() != ")":
    end += 1
if start < 0 or end >= len(lines):
    raise SystemExit("new path contract block boundaries not found")
lines[start : end + 1] = [
    "check(",
    "    DEFAULT_REPORT_TEXT in wrapper,",
    '    "the PowerShell operator command uses the shared report location",',
    ")",
]
contract.write_text("\n".join(lines) + "\n", encoding="utf-8")

# The pre-existing readiness contract must follow the same shared default,
# otherwise the generator is correct but CI keeps asserting the obsolete path.
readiness_test = ROOT / "tests" / "workflow_activation_readiness.py"
replace_once(
    readiness_test,
    'GEN = ROOT / "scripts" / "activation_readiness.py"\n',
    '''GEN = ROOT / "scripts" / "activation_readiness.py"
sys.path.insert(0, str(ROOT / "scripts"))
from agent3_validation_paths import DEFAULT_REPORT_RELATIVE, DEFAULT_REPORT_TEXT  # noqa: E402
''',
)
replace_once(
    readiness_test,
    'has_report = (ROOT / "agent3-validation-latest.json").exists()',
    "has_report = (ROOT / DEFAULT_REPORT_RELATIVE).exists()",
)
replace_once(
    readiness_test,
    '''check("agent3-validation-latest.json" in text and "/home/" not in text,
      "the report path is relative -- an absolute one bakes one machine into a "
      "committed file")''',
    '''check(DEFAULT_REPORT_TEXT in text and "/home/" not in text,
      "the report path is relative -- an absolute one bakes one machine into a "
      "committed file")''',
)

# PR and release use the same reusable test workflow. Parse every committed
# PowerShell script there, so this operator command cannot regress into a file
# that looks plausible in review but PowerShell refuses to load on the rig.
tests_workflow = ROOT / ".github" / "workflows" / "_tests.yml"
replace_once(
    tests_workflow,
    '''      - name: Python lint gate (syntax + undefined names)
        run: |
          pip install --quiet ruff
          ruff check --select E9,F63,F7,F82 worker/ tests/

      # Every integration + worker test, globbed so a new tests/*.py is included''',
    '''      - name: Python lint gate (syntax + undefined names)
        run: |
          pip install --quiet ruff
          ruff check --select E9,F63,F7,F82 worker/ tests/

      - name: PowerShell syntax gate
        shell: pwsh
        run: |
          $ErrorActionPreference = "Stop"
          Get-ChildItem -Path . -Recurse -File -Filter *.ps1 | ForEach-Object {
            [void][scriptblock]::Create((Get-Content -LiteralPath $_.FullName -Raw))
            Write-Host "parsed $($_.FullName)"
          }

      # Every integration + worker test, globbed so a new tests/*.py is included''',
)

print("Agent3 validation command integration normalized")
