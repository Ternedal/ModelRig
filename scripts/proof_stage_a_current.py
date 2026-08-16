#!/usr/bin/env python3
"""Current-head adapter for the repository's retained Stage A one-click campaign."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import physical_validation_campaign as campaign  # noqa: E402
import stage_a_one_click as stage  # noqa: E402


def cap(*args: str) -> str:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if p.returncode:
        raise stage.WizardError((p.stderr or p.stdout).strip())
    return p.stdout.strip()


def ensure_current() -> str:
    if os.name != "nt":
        raise stage.WizardError("Stage A må kun køres på Windows-riggen")
    dirty = cap("git", "status", "--porcelain")
    if dirty:
        raise stage.WizardError("Working tree er ikke ren:\n" + dirty)
    branch = cap("git", "branch", "--show-current")
    if not branch:
        raise stage.WizardError("Detached HEAD afvises; brug en navngivet branch")
    # Never switch branch. Update exactly the checkout the operator selected.
    cap("git", "fetch", "--quiet", "origin", branch)
    cap("git", "pull", "--ff-only", "origin", branch)
    sha = cap("git", "rev-parse", "HEAD")
    remote = cap("git", "rev-parse", f"origin/{branch}")
    if sha != remote:
        raise stage.WizardError("Lokal HEAD matcher ikke origin/" + branch)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != stage.VERSION:
        raise stage.WizardError(f"VERSION er {version}, forventede {stage.VERSION}")
    stage.ok(f"Aktuel kandidat {version} på {sha}")
    return sha


def _still_valid_proofs() -> set[str]:
    """Return proof names that already pass the authoritative current-candidate validators.

    The retained wizard used to archive every rolling report whenever HEAD changed,
    even when the proof contract itself was code-fingerprint/version bound and still
    valid.  Reuse only evidence that the same campaign validator accepts against the
    new candidate; everything else remains fail-closed and is archived/re-run.
    """
    identity = campaign.candidate_identity(ROOT)
    thresholds = {
        "min_model_exact": 1.0,
        "agent3_assessor": campaign._load_agent3_assessor(ROOT),
        "root": ROOT,
    }
    now = datetime.now(timezone.utc)
    carried: set[str] = set()
    for name in stage.PROOFS:
        path = campaign.DEFAULT_PATHS.get(name)
        if path is None or not (ROOT / path).is_file():
            continue
        try:
            result = campaign.validate_evidence(
                ROOT,
                name,
                path,
                candidate=identity,
                thresholds=thresholds,
                now=now,
                max_age_hours=168.0,
            )
        except Exception:
            continue
        if result.get("status") == "pass":
            carried.add(name)
    return carried


def archive_previous_evidence_current(sha: str, state: dict) -> None:
    """Archive only evidence that is no longer valid for the new exact candidate."""
    if state.get("candidate_sha") == sha:
        return

    try:
        carried = _still_valid_proofs()
    except Exception as exc:
        # Carry-forward is an optimisation, never a reason to weaken fail-closed.
        stage.note(f"Kunne ikke verificere genbrug af tidligere beviser ({type(exc).__name__}); invaliderer konservativt.")
        carried = set()

    proof_paths = {
        name: campaign.DEFAULT_PATHS[name]
        for name in stage.PROOFS
        if name in campaign.DEFAULT_PATHS
    }
    always_archive = (
        Path("validation/pre-release-candidate-freeze-latest.json"),
        Path("validation/physical-validation-candidate-campaign-latest.json"),
        Path("validation/browser-peer-public-validation-physical-latest.json"),
        Path("validation/browser-peer-public-validation-latest.json"),
        Path("validation/physical-validation-candidate-final-latest.json"),
    )
    sources: list[Path] = []
    for name, relative in proof_paths.items():
        path = ROOT / relative
        if path.is_file() and name not in carried:
            sources.append(path)
    for relative in always_archive:
        path = ROOT / relative
        if path.is_file():
            sources.append(path)

    if sources:
        archive = stage.VALIDATION / "archive" / time.strftime("stage-a-%Y%m%d-%H%M%S")
        archive.mkdir(parents=True, exist_ok=True)
        for source in sources:
            source.replace(archive / source.name)
        stage.note(f"Kun invaliderede rolling reports er bevaret i {archive}")
    if carried:
        stage.note("Genbruger allerede gyldige beviser: " + ", ".join(sorted(carried)))

    state.clear()
    state["candidate_sha"] = sha
    state["carried_forward_proofs"] = sorted(carried)
    stage.save_state(state)


def strict_stage_current(action: str, sha: str, url: str | None = None) -> None:
    args = [
        sys.executable,
        str(ROOT / "scripts" / "proof_stage_a_operator_current.py"),
        action.lower(),
        "--expected-sha",
        sha,
        "--max-age-hours",
        "168",
        "--min-model-exact",
        "1.0",
    ]
    if url:
        args += ["--url", url]
    stage.run(args)


def stop_exact_head_stack_for_voice() -> None:
    """Release 8080/8099 only when they are owned by the known Stage-A stack.

    The retained one-click flow starts a loopback exact-head stack for preflight,
    Agent 3 and RAG. The physical voice flow must replace that stack with its
    LAN-bound phone stack. Hand the ports over explicitly instead of asking the
    operator to kill a process. The cleanup script is fail-closed and refuses
    unknown listeners.
    """
    stage.note("Voice-handoff: stopper den kendte loopback Stage A-stack før LAN/Pixel-testen.")
    stage.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "stop-stage-a-known-processes.ps1"),
        ]
    )


def voice_observations_current(argv: list[str]) -> int:
    """Run the retained guided collector against the phone-stack v2 state schema."""
    import stage_a_voice_observations as observations

    observations.PHONE_STATE_SCHEMA = "kaliv-stage-a-phone-test-state/v2"
    return int(observations.main(argv))


def voice_current(planner: str) -> None:
    stage.heading("Fysisk voice-bevis — guidet og automatisk")
    stop_exact_head_stack_for_voice()
    stage.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "stage-a-voice-test.ps1"),
            "-PlannerModel",
            planner,
        ]
    )


def scheduler_current(planner: str, state: dict) -> None:
    del planner, state
    stage.heading("Fysisk scheduler-bevis — én Pixel-godkendelse")
    stage.run([sys.executable, str(ROOT / "scripts" / "proof_scheduler_current.py")])


def main() -> int:
    os.chdir(ROOT)
    branch = cap("git", "branch", "--show-current")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    stage.BRANCH, stage.VERSION = branch, version
    stage.ensure_candidate = ensure_current
    stage.archive_previous_evidence = archive_previous_evidence_current
    stage.strict_stage = strict_stage_current
    stage.run_voice = voice_current
    stage.run_scheduler = scheduler_current
    return int(stage.main())


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "voice-observations":
            raise SystemExit(voice_observations_current(sys.argv[2:]))
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"STAGE A CURRENT-HEAD BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
