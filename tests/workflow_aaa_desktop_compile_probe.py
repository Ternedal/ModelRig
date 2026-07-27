from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ["./gradlew", ":composeApp:test", "--no-daemon", "--console=plain"]

completed = subprocess.run(
    COMMAND,
    cwd=ROOT / "desktop",
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    timeout=900,
)

if completed.returncode != 0:
    lines = completed.stdout.splitlines()
    print("===== TEMP DESKTOP COMPILE DIAGNOSTIC: LAST 160 LINES =====")
    print("\n".join(lines[-160:]))
    raise SystemExit(completed.returncode)

print("temporary desktop compile diagnostic: success")
