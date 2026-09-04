#!/usr/bin/env python3
"""Current-head adapter for the existing T-033 physical backup/restore proof.

The underlying physical operator and acceptance gate stay authoritative. This
adapter only adds a strict campaign-id addressing mode so the second Windows SID
can resolve the already-created Public request/probe paths without copying long
absolute paths between user sessions.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKER = ROOT / "worker"
CAMPAIGN_ROOT = ROOT / "validation" / "agent3-memory-protected-backup-physical"
CAMPAIGN_ID_RE = re.compile(r"^t033-\d{8}-\d{6}-[0-9a-f]{8}$")

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(WORKER))
import agent3_memory_protected_backup_physical as op  # noqa: E402


def cap(*args: str) -> str:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout.strip()


def exact(*, sync_remote: bool) -> str:
    dirty = cap("git", "status", "--porcelain")
    if dirty:
        raise RuntimeError("Working tree er ikke ren:\n" + dirty)
    branch = cap("git", "branch", "--show-current")
    if not branch:
        raise RuntimeError("Detached HEAD afvises")
    if sync_remote:
        cap("git", "fetch", "--quiet", "origin", branch)
        cap("git", "pull", "--ff-only", "origin", branch)
    sha = cap("git", "rev-parse", "HEAD")
    if sync_remote and sha != cap("git", "rev-parse", f"origin/{branch}"):
        raise RuntimeError("HEAD/remote mismatch")
    return sha


def _validated_campaign_id(value: str) -> str:
    campaign_id = value.strip()
    if not CAMPAIGN_ID_RE.fullmatch(campaign_id):
        raise RuntimeError(
            "campaign-id skal have formen t033-YYYYMMDD-HHMMSS-<8 lowercase hex>"
        )
    return campaign_id


def _public_campaign_root() -> Path:
    value = os.environ.get("PUBLIC", "").strip()
    if value:
        public_root = Path(value)
    else:
        drive = Path(ROOT.drive + "\\") if ROOT.drive else Path("C:\\")
        public_root = drive / "Users" / "Public"
    return public_root / "Documents" / "Kaliv-T033"


def _campaign_paths(campaign_id: str) -> dict[str, Path]:
    campaign_id = _validated_campaign_id(campaign_id)
    repository_campaign = CAMPAIGN_ROOT / campaign_id
    public_campaign = _public_campaign_root() / campaign_id
    return {
        "state": repository_campaign / "state.json",
        "request": public_campaign / "request.json",
        "probe": public_campaign / "probe.json",
    }


def _expand_campaign_args(argv: list[str]) -> list[str]:
    values = list(argv)
    if "--campaign-id" not in values:
        return values
    if len(values) != 3 or values[0] not in {"probe", "collect"} or values[1] != "--campaign-id":
        raise RuntimeError(
            "campaign-id mode er eksklusiv: brug kun 'probe --campaign-id <id>' "
            "eller 'collect --campaign-id <id>'"
        )
    paths = _campaign_paths(values[2])
    if values[0] == "probe":
        return [
            "probe",
            "--request",
            str(paths["request"]),
            "--output",
            str(paths["probe"]),
        ]
    return [
        "collect",
        "--state",
        str(paths["state"]),
        "--probe",
        str(paths["probe"]),
    ]


def _latest_campaign_id(candidate_sha: str) -> str | None:
    if not CAMPAIGN_ROOT.is_dir() or CAMPAIGN_ROOT.is_symlink():
        return None
    states = sorted(
        CAMPAIGN_ROOT.glob("*/state.json"),
        key=lambda path: path.stat().st_mtime_ns if path.exists() else 0,
        reverse=True,
    )
    for state_path in states:
        if state_path.is_symlink() or not state_path.is_file() or state_path.parent.is_symlink():
            continue
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(state, dict):
            continue
        candidate = state.get("candidate")
        campaign_id = state.get("campaign_id")
        if not isinstance(candidate, dict) or candidate.get("git_sha") != candidate_sha:
            continue
        if not isinstance(campaign_id, str) or campaign_id != state_path.parent.name:
            continue
        try:
            return _validated_campaign_id(campaign_id)
        except RuntimeError:
            continue
    return None


def _print_campaign_hint(candidate_sha: str) -> None:
    campaign_id = _latest_campaign_id(candidate_sha)
    if campaign_id is None:
        return
    adapter = ROOT / "scripts" / "proof_t033_current.py"
    print("\nT-033 CAMPAIGN-ID MODE (current-era ergonomi; samme fysiske gate):")
    print(f"Campaign: {campaign_id}")
    print("Brug denne korte kommando i stedet for at kopiere request/output-paths:")
    print(
        f'runas /user:<ANDEN-BRUGER> "python \\\"{adapter}\\\" '
        f'probe --campaign-id {campaign_id}"'
    )
    print(
        "Når runas-proben er færdig, kør proof-kampagnen igen fra den samme "
        "ejer-session; eksisterende exact-SHA state/probe genbruges og collect sker derfra."
    )


def main(argv: list[str] | None = None) -> int:
    os.chdir(ROOT)
    values = list(sys.argv[1:] if argv is None else argv)
    command = values[0] if values else ""
    candidate_sha = exact(sync_remote=(command == "prepare"))
    branch = cap("git", "branch", "--show-current")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    op.BRANCH, op.VERSION = branch, version
    op.stage.BRANCH, op.stage.VERSION = branch, version
    op.stage.ensure_candidate = lambda: exact(sync_remote=True)
    expanded = _expand_campaign_args(values)
    result = int(op.main(expanded))
    if command == "prepare" and result == 0:
        _print_campaign_hint(candidate_sha)
    return result


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"T-033 BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
