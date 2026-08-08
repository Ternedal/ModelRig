#!/usr/bin/env python3
"""Authoritative Stage B wizard with source, bootstrap and interruption proof."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import stage_b_one_click as legacy

EXPECTED_SOURCE_VERSION = "1.58.150"
EXPECTED_TARGET_VERSION = "1.58.151"
UPDATER_ASSET = "modelrig-updater-windows-x64.exe"
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _release_asset_sha256(version: str, asset_name: str) -> str:
    tag = version if version.startswith("v") else f"v{version}"
    release = legacy.get_json(
        f"https://api.github.com/repos/{legacy.RELEASE_REPO}/releases/tags/{tag}",
        timeout=20.0,
    )
    assets = release.get("assets") if isinstance(release, dict) else None
    sums_url = ""
    for asset in assets or []:
        if isinstance(asset, dict) and asset.get("name") == "SHA256SUMS.txt":
            sums_url = str(asset.get("browser_download_url") or "")
            break
    if not sums_url:
        raise legacy.StageBError(f"v{version} mangler SHA256SUMS.txt")
    try:
        with urllib.request.urlopen(sums_url, timeout=30.0) as response:
            text = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise legacy.StageBError("Kunne ikke hente release-checksummer") from exc
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[-1].lstrip("*") == asset_name:
            digest = fields[0].lower()
            if _SHA64.fullmatch(digest):
                return digest
    raise legacy.StageBError(f"SHA256SUMS.txt mangler {asset_name}")


def _configure(root: Path | None, appliance: Path | None) -> None:
    if root is not None:
        if not (root / "VERSION").is_file():
            raise legacy.StageBError(f"--root peger ikke på en ModelRig-checkout: {root}")
        legacy.use_root(root)
    if appliance is not None:
        legacy.APPLIANCE = appliance.resolve()


def _load_observations(candidate: dict[str, Any]) -> dict[str, Any]:
    observations = legacy.build_observations(candidate)
    trials = observations.setdefault("trials", {})
    if not isinstance(trials, dict):
        raise legacy.StageBError("Lifecycle trials er ugyldige")
    return observations


def _verify_bootstrap(candidate: dict[str, Any], observations: dict[str, Any], state: dict[str, Any]) -> None:
    resumed = bool(state.get("updater_bootstrap_done"))
    if resumed and not isinstance(observations.get("trials", {}).get("updater_bootstrap"), dict):
        raise legacy.StageBError("Bootstrap-state findes uden bootstrap-evidens")
    if resumed:
        legacy.ok("Updater-bootstrap checkpoint findes; live fil og provenance genverificeres.")
    legacy.heading("STRICT 1/2 — verificér updater-bootstrap")
    if candidate.get("version") != EXPECTED_TARGET_VERSION:
        raise legacy.StageBError(
            f"Stage B v2 er bundet til {EXPECTED_TARGET_VERSION}, ikke {candidate.get('version')}"
        )
    updater = legacy.appliance_root() / UPDATER_ASSET
    if not updater.is_file():
        raise legacy.StageBError(f"Updater-bootstrap mangler: {updater}")
    expected = _release_asset_sha256(EXPECTED_TARGET_VERSION, UPDATER_ASSET)
    actual = legacy.sha256_file(updater)
    if actual != expected:
        raise legacy.StageBError(
            f"Updater-bootstrap hash mismatch: forventet {expected}, fik {actual}"
        )
    command = [
        "gh", "attestation", "verify", str(updater),
        "--repo", legacy.RELEASE_REPO,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=legacy.ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=180.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise legacy.StageBError(
            "GitHub CLI kunne ikke verificere updaterens build provenance"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise legacy.StageBError(f"Updater provenance verification fejlede: {detail[-500:]}")

    log = legacy.EVIDENCE / "updater_binary_check.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    safe_output = (result.stdout or result.stderr or "").replace("\r", " ").strip()
    log.write_text(
        "\n".join(
            (
                f"verified_at={datetime.now(timezone.utc).isoformat()}",
                f"release_version={EXPECTED_TARGET_VERSION}",
                f"release_git_sha={candidate['git_sha']}",
                f"asset_name={UPDATER_ASSET}",
                f"expected_sha256={expected}",
                f"actual_sha256={actual}",
                "provenance_verified=true",
                f"provenance_command={' '.join(command)}",
                f"provenance_output={safe_output[:2000]}",
            )
        ) + "\n",
        encoding="utf-8",
    )
    observations["trials"]["updater_bootstrap"] = {
        "performed": True,
        "release_version": EXPECTED_TARGET_VERSION,
        "release_git_sha": candidate["git_sha"],
        "asset_name": UPDATER_ASSET,
        "expected_sha256": expected,
        "actual_sha256": actual,
        "provenance_verified": True,
        "evidence_path": "validation/appliance-lifecycle-evidence/updater_binary_check.log",
        "evidence_sha256": legacy.sha256_file(log),
    }
    legacy.save_observations(observations)
    state["updater_bootstrap_done"] = True
    legacy.save_state(state)
    legacy.ok(f"Updater-bootstrap bundet til v{EXPECTED_TARGET_VERSION} ({actual[:16]}…)")


def _journal_snapshot(root: Path) -> tuple[str, list[str]]:
    candidates: list[dict[str, Any]] = []
    for path in (root / "update-transaction.json", root / "update-transaction.json.tmp"):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        return "", []
    value = max(candidates, key=lambda item: int(item.get("revision") or 0))
    swapped = value.get("swapped")
    return str(value.get("state") or ""), [str(x) for x in swapped] if isinstance(swapped, list) else []


def _all_live_executables_present(root: Path) -> bool:
    paths = (
        root / "modelrig-server-windows-x64.exe",
        root / "modelrig-supervisor-windows-x64.exe",
        root / "worker" / "modelrig-worker-windows-x64.exe",
        root / UPDATER_ASSET,
    )
    return all(path.is_file() and path.stat().st_size > 0 for path in paths)


def _run_interruption(candidate: dict[str, Any], observations: dict[str, Any], state: dict[str, Any]) -> None:
    if state.get("appliance_interruption_done"):
        if not isinstance(observations.get("trials", {}).get("appliance_interruption"), dict):
            raise legacy.StageBError("Interruption-state findes uden interruption-evidens")
        legacy.ok("Appliance interruption/recovery er allerede bevist.")
        return
    legacy.heading("STRICT 2/2 — kontrolleret interruption efter første swap")
    before = legacy.live_versions()
    if before.get("backend_version") != EXPECTED_SOURCE_VERSION:
        raise legacy.StageBError(
            f"Interruption-testen kræver backend {EXPECTED_SOURCE_VERSION}; "
            f"riggen rapporterer {before.get('backend_version') or '(nede)'}"
        )
    if before.get("worker_version") != EXPECTED_SOURCE_VERSION:
        raise legacy.StageBError(
            f"Interruption-testen kræver worker {EXPECTED_SOURCE_VERSION}; "
            f"riggen rapporterer {before.get('worker_version') or '(nede)'}"
        )
    root = legacy.appliance_root()
    updater = root / UPDATER_ASSET
    log = legacy.EVIDENCE / "appliance_interruption.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as handle:
        process = subprocess.Popen(
            [str(updater)], cwd=root, stdout=handle, stderr=subprocess.STDOUT
        )
        deadline = time.monotonic() + 300.0
        observed_state = ""
        observed_swapped: list[str] = []
        while time.monotonic() < deadline and process.poll() is None:
            observed_state, observed_swapped = _journal_snapshot(root)
            if observed_state == "swapping" and observed_swapped:
                process.kill()
                process.wait(timeout=30.0)
                break
            time.sleep(0.1)
        else:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=30.0)
            raise legacy.StageBError(
                "Updateren nåede ikke journal state=swapping med mindst ét registreret swap"
            )
    killed = process.returncode is not None and process.returncode != 0
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"observed_journal_state={observed_state}\n")
        handle.write(f"observed_swapped_count={len(observed_swapped)}\n")
        handle.write(f"observed_swapped_assets={','.join(observed_swapped)}\n")
        handle.write(f"updater_process_killed={'true' if killed else 'false'}\n")
        recovery = subprocess.run(
            [str(updater), "-recover"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=300.0,
        )
        handle.write("--- recovery stdout ---\n")
        handle.write(recovery.stdout or "")
        handle.write("\n--- recovery stderr ---\n")
        handle.write(recovery.stderr or "")
        handle.write(f"\nrecovery_exit_code={recovery.returncode}\n")

    ready_ms = legacy.wait_ready()
    after = legacy.live_versions()
    live_present = _all_live_executables_present(root)
    journal_absent = not (root / "update-transaction.json").exists() and not (
        root / "update-transaction.json.tmp"
    ).exists()
    recovered = (
        recovery.returncode == 0
        and ready_ms is not None
        and after.get("backend_version") == EXPECTED_SOURCE_VERSION
        and after.get("worker_version") == EXPECTED_SOURCE_VERSION
        and live_present
        and journal_absent
    )
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"recovery_succeeded={'true' if recovered else 'false'}\n")
        handle.write(f"live_executables_present={'true' if live_present else 'false'}\n")
        handle.write(f"journal_absent={'true' if journal_absent else 'false'}\n")
        handle.write(f"backend_version={after.get('backend_version') or ''}\n")
        handle.write(f"worker_version={after.get('worker_version') or ''}\n")

    observations["trials"]["appliance_interruption"] = {
        "performed": True,
        "source_version": EXPECTED_SOURCE_VERSION,
        "observed_journal_state": observed_state,
        "observed_swapped_count": len(observed_swapped),
        "observed_swapped_assets": observed_swapped,
        "updater_process_killed": killed,
        "recovery_exit_code": recovery.returncode,
        "recovery_succeeded": recovered,
        "live_executables_present": live_present,
        "journal_absent": journal_absent,
        "ready": ready_ms is not None,
        "backend_version": after.get("backend_version"),
        "worker_version": after.get("worker_version"),
        "evidence_path": "validation/appliance-lifecycle-evidence/appliance_interruption.log",
        "evidence_sha256": legacy.sha256_file(log),
    }
    legacy.save_observations(observations)
    if not recovered:
        raise legacy.StageBError(
            "Interruption-recovery blev ikke bevist; behold loggen og stop Stage B"
        )
    state["appliance_interruption_done"] = True
    legacy.save_state(state)
    legacy.ok("Mid-swap interruption blev recovered til 1.58.150 med alle live exes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--appliance", type=Path, default=None)
    args = parser.parse_args(argv)
    _configure(args.root, args.appliance)
    os.chdir(legacy.ROOT)

    candidate = legacy.preflight()
    state = legacy.load_state()
    observations = _load_observations(candidate)
    legacy.EVIDENCE.mkdir(parents=True, exist_ok=True)
    _verify_bootstrap(candidate, observations, state)
    if not state.get("good_update_done"):
        _run_interruption(candidate, observations, state)
    elif not state.get("appliance_interruption_done"):
        raise legacy.StageBError(
            "Good update er allerede gennemført uden det obligatoriske interruption-bevis; "
            "gendan source 1.58.150 og start kampagnen forfra."
        )

    forwarded: list[str] = []
    if args.root is not None:
        forwarded.extend(["--root", str(args.root)])
    if args.appliance is not None:
        forwarded.extend(["--appliance", str(args.appliance)])
    return legacy.main(forwarded)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nSIKKERT STOP: afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"\nSIKKERT STOP: {type(exc).__name__}: {str(exc)[:800]}", file=sys.stderr)
        print("Ingen release eller produktion blev aktiveret.", file=sys.stderr)
        raise SystemExit(1)
