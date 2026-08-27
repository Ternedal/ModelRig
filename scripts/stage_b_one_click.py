#!/usr/bin/env python3
"""One-click, resumable Windows wizard for the physical Stage B updater campaign.

Stage A proved seven candidate-bound proofs. Stage B proves the eighth: that the
appliance survives its own lifecycle -- a reboot, both supervisor restarts, a real
updater run onto the published release, and an invalid update that is refused or
rolled back cleanly.

The observations file behind that proof carries ~50 hand-filled fields: versions,
40- and 64-hex fingerprints, log paths, SHA-256 digests and latencies. Every one of
them is measurable, and hand-copying them is where a physical campaign goes wrong.
This wizard measures them instead, and stops only for what a human must truly do:
press reboot, and approve the invalid-update run.

It cannot merge, push, tag, publish a release or activate production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
EVIDENCE = VALIDATION / "appliance-lifecycle-evidence"
OBSERVATIONS = VALIDATION / "appliance-lifecycle-observations.json"
EXAMPLE = ROOT / "eval" / "appliance_lifecycle_observations.example.json"
STATE_PATH = VALIDATION / "stage-b-easy-state.json"
JOURNAL = ROOT / "update-transaction.json"
APPLIANCE: Path | None = None


def use_root(new_root: Path) -> None:
    """Point the wizard at a different checkout than the one it is stored in.

    Stage B's release freeze requires HEAD to be exactly the published tag's
    commit -- but this wizard is merged AFTER that commit, so it does not exist
    inside the release checkout, and copying it in would dirty the tree the same
    freeze checks. Running it from a newer worktree while writing evidence into
    the release checkout resolves both: validation/ is gitignored, so the
    evidence never dirties the tree it must describe.
    """
    global ROOT, VALIDATION, EVIDENCE, OBSERVATIONS, EXAMPLE, STATE_PATH, JOURNAL
    ROOT = new_root.resolve()
    VALIDATION = ROOT / "validation"
    EVIDENCE = VALIDATION / "appliance-lifecycle-evidence"
    OBSERVATIONS = VALIDATION / "appliance-lifecycle-observations.json"
    EXAMPLE = ROOT / "eval" / "appliance_lifecycle_observations.example.json"
    STATE_PATH = VALIDATION / "stage-b-easy-state.json"
    JOURNAL = ROOT / "update-transaction.json"

LIFECYCLE_SCHEMA = "kaliv-appliance-lifecycle-observations/v1"
RELEASE_REPO = "Ternedal/ModelRig"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
BACKEND_HEALTH = "http://127.0.0.1:8080/healthz"
WORKER_HEALTH = "http://127.0.0.1:8099/healthz"
AGENT3_STATUS = "http://127.0.0.1:8080/api/v1/experimental/agent3/status"
SUPERVISOR_TASK = "KalivSupervisor"
READY_TIMEOUT_S = 300.0


class StageBError(RuntimeError):
    pass


def heading(text: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {text}")
    print("=" * 72)


def ok(text: str) -> None:
    print(f"  OK    {text}")


def note(text: str) -> None:
    print(f"  ->    {text}")


def capture(args: list[str], *, cwd: Path | None = None, timeout: float = 120.0) -> str:
    # Resolve ROOT at call time, not at def time. `cwd: Path = ROOT` bound the
    # default to whatever ROOT was when this module was imported, so use_root()
    # could not move it -- and --root exists precisely to run a newer wizard
    # against a frozen release checkout. The result was that `git rev-parse
    # HEAD` and the clean-tree check both ran in the WIZARD's repo, so the
    # bundle attested the wizard's commit as the candidate instead of the
    # released one, and the release freeze rejected it.
    try:
        result = subprocess.run(
            args,
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StageBError(f"Kommandoen kunne ikke gennemføres: {' '.join(args)}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise StageBError(f"{' '.join(args)} fejlede: {detail[-400:]}")
    return result.stdout.strip()


def powershell(script: str, *, timeout: float = 120.0) -> str:
    return capture(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    )


def get_json(url: str, *, timeout: float = 5.0, token: str | None = None) -> Any:
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _github_token() -> str | None:
    """The rig's PAT when the session carries one, else None.

    Unauthenticated GitHub API calls share a 60/hour per-IP budget that a
    single rig day exhausts (#753 item 9); authenticated calls do not.
    """
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_state() -> dict[str, Any]:
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    VALIDATION.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def save_observations(observations: dict[str, Any]) -> None:
    OBSERVATIONS.parent.mkdir(parents=True, exist_ok=True)
    OBSERVATIONS.write_text(
        json.dumps(observations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# --- measurement -----------------------------------------------------------


def candidate_identity() -> dict[str, Any]:
    """The same identity the chain validator recomputes -- never hand-typed."""
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    git_sha = capture(["git", "rev-parse", "HEAD"])
    worker = ROOT / "worker"
    if str(worker) not in sys.path:
        sys.path.insert(0, str(worker))
    from app.build_identity import code_fingerprint  # noqa: E402

    return {"version": version, "git_sha": git_sha, "code_sha256": code_fingerprint()}


def released_commit(version: str) -> str:
    """The commit a published release tag points at.

    good_update.source_git_sha must name the release the rig actually started
    on. It used to fall back to the candidate's own SHA, which the validator
    rejects outright ("source_git_sha must differ from the candidate") -- and
    rightly so: a source equal to the target would prove no transition happened.
    """
    tag = version if version.startswith("v") else f"v{version}"
    try:
        sha = capture(["git", "rev-list", "-n", "1", tag])
    except StageBError:
        raise StageBError(
            f"Kunne ikke slå {tag} op i checkouten. Hent tags med "
            "'git fetch --tags origin', så kildereleasens commit kan måles."
        ) from None
    if not _SHA40.fullmatch(sha):
        raise StageBError(f"{tag} gav ikke en gyldig 40-tegns commit: {sha!r}")
    return sha


def remote_release_identity(repo: str) -> tuple[str, str]:
    """Version and commit of the release an invalid-update trial actually hit.

    Measured from the release the updater was pointed at, so the attested
    attempt names a real artifact instead of an empty string.
    """
    try:
        release = get_json(
            f"https://api.github.com/repos/{repo}/releases/latest",
            timeout=15.0,
            token=_github_token(),
        )
        tag = str(release.get("tag_name") or "")
        if not tag:
            return "", ""
        ref = get_json(
            f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}",
            timeout=15.0,
            token=_github_token(),
        )
        obj = ref.get("object") if isinstance(ref, dict) else None
        sha = str(obj.get("sha") or "") if isinstance(obj, dict) else ""
        # An annotated tag points at a tag object; dereference it to the commit.
        if isinstance(obj, dict) and obj.get("type") == "tag" and _SHA40.fullmatch(sha):
            tag_obj = get_json(
                f"https://api.github.com/repos/{repo}/git/tags/{sha}",
                timeout=15.0,
                token=_github_token(),
            )
            inner = tag_obj.get("object") if isinstance(tag_obj, dict) else None
            if isinstance(inner, dict):
                sha = str(inner.get("sha") or "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return "", ""
    version = tag[1:] if tag.startswith("v") else tag
    return version, sha if _SHA40.fullmatch(sha) else ""


WORKER_ASSET = "modelrig-worker-windows-x64.exe"


def installed_worker_exe_sha256() -> str:
    """Digest of the worker exe the updater actually swapped in.

    This is the binding that does not need a token or a feature flag: whatever
    file is sitting in the appliance right now is what the supervisor restarts
    and what survives a reboot.
    """
    path = appliance_root() / "worker" / WORKER_ASSET
    if not path.is_file():
        return ""
    return sha256_file(path)


def released_worker_exe_sha256(version: str) -> str:
    """The same digest as published for this candidate, from its SHA256SUMS.txt.

    Comparing the two proves the installed worker is the released build, without
    asking the running process to introspect itself.
    """
    tag = version if version.startswith("v") else f"v{version}"
    try:
        release = get_json(
            f"https://api.github.com/repos/{RELEASE_REPO}/releases/tags/{tag}",
            timeout=15.0,
            token=_github_token(),
        )
        assets = release.get("assets") if isinstance(release, dict) else None
        url = ""
        for asset in assets or []:
            if isinstance(asset, dict) and asset.get("name") == "SHA256SUMS.txt":
                url = str(asset.get("browser_download_url") or "")
                break
        if not url:
            return ""
        with urllib.request.urlopen(url, timeout=20.0) as response:
            text = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return ""
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[-1].lstrip("*") == WORKER_ASSET:
            digest = fields[0].lower()
            return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else ""
    return ""


def live_versions() -> dict[str, Any]:
    """Read what the running appliance reports -- the honest post-condition."""
    out: dict[str, Any] = {}
    try:
        out["backend_version"] = str(get_json(BACKEND_HEALTH).get("version") or "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        out["backend_version"] = ""
    try:
        out["worker_version"] = str(get_json(WORKER_HEALTH).get("version") or "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        out["worker_version"] = ""
    out["worker_code_sha256"] = worker_fingerprint()
    out["worker_exe_sha256"] = installed_worker_exe_sha256()
    return out


def worker_fingerprint() -> str:
    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    if not token:
        return ""
    try:
        payload = get_json(AGENT3_STATUS, token=token)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return ""
    value = payload.get("code_sha256") if isinstance(payload, dict) else None
    return str(value) if isinstance(value, str) else ""


def seconds_since_boot() -> float | None:
    """How long ago this machine started, so the reboot trial has a real clock.

    The trial's ready_ms only times the wait after the operator confirms the
    rig is back, which is near zero whenever they confirm after it is already
    up. That number has been read as a boot duration. This one cannot be.
    """
    # InvariantCulture is not optional: this rig runs a Danish Windows, where
    # TotalSeconds formats as "12091,615852" and float() rejects it. The first
    # version of this returned None on the only machine it was written for.
    script = (
        "$b=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime; "
        "Write-Output (((Get-Date) - $b).TotalSeconds)"
        ".ToString([System.Globalization.CultureInfo]::InvariantCulture)"
    )
    try:
        return round(float(powershell(script, timeout=30.0).splitlines()[-1].strip()), 1)
    except (StageBError, ValueError, IndexError):
        return None


def wait_ready(timeout: float = READY_TIMEOUT_S) -> float | None:
    """Block until backend AND worker answer; return the milliseconds it took."""
    start = time.monotonic()
    deadline = start + timeout
    while time.monotonic() < deadline:
        try:
            backend = get_json(BACKEND_HEALTH, timeout=2.0)
            worker = get_json(WORKER_HEALTH, timeout=2.0)
            if backend.get("status") == "ok" and worker.get("status") == "ok":
                return round((time.monotonic() - start) * 1000.0, 3)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        time.sleep(1.0)
    return None


def listener_pid(port: int) -> int | None:
    script = (
        f"$x=Get-NetTCPConnection -State Listen -LocalPort {port} "
        "-ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if($null -eq $x){exit 1}; Write-Output $x.OwningProcess"
    )
    try:
        return int(powershell(script, timeout=30.0).splitlines()[-1])
    except (StageBError, ValueError, IndexError):
        return None


SCHEDULE_STORE = "kaliv-schedules.db"


def data_snapshot() -> dict[str, Any]:
    """Cheap before/after fingerprint so data_preserved is measured, not claimed.

    Schedules are read two ways. The admin API is preferred, but it only exists
    when KALIV_SCHEDULER_API=1, which a normal appliance does not set -- and
    comparing two unmeasured None values used to yield "preserved: true" without
    anything having been observed at all. So when the API is unavailable the
    schedule store on disk is digested instead, and the snapshot records WHICH
    binding produced the answer so the bundle cannot claim an unmade measurement.
    """
    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    snapshot: dict[str, Any] = {"schedules": None, "documents": None, "schedules_binding": ""}
    try:
        snapshot["documents"] = get_json(WORKER_HEALTH).get("documents")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        pass
    if token:
        try:
            payload = get_json("http://127.0.0.1:8080/api/v1/schedules", token=token)
            items = payload.get("schedules") if isinstance(payload, dict) else None
            if isinstance(items, list):
                snapshot["schedules"] = len(items)
                snapshot["schedules_binding"] = "api"
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
    if not snapshot["schedules_binding"]:
        store = appliance_root() / SCHEDULE_STORE
        if store.is_file():
            snapshot["schedules"] = sha256_file(store)
            snapshot["schedules_binding"] = "store_digest"
        else:
            snapshot["schedules"] = "absent"
            snapshot["schedules_binding"] = "store_absent"
    return snapshot


# --- trials ----------------------------------------------------------------


def trial_reboot(observations: dict[str, Any], state: dict[str, Any]) -> None:
    if state.get("reboot_done"):
        ok("Reboot-beviset er allerede indsamlet.")
        return
    heading("2/5  MANUELT PAUSEPUNKT — normal reboot")
    print("  Riggen kører nu kandidaten. Genstart normalt (Start -> Genstart), log ind")
    print("  igen når den er oppe, og kør denne wizard igen. Supervisoren skal selv")
    print("  bringe backend + worker op — på kandidatens version, ikke den forrige.")
    print("  Wizard'en måler, hvilke versioner der kom op, og hvor længe siden")
    print("  maskinen bootede — ikke hvor lang tid opstarten tog.")
    log = EVIDENCE / "reboot.log"
    state["reboot_pending_since"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    input("\n  Tryk Enter LIGE EFTER du er logget ind igen efter genstarten: ")

    note("Venter på at supervisoren bringer backend + worker op...")
    ready_ms = wait_ready()
    versions = live_versions()
    # ready_ms is the wait from THIS moment until both services answer -- so it
    # is ~0 whenever the operator presses Enter after the rig is already up,
    # which is the normal case. Runs have recorded 0 ms and 31 ms, and both were
    # read as "the rig booted in 31 milliseconds". It never measured that. The
    # boot age is recorded alongside so the number cannot be misread: it says
    # how long ago the machine actually started.
    lines = [
        f"stage-b reboot trial at {datetime.now(timezone.utc).isoformat()}",
        f"ready_ms={ready_ms}  # wait from operator confirmation, NOT boot duration",
        f"seconds_since_boot={seconds_since_boot()}",
        f"backend_version={versions['backend_version']}",
        f"worker_version={versions['worker_version']}",
        f"worker_code_sha256={versions['worker_code_sha256']}",
        f"worker_exe_sha256={versions['worker_exe_sha256']}",
    ]
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    trial = observations["trials"]["reboot"]
    trial.update(
        {
            "performed": True,
            "ready": ready_ms is not None,
            "ready_ms": ready_ms,
            "backend_version": versions["backend_version"],
            "worker_version": versions["worker_version"],
            "worker_code_sha256": versions["worker_code_sha256"],
            "worker_exe_sha256": versions["worker_exe_sha256"],
            "notes": (
                "Målt af stage_b_one_click efter operatørens genstart. "
                "ready_ms er ventetiden fra operatørens bekræftelse til begge "
                "services svarer — ikke opstartstiden; se seconds_since_boot "
                "i reboot.log."
            ),
            "evidence_path": "validation/appliance-lifecycle-evidence/reboot.log",
            "evidence_sha256": sha256_file(log),
        }
    )
    save_observations(observations)
    state["reboot_done"] = True
    save_state(state)
    if ready_ms is None:
        raise StageBError("Riggen kom ikke op efter genstarten inden for tidsgrænsen.")
    ok(f"Reboot bevist: klar efter {ready_ms:.0f} ms")


def trial_supervisor(
    observations: dict[str, Any], state: dict[str, Any], which: str, port: int
) -> None:
    key = f"supervisor_{which}"
    if state.get(f"{key}_done"):
        ok(f"Supervisor-{which} er allerede bevist.")
        return
    heading(f"{'3' if which == 'backend' else '4'}/5  AUTOMATISK — supervisor genstarter {which}")
    before = listener_pid(port)
    if before is None:
        raise StageBError(f"Ingen {which} lytter på port {port}; start appliancen først.")
    note(f"Stopper {which} (pid {before}); supervisoren skal selv bringe den tilbage.")
    try:
        powershell(f"Stop-Process -Id {before} -Force -ErrorAction Stop", timeout=30.0)
    except StageBError as exc:
        raise StageBError(
            f"Kunne ikke stoppe {which}: {exc}. Kør wizard'en som administrator."
        ) from exc

    start = time.monotonic()
    deadline = start + READY_TIMEOUT_S
    after: int | None = None
    while time.monotonic() < deadline:
        candidate_pid = listener_pid(port)
        if candidate_pid is not None and candidate_pid != before:
            after = candidate_pid
            break
        time.sleep(1.0)
    restart_ms = round((time.monotonic() - start) * 1000.0, 3) if after else None
    if after is not None:
        wait_ready()
    versions = live_versions()
    active_version = versions["backend_version"] if which == "backend" else versions["worker_version"]

    log = EVIDENCE / f"supervisor_{which}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "\n".join(
            [
                f"stage-b supervisor_{which} trial at {datetime.now(timezone.utc).isoformat()}",
                f"stopped_pid={before}",
                f"restarted_pid={after}",
                f"restart_ms={restart_ms}",
                f"active_version={active_version}",
                f"active_code_sha256={versions['worker_code_sha256']}",
                f"active_exe_sha256={versions['worker_exe_sha256']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trial = observations["trials"][key]
    trial.update(
        {
            "performed": True,
            "restarted": after is not None,
            "ready": after is not None,
            "restart_ms": restart_ms,
            "active_version": active_version,
            "active_code_sha256": versions["worker_code_sha256"],
            "active_exe_sha256": versions["worker_exe_sha256"],
            "notes": f"Supervisor bragte {which} tilbage; målt af stage_b_one_click.",
            "evidence_path": f"validation/appliance-lifecycle-evidence/supervisor_{which}.log",
            "evidence_sha256": sha256_file(log),
        }
    )
    save_observations(observations)
    state[f"{key}_done"] = True
    save_state(state)
    if after is None:
        raise StageBError(
            f"Supervisoren bragte ikke {which} tilbage. Kontrollér den planlagte opgave "
            f"{SUPERVISOR_TASK}."
        )
    ok(f"Supervisor genstartede {which} på {restart_ms:.0f} ms (pid {before} -> {after})")


def appliance_root() -> Path:
    """Where the installed appliance lives -- NOT the repo checkout.

    The repo holds the evidence; the appliance holds the exes the updater swaps.
    They are different directories, so ask the running supervisor where it lives
    rather than guessing: whatever process currently supervises the rig is the
    installation this campaign must prove. Explicit --appliance wins.
    """
    if APPLIANCE is not None:
        return APPLIANCE
    script = (
        "$p=Get-Process 'modelrig-supervisor-windows-x64' -ErrorAction SilentlyContinue | "
        "Select-Object -First 1; if($null -eq $p){exit 1}; Write-Output $p.Path"
    )
    try:
        path = Path(powershell(script, timeout=30.0).splitlines()[-1].strip())
        if path.is_file():
            return path.parent
    except (StageBError, IndexError, OSError):
        pass
    return ROOT


def run_updater(log_path: Path, extra: list[str]) -> None:
    """Run the updater in place, tee'ing the complete stdout+stderr."""
    root = appliance_root()
    updater = root / "modelrig-updater-windows-x64.exe"
    if not updater.is_file():
        raise StageBError(
            f"modelrig-updater-windows-x64.exe blev ikke fundet i {root}. Hent den fra "
            "den publicerede release, verificér dens SHA-256 mod SHA256SUMS.txt, og "
            "angiv evt. installationen med --appliance."
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as handle:
        process = subprocess.Popen(
            [str(updater), *extra],
            cwd=updater.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None
        for raw in process.stdout:
            sys.stdout.write(raw.decode("utf-8", "replace"))
            handle.write(raw)
        process.wait()


def trial_good_update(observations: dict[str, Any], state: dict[str, Any]) -> None:
    if state.get("good_update_done"):
        ok("Den gode opdatering er allerede bevist.")
        return
    heading("1/5  AUTOMATISK — gyldig opdatering til den publicerede release")
    candidate = candidate_identity()
    before_versions = live_versions()
    before_data = data_snapshot()
    source_version = before_versions["backend_version"]
    if not source_version:
        raise StageBError("Kunne ikke læse riggens nuværende version fra /healthz.")
    if source_version == candidate["version"]:
        raise StageBError(
            f"Riggen kører allerede {source_version}. Stage B kræver, at den starter på "
            "den FORRIGE release, så updateren har noget at opdatere til."
        )
    note(f"Opdaterer {source_version} -> {candidate['version']} via den rigtige updater.")
    log = EVIDENCE / "good_update.log"
    run_updater(log, [])

    wait_ready()
    after_versions = live_versions()
    after_data = data_snapshot()
    trial = observations["trials"]["good_update"]
    trial.update(
        {
            "performed": True,
            "source_version": source_version,
            "source_git_sha": released_commit(source_version),
            "target_version": candidate["version"],
            "target_git_sha": candidate["git_sha"],
            "target_code_sha256": candidate["code_sha256"],
            "ready": after_versions["backend_version"] == candidate["version"],
            "rollback_observed": "rolling back" in log.read_text(encoding="utf-8", errors="replace").lower(),
            "data_preserved": before_data["documents"] == after_data["documents"],
            "schedules_preserved": (
                before_data["schedules"] == after_data["schedules"]
                and bool(after_data["schedules_binding"])
            ),
            "schedules_binding": after_data["schedules_binding"],
            "notes": "Kørt og målt af stage_b_one_click; hele updater-outputtet er gemt.",
            "evidence_path": "validation/appliance-lifecycle-evidence/good_update.log",
            "evidence_sha256": sha256_file(log),
        }
    )
    save_observations(observations)
    text = log.read_text(encoding="utf-8", errors="replace").lower()
    for marker in ("rolling back", "rollback failed", "manual_recovery", "fatal:"):
        if marker in text:
            raise StageBError(
                f"Den gode opdatering indeholder den forbudte markør {marker!r}. "
                "Ryd op med 'modelrig-updater-windows-x64.exe -recover' (som "
                "administrator) og kør trinnet igen."
            )
    if after_versions["backend_version"] != candidate["version"]:
        raise StageBError(
            f"Opdateringen tog ikke effekt: backend rapporterer stadig "
            f"{after_versions['backend_version'] or '(nede)'}, "
            f"ikke {candidate['version']}. Beviset ville være usandt."
        )
    state["good_update_done"] = True
    save_state(state)
    ok(f"Opdatering gennemført: {source_version} -> {after_versions['backend_version']}")


def trial_bad_update(observations: dict[str, Any], state: dict[str, Any]) -> None:
    if state.get("bad_update_done"):
        ok("Den ugyldige opdatering er allerede bevist.")
        return
    heading("5/5  MANUELT PAUSEPUNKT — ugyldig opdatering")
    bad_repo = os.environ.get("KALIV_STAGE_B_BAD_REPO", "").strip()
    log = EVIDENCE / "bad_update.log"
    candidate = candidate_identity()
    # Name the artifact the refusal was actually aimed at. These used to be read
    # from a state key nothing ever wrote, so they attested as empty strings and
    # the validator rejected the trial.
    attempted_version, attempted_git_sha = ("", "")
    if bad_repo:
        attempted_version, attempted_git_sha = remote_release_identity(bad_repo)
    attempted_version = attempted_version or str(state.get("bad_attempted_version") or "")
    attempted_git_sha = attempted_git_sha or str(state.get("bad_attempted_git_sha") or "")

    if bad_repo:
        note(f"Kører updateren mod {bad_repo}, hvis release bevidst har en forkert checksum.")
        print("  Forventet udfald: 'checksum MISMATCH ... refusing to install' FØR swap.")
        answer = input("  Skriv JA for at køre den ugyldige opdatering: ").strip()
        if answer.upper() != "JA":
            raise StageBError("Den ugyldige opdatering blev ikke godkendt.")
        run_updater(log, ["-repo", bad_repo])
    else:
        print("  Sæt KALIV_STAGE_B_BAD_REPO til et testdepot, hvis seneste release har en")
        print("  bevidst forkert SHA256SUMS.txt, så wizard'en kan køre trinnet selv.")
        print("  Ellers: kør den ugyldige opdatering manuelt og gem HELE outputtet som")
        print(f"  {log}")
        input("\n  Tryk Enter, når loggen ligger der: ")
    if not log.is_file():
        raise StageBError(f"Den ugyldige opdaterings log mangler: {log}")

    text = log.read_text(encoding="utf-8", errors="replace").lower()
    rejected = any(
        marker in text
        for marker in (
            "checksum mismatch",
            "refusing to install",
            "cannot check provenance",
            "no build provenance",
            "has no sha256sums.txt",
        )
    )
    rolled_back = f"rolled back to {candidate['version'].lower()}" in text
    if not rejected and not rolled_back:
        raise StageBError(
            "Loggen beviser hverken en afvisning før swap eller en gennemført rollback."
        )
    after_versions = live_versions()
    after_data = data_snapshot()
    trial = observations["trials"]["bad_update"]
    trial.update(
        {
            "performed": True,
            "attempted_version": attempted_version,
            "attempted_git_sha": attempted_git_sha,
            "rejected_or_rolled_back": True,
            "active_version": after_versions["backend_version"],
            "active_git_sha": candidate["git_sha"],
            "active_code_sha256": candidate["code_sha256"],
            "ready": after_versions["backend_version"] == candidate["version"],
            "data_preserved": after_data["documents"] is not None,
            "schedules_preserved": (
                after_data["schedules"] is not None
                and bool(after_data["schedules_binding"])
            ),
            "schedules_binding": after_data["schedules_binding"],
            "notes": "Afvist før swap" if rejected else "Fuld rollback gennemført",
            "evidence_path": "validation/appliance-lifecycle-evidence/bad_update.log",
            "evidence_sha256": sha256_file(log),
        }
    )
    save_observations(observations)
    state["bad_update_done"] = True
    save_state(state)
    ok("Den ugyldige opdatering blev afvist eller rullet rent tilbage.")


# --- orchestration ---------------------------------------------------------


def preflight() -> dict[str, Any]:
    heading("Preflight — er riggen klar til Stage B?")
    if os.name != "nt":
        raise StageBError("Stage B må kun køres på Windows-riggen.")
    # The updater must stop the KalivSupervisor scheduled task before it swaps
    # exes; without elevation the supervisor restarts the server, the exe stays
    # locked, and BOTH the swap and its rollback fail with "Adgang nægtet",
    # leaving a manual_recovery journal that blocks Stage B outright.
    elevated = powershell(
        "$p=New-Object Security.Principal.WindowsPrincipal("
        "[Security.Principal.WindowsIdentity]::GetCurrent()); "
        "Write-Output $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
        timeout=30.0,
    ).strip().lower()
    if not elevated.startswith("true"):
        raise StageBError(
            "Stage B skal køres som ADMINISTRATOR. Updateren kan ellers ikke stoppe "
            "KalivSupervisor, og både swap og rollback fejler på låste exe-filer."
        )
    if JOURNAL.exists():
        raise StageBError(
            "update-transaction.json findes stadig; en tidligere updater-transaktion er "
            "ikke afsluttet. Kør updateren med -recover først."
        )
    dirty = capture(["git", "status", "--porcelain"])
    if dirty:
        raise StageBError(f"Working tree er ikke ren:\n{dirty}")
    candidate = candidate_identity()
    ok(f"Kandidat {candidate['version']} @ {candidate['git_sha'][:12]}")
    versions = live_versions()
    ok(f"Backend kører {versions['backend_version'] or '(nede)'}")
    ok(f"Worker kører {versions['worker_version'] or '(nede)'}")
    # Both token-backed readings sit behind experimental flags a normal
    # appliance does not set: the worker fingerprint needs KALIV_AGENT3_ENABLED,
    # the schedule count needs KALIV_SCHEDULER_API. The bundle therefore binds
    # the running build to the installed worker exe and the schedule store on
    # disk instead, which need neither. A token only adds the stronger readings
    # on a rig that already exposes them -- it is not required, and its absence
    # no longer lets an unmeasured value pass as an observation.
    if os.environ.get("MODELRIG_TOKEN", "").strip():
        ok("MODELRIG_TOKEN er sat; fingerprint og schedule-API bruges hvis de svarer.")
    else:
        note("MODELRIG_TOKEN er ikke sat; binder mod installeret exe og schedule-lager.")
    exe = installed_worker_exe_sha256()
    if not exe:
        raise StageBError(
            f"Kunne ikke læse {WORKER_ASSET} i {appliance_root() / 'worker'}. "
            "Uden den kan den kørende worker ikke bindes til kandidaten."
        )
    published = released_worker_exe_sha256(candidate["version"])
    if not published:
        raise StageBError(
            f"Kunne ikke hente {WORKER_ASSET}s checksum fra den publicerede "
            f"v{candidate['version']}. Bundlen ville mangle sin worker-binding."
        )
    ok(f"Worker-binding klar (publiceret {published[:16]}…).")
    return candidate


def build_observations(candidate: dict[str, Any]) -> dict[str, Any]:
    if OBSERVATIONS.is_file():
        try:
            existing = json.loads(OBSERVATIONS.read_text(encoding="utf-8-sig"))
            if isinstance(existing, dict) and existing.get("schema") == LIFECYCLE_SCHEMA:
                return existing
        except (OSError, json.JSONDecodeError):
            pass
    observations = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    observations["candidate"] = dict(candidate)
    # What the published release says the worker exe should hash to. The trials
    # compare the installed file against this, so the bundle binds the running
    # build without needing the experimental agent3 route enabled on the rig.
    observations["candidate"]["worker_exe_sha256"] = released_worker_exe_sha256(
        candidate["version"]
    )
    observations["host"] = {
        "hostname": socket.gethostname(),
        "windows_version": platform.platform(),
    }
    observations["started_at"] = datetime.now(timezone.utc).isoformat()
    save_observations(observations)
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "checkout, som evidensen hører til (default: wizardens eget repo). "
            "Brug den udcheckede release, når wizard'en køres fra en nyere worktree."
        ),
    )
    parser.add_argument(
        "--appliance",
        type=Path,
        default=None,
        help=(
            "installationen med de exe'er updateren swapper (default: udledes fra "
            "den koerende supervisor)."
        ),
    )
    args = parser.parse_args(argv)
    if args.appliance is not None:
        global APPLIANCE
        APPLIANCE = args.appliance.resolve()
    if args.root is not None:
        if not (args.root / "VERSION").is_file():
            raise StageBError(f"--root peger ikke på en ModelRig-checkout: {args.root}")
        use_root(args.root)

    os.chdir(ROOT)
    heading("Kaliv Stage B — updater-evidens, letteste vej")
    note(f"Evidens skrives til {ROOT}")
    print("  Wizard'en måler alt, den kan måle, og stopper kun for genstarten og")
    print("  godkendelsen af den ugyldige opdatering.")
    print("  Den kan ikke merge, pushe, tagge, release eller aktivere produktion.")

    candidate = preflight()
    state = load_state()
    observations = build_observations(candidate)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # The update comes FIRST, and everything after it is measured on the
    # installed candidate. The old order (reboot -> supervisor x2 -> update)
    # measured the PREVIOUS release, because the rig is still running it until
    # the update lands -- so every run attested
    # "reboot.backend_version mismatch: expected <candidate>, got <previous>"
    # and no run could ever produce a valid bundle. Reboot and the supervisor
    # restarts are claims about the candidate; they have to happen while the
    # candidate is what is actually running.
    trial_good_update(observations, state)
    trial_reboot(observations, state)
    trial_supervisor(observations, state, "backend", 8080)
    trial_supervisor(observations, state, "worker", 8099)
    trial_bad_update(observations, state)

    observations["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_observations(observations)

    heading("Alle fem lifecycle-observationer er indsamlet")
    print(f"  Observationer: {OBSERVATIONS.relative_to(ROOT)}")
    print("  Verificér nu hele Stage B-bundlen med:")
    print("    VERIFY_STAGE_B_EVIDENCE.cmd")
    print("  production_activation forbliver false.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001 -- the wizard reports, never crashes raw
        print(f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:800]}", file=sys.stderr)
        print(
            "  Intet blev merget, releaset eller aktiveret. Ret problemet og kør igen.",
            file=sys.stderr,
        )
        raise SystemExit(1)
