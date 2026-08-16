from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-proof-campaign.ps1"


def main() -> int:
    source = SCRIPT.read_text(encoding="utf-8")
    failures: list[str] = []

    if "function Git(" not in source:
        failures.append("proof campaign Git helper is missing")

    if "& git.exe @A" not in source:
        failures.append("Git helper must invoke git.exe explicitly")

    if re.search(r"&\s+git\s+@A", source, flags=re.IGNORECASE):
        failures.append(
            "Git helper recursively resolves to PowerShell function Git; use git.exe"
        )

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("PASS: physical proof launcher Git helper cannot recurse into itself")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
