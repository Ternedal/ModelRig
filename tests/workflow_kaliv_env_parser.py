#!/usr/bin/env python3
"""Read-KalivEnvFile strips inline comments the way the appliance means them.

An env mirror that matched ^KEY=(.*)$ once swallowed "# comment" into the
value of MODELRIG_OLLAMA_URL; every model call answered 405 for three days
before anyone read the variable. Env parsing now lives in one PowerShell
function, and this gate runs it under pwsh against the exact shapes that
bit: trailing comments after whitespace, values that legitimately contain
'#', quotes, indentation, blank and comment-only lines, lines without '='.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CASES = """# top comment
MODELRIG_OLLAMA_URL=http://127.0.0.1:11434 # (worker reads the same var)
MODELRIG_CLAIM_MAX=10                       # max pair/claim attempts
KALIV_AGENT3_ENABLED=1
QUOTED="hello world" # trailing
COLOUR=#ff00ff
EMPTY=
   INDENTED = spaced   
NOEQ
"""

EXPECT = {
    "MODELRIG_OLLAMA_URL": "http://127.0.0.1:11434",
    "MODELRIG_CLAIM_MAX": "10",
    "KALIV_AGENT3_ENABLED": "1",
    "QUOTED": "hello world",
    "COLOUR": "#ff00ff",
    "EMPTY": "",
    "INDENTED": "spaced",
}


def main() -> int:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        print("  SKIP: no PowerShell available -- parser gate needs pwsh")
        return 0
    with tempfile.TemporaryDirectory() as d:
        env_path = Path(d) / "modelrig.env"
        env_path.write_text(CASES, encoding="utf-8")
        script = (
            f". '{(ROOT / 'scripts' / 'Read-KalivEnvFile.ps1').as_posix()}'\n"
            f"$e = Read-KalivEnvFile -Path '{env_path.as_posix()}'\n"
            "foreach ($k in ($e.Keys | Sort-Object)) { Write-Output ($k + '=' + $e[$k]) }\n"
        )
        out = subprocess.run([pwsh, "-NoProfile", "-Command", script], capture_output=True, text=True)
    if out.returncode != 0:
        print("  FAIL: pwsh exited", out.returncode, out.stderr[:300])
        return 1
    got = dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)
    failed = 0
    for key, want in EXPECT.items():
        ok = got.get(key) == want
        print(f"  {'PASS' if ok else 'FAIL'}: {key} = [{got.get(key)}]" + ("" if ok else f" (expected [{want}])"))
        failed |= not ok
    ok = "NOEQ" not in got
    print(f"  {'PASS' if ok else 'FAIL'}: a line without '=' is ignored")
    failed |= not ok
    print("kaliv env parser: " + ("OK" if not failed else "BROKEN"))
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
