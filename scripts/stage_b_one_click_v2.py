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
import stage_b_physical_gate_v2 as final_gate

# The released predecessor of the target, which is 1.58.149 -- not 1.58.150.
#
# 1.58.150 was bumped but never validated or published: GitHub Actions was down
# for the whole evening its candidate was prepared, so it never got four green
# workflows and was never promoted. The version moved on to 1.58.151, and this
# constant was written against a predecessor that does not exist. There is no
# v1.58.150 release, tag or draft to install a source appliance from, so Stage B
# could not start at all: the wrapper demands backend and worker on exactly the
# source version, and no such build was ever produced.
#
# Nothing about the proof changes. 1.58.149's updater also predates self-update,
# so the manual bootstrap of the 1.58.151 updater is required for the same
# reason, and 1.58.149 -> 1.58.151 is a genuine transition between two signed
# releases.
EXPECTED_SOURCE_VERSION = "2.0.10"
EXPECTED_TARGET_VERSION = "2.0.11"
UPDATER_ASSET = "modelrig-updater-windows-x64.exe"
SOURCE_REF = f"refs/tags/v{EXPECTED_TARGET_VERSION}"
SIGNER_WORKFLOW = (
    f"{legacy.RELEASE_REPO}/.github/workflows/build-and-release.yml"
)
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
        if (
            isinstance(asset, dict)
            and asset.get("name") == "SHA256SUMS.txt"
        ):
            sums_url = str(asset.get("browser_download_url") or "")
            break
    if not sums_url:
        raise legacy.StageBError(f"v{version} mangler SHA256SUMS.txt")
    try:
        with urllib.request.urlopen(sums_url, timeout=30.0) as response:
            text = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise legacy.StageBError(
            "Kunne ikke hente release-checksummer"
        ) from exc
    for line in text.splitlines():
        fields = line.split()
        if (
            len(fields) >= 2
            and fields[-1].lstrip("*") == asset_name
        ):
            digest = fields[0].lower()
            if _SHA64.fullmatch(digest):
                return digest
    raise legacy.StageBError(
        f"SHA256SUMS.txt mangler {asset_name}"
    )


def _configure(
    root: Path | None,
    appliance: Path | None,
) -> None:
    if root is not None:
        if not (root / "VERSION").is_file():
            raise legacy.StageBError(
                f"--root peger ikke på en ModelRig-checkout: {root}"
            )
        legacy.use_root(root)
    if appliance is not None:
        legacy.APPLIANCE = appliance.resolve()


def _load_observations(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    observations = legacy.build_observations(candidate)
    trials = observations.setdefault("trials", {})
    if not isinstance(trials, dict):
        raise legacy.StageBError("Lifecycle trials er ugyldige")
    return observations


def _invalidate_final_receipt() -> None:
    # The official latest receipt is an activation input. Block it BEFORE
    # persisting the false bootstrap tombstone, so no interruption can leave
    # false state alongside a stale green final receipt. The final-gate writer
    # uses temp-file + replace; if that fails, remove the old receipt and stop.
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    destination = legacy.ROOT / final_gate.DEFAULT_REPORT
    report = final_gate._blocked_receipt(
        now,
        "bootstrap live re-verification required; no prior green receipt is current",
        status="bootstrap_reverification_required",
    )
    try:
        final_gate._write(destination, report)
    except Exception as exc:
        cleanup_error: Exception | None = None
        try:
            destination.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            cleanup_error = cleanup_exc
        detail = f"Final Stage B receipt could not be invalidated: {exc}"
        if cleanup_error is not None:
            detail += f"; stale receipt could not be removed: {cleanup_error}"
        raise legacy.StageBError(detail) from exc


def _verify_bootstrap(
    candidate: dict[str, Any],
    observations: dict[str, Any],
    state: dict[str, Any],
) -> None:
    resumed = bool(state.get("updater_bootstrap_done"))
    trials = observations.get("trials")
    if not isinstance(trials, dict):
        raise legacy.StageBError("Lifecycle trials er ugyldige")

    cached_trial = trials.get("updater_bootstrap")
    if resumed and not isinstance(cached_trial, dict):
        # A true checkpoint without its proof is never authority. Recover by
        # persisting false first, then continue with a full live verification.
        legacy.ok(
            "Bootstrap-checkpoint mangler sit proof; "
            "checkpoint nulstilles og live fil genverificeres."
        )
        resumed = False
    elif resumed:
        legacy.ok(
            "Updater-bootstrap checkpoint findes; cached proof "
            "ugyldiggøres og live fil genverificeres."
        )

    # Block the official latest receipt before persisting the false checkpoint.
    # Interruption after this write leaves the old state/trial but no green
    # receipt; interruption after save_state leaves false state + blocked receipt.
    _invalidate_final_receipt()

    # Persist the false checkpoint BEFORE deleting the cached trial. Every
    # interruption ordering is then resumable:
    # - stop here: false checkpoint + old trial (old trial is ignored);
    # - stop after trial save: false checkpoint + no trial.
    state["updater_bootstrap_done"] = False
    legacy.save_state(state)
    trials.pop("updater_bootstrap", None)
    legacy.save_observations(observations)

    log = legacy.EVIDENCE / "updater_binary_check.log"
    try:
        log.unlink(missing_ok=True)
    except OSError as exc:
        raise legacy.StageBError(
            f"Gammel bootstrap-log kunne ikke fjernes: {exc}"
        ) from exc

    legacy.heading("STRICT 1/2 — verificér updater-bootstrap")
    if candidate.get("version") != EXPECTED_TARGET_VERSION:
        raise legacy.StageBError(
            f"Stage B v2 er bundet til {EXPECTED_TARGET_VERSION}, "
            f"ikke {candidate.get('version')}"
        )
    source_digest = str(candidate.get("git_sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", source_digest):
        raise legacy.StageBError(
            "Kandidatens release Git-SHA er ugyldig"
        )
    updater = legacy.appliance_root() / UPDATER_ASSET
    if not updater.is_file():
        raise legacy.StageBError(
            f"Updater-bootstrap mangler: {updater}"
        )
    expected = _release_asset_sha256(
        EXPECTED_TARGET_VERSION,
        UPDATER_ASSET,
    )
    actual = legacy.sha256_file(updater)
    if actual != expected:
        raise legacy.StageBError(
            f"Updater-bootstrap hash mismatch: "
            f"forventet {expected}, fik {actual}"
        )
    command = [
        "gh",
        "attestation",
        "verify",
        str(updater),
        "--repo",
        legacy.RELEASE_REPO,
        "--source-digest",
        source_digest,
        "--source-ref",
        SOURCE_REF,
        "--signer-workflow",
        SIGNER_WORKFLOW,
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
            "GitHub CLI kunne ikke verificere updaterens "
            "releasebundne build provenance"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise legacy.StageBError(
            f"Updater provenance verification fejlede: "
            f"{detail[-500:]}"
        )

    log.parent.mkdir(parents=True, exist_ok=True)
    safe_output = (
        result.stdout or result.stderr or ""
    ).replace("\r", " ").strip()
    log.write_text(
        "\n".join(
            (
                f"verified_at={datetime.now(timezone.utc).isoformat()}",
                f"release_version={EXPECTED_TARGET_VERSION}",
                f"release_git_sha={source_digest}",
                f"asset_name={UPDATER_ASSET}",
                f"expected_sha256={expected}",
                f"actual_sha256={actual}",
                f"source_digest={source_digest}",
                f"source_ref={SOURCE_REF}",
                f"signer_workflow={SIGNER_WORKFLOW}",
                "provenance_verified=true",
                f"provenance_command={' '.join(command)}",
                f"provenance_output={safe_output[:2000]}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    trials["updater_bootstrap"] = {
        "performed": True,
        "release_version": EXPECTED_TARGET_VERSION,
        "release_git_sha": source_digest,
        "asset_name": UPDATER_ASSET,
        "expected_sha256": expected,
        "actual_sha256": actual,
        "source_digest": source_digest,
        "source_ref": SOURCE_REF,
        "signer_workflow": SIGNER_WORKFLOW,
        "provenance_verified": True,
        "evidence_path": (
            "validation/appliance-lifecycle-evidence/"
            "updater_binary_check.log"
        ),
        "evidence_sha256": legacy.sha256_file(log),
    }
    legacy.save_observations(observations)
    state["updater_bootstrap_done"] = True
    legacy.save_state(state)
    legacy.ok(
        f"Updater-bootstrap bundet til v{EXPECTED_TARGET_VERSION} "
        f"({actual[:16]}…)"
    )


def _read_journal_file(
    path: Path,
) -> dict[str, Any] | None:
    try:
        body = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise legacy.StageBError(
            f"Journalen kan ikke læses: {path}: {exc}"
        ) from exc
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise legacy.StageBError(
            f"Journalen er ugyldig JSON: {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise legacy.StageBError(
            f"Journalen er ikke et objekt: {path}"
        )
    tx_id = value.get("id")
    revision = value.get("revision")
    state = value.get("state")
    swapped = value.get("swapped")
    if not isinstance(tx_id, str) or not tx_id.strip():
        raise legacy.StageBError(
            f"Journalen mangler transaction id: {path}"
        )
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
    ):
        raise legacy.StageBError(
            f"Journalen har ugyldig revision: {path}"
        )
    if not isinstance(state, str) or not state:
        raise legacy.StageBError(
            f"Journalen har ugyldig state: {path}"
        )
    if swapped is None:
        swapped = []
    if (
        not isinstance(swapped, list)
        or not all(isinstance(item, str) for item in swapped)
    ):
        raise legacy.StageBError(
            f"Journalen har ugyldig swapped-liste: {path}"
        )
    return {
        "id": tx_id,
        "revision": revision,
        "state": state,
        "swapped": list(swapped),
        "from": str(value.get("from") or ""),
        "to": str(value.get("to") or ""),
    }


def _journal_snapshot(
    root: Path,
    *,
    include_tmp: bool = True,
) -> dict[str, Any] | None:
    """Read the updater's journal.

    include_tmp=False while the updater is RUNNING, and here is why.

    The updater writes its journal atomically: write update-transaction.json.tmp,
    then rename it over update-transaction.json. On Windows a rename fails if any
    process holds the source open -- and this function opened the .tmp file every
    100 ms during the interruption poll. Sooner or later the read landed inside
    the rename window and the updater died on

        FATAL: rename ...json.tmp ...json: Processen kan ikke faa adgang til
        filen, da den bruges af en anden proces.

    before it ever reached state=swapping. The interruption test then failed with
    "naaede ikke en ny journal i state=swapping" -- reporting the updater as at
    fault for something the observer caused. Observed on the rig; the updater had
    already completed download, checksums and provenance.

    The main/.tmp consistency check is still worth having, so it stays for the
    before-and-after calls where nothing is writing.
    """
    main = _read_journal_file(
        root / "update-transaction.json"
    )
    if not include_tmp:
        return main
    temporary = _read_journal_file(
        root / "update-transaction.json.tmp"
    )
    if main is None:
        return temporary
    if temporary is None:
        return main
    if main["id"] != temporary["id"]:
        raise legacy.StageBError(
            "Journal main og .tmp beskriver forskellige transaktioner"
        )
    if main["revision"] > temporary["revision"]:
        return main
    if temporary["revision"] > main["revision"]:
        return temporary
    if main != temporary:
        raise legacy.StageBError(
            "Journal main og .tmp har samme revision "
            "men forskelligt indhold"
        )
    return main


def _require_no_active_journal(root: Path) -> None:
    present = [
        path.name
        for path in (
            root / "update-transaction.json",
            root / "update-transaction.json.tmp",
        )
        if path.exists()
    ]
    if present:
        raise legacy.StageBError(
            "Interruption-testen kræver ingen aktiv journal "
            "før launch; fundet: "
            + ", ".join(present)
        )


def _all_live_executables_present(root: Path) -> bool:
    paths = (
        root / "modelrig-server-windows-x64.exe",
        root / "modelrig-supervisor-windows-x64.exe",
        root / "worker" / "modelrig-worker-windows-x64.exe",
        root / UPDATER_ASSET,
    )
    return all(
        path.is_file() and path.stat().st_size > 0
        for path in paths
    )


def _run_interruption(
    candidate: dict[str, Any],
    observations: dict[str, Any],
    state: dict[str, Any],
) -> None:
    if state.get("appliance_interruption_done"):
        if not isinstance(
            observations.get("trials", {}).get(
                "appliance_interruption"
            ),
            dict,
        ):
            raise legacy.StageBError(
                "Interruption-state findes uden interruption-evidens"
            )
        legacy.ok(
            "Appliance interruption/recovery er allerede bevist."
        )
        return
    legacy.heading(
        "STRICT 2/2 — kontrolleret interruption efter første swap"
    )
    before = legacy.live_versions()
    if before.get("backend_version") != EXPECTED_SOURCE_VERSION:
        raise legacy.StageBError(
            f"Interruption-testen kræver backend "
            f"{EXPECTED_SOURCE_VERSION}; riggen rapporterer "
            f"{before.get('backend_version') or '(nede)'}"
        )
    if before.get("worker_version") != EXPECTED_SOURCE_VERSION:
        raise legacy.StageBError(
            f"Interruption-testen kræver worker "
            f"{EXPECTED_SOURCE_VERSION}; riggen rapporterer "
            f"{before.get('worker_version') or '(nede)'}"
        )
    root = legacy.appliance_root()
    _require_no_active_journal(root)
    updater = root / UPDATER_ASSET
    log = legacy.EVIDENCE / "appliance_interruption.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    observed: dict[str, Any] | None = None
    observed_id = ""
    observed_revision = 0
    process: subprocess.Popen[bytes] | None = None
    try:
        with log.open("wb") as handle:
            process = subprocess.Popen(
                [str(updater)],
                cwd=root,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + 300.0
            while (
                time.monotonic() < deadline
                and process.poll() is None
            ):
                # Never touch the .tmp file while the updater is writing it:
                # an open handle makes its atomic rename fail on Windows.
                snapshot = _journal_snapshot(root, include_tmp=False)
                if snapshot is not None:
                    if not observed_id:
                        observed_id = str(snapshot["id"])
                        if (
                            snapshot.get("from")
                            != EXPECTED_SOURCE_VERSION
                        ):
                            raise legacy.StageBError(
                                "Den nye journal har forkert "
                                "source-version"
                            )
                        if (
                            str(snapshot.get("to") or "").lstrip("v")
                            != EXPECTED_TARGET_VERSION
                        ):
                            raise legacy.StageBError(
                                "Den nye journal har forkert "
                                "target-version"
                            )
                    elif snapshot["id"] != observed_id:
                        raise legacy.StageBError(
                            "Transaction id skiftede under "
                            "interruption-testen"
                        )
                    if snapshot["revision"] < observed_revision:
                        raise legacy.StageBError(
                            "Journalrevision gik baglæns under "
                            "interruption-testen"
                        )
                    observed_revision = int(snapshot["revision"])
                    observed = snapshot
                    if (
                        snapshot["state"] == "swapping"
                        and snapshot["swapped"]
                    ):
                        process.kill()
                        process.wait(timeout=30.0)
                        break
                time.sleep(0.1)
            else:
                raise legacy.StageBError(
                    "Updateren nåede ikke en ny journal i "
                    "state=swapping med mindst ét registreret swap"
                )
    except BaseException:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=30.0)
        raise
    if process is None or observed is None:
        raise legacy.StageBError(
            "Interruption-process eller journalobservation mangler"
        )
    killed = (
        process.returncode is not None
        and process.returncode != 0
    )
    process_pid = int(getattr(process, "pid", 0) or 0)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            f"observed_transaction_id={observed_id}\n"
        )
        handle.write(
            f"observed_revision={observed_revision}\n"
        )
        handle.write(
            f"observed_journal_from="
            f"{observed.get('from') or ''}\n"
        )
        handle.write(
            f"observed_journal_to="
            f"{observed.get('to') or ''}\n"
        )
        handle.write(
            f"observed_journal_state="
            f"{observed.get('state') or ''}\n"
        )
        handle.write(
            f"observed_swapped_count="
            f"{len(observed.get('swapped') or [])}\n"
        )
        handle.write(
            f"observed_swapped_assets="
            f"{','.join(observed.get('swapped') or [])}\n"
        )
        handle.write(
            f"updater_process_pid={process_pid}\n"
        )
        handle.write(
            f"updater_process_killed="
            f"{'true' if killed else 'false'}\n"
        )
        # Clear the lock the killed updater stranded, exactly as an operator
        # would after a crash.
        #
        # The single-instance lock is created with O_EXCL and released on a
        # clean exit. Killing the process mid-swap -- which this test does on
        # purpose -- leaves it behind, and the next run refuses to start:
        #
        #     another updater appears to be running (pid N started ...) --
        #     lock ...updater.lock exists. If it crashed, delete the lock file
        #     and rerun
        #
        # That refusal is deliberate (see lock.go: failing closed beats guessing
        # staleness), and it is also the documented remedy. So the test performs
        # the documented remedy and records that it did, rather than pretending
        # recovery is automatic. Only the lock is removed -- never the journal,
        # which is the thing recovery has to act on.
        lock_path = root / "updater.lock"
        lock_body = ""
        if lock_path.exists():
            lock_body = lock_path.read_text(encoding="utf-8", errors="replace").strip()
            lock_path.unlink()
        handle.write(
            f"stranded_lock_cleared={'true' if lock_body else 'false'}\n"
        )
        if lock_body:
            handle.write(f"stranded_lock_contents={lock_body}\n")
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
        handle.write(
            f"\nrecovery_exit_code={recovery.returncode}\n"
        )

    ready_ms = legacy.wait_ready()
    after = legacy.live_versions()
    live_present = _all_live_executables_present(root)
    journal_absent = (
        not (root / "update-transaction.json").exists()
        and not (root / "update-transaction.json.tmp").exists()
    )
    recovered = (
        recovery.returncode == 0
        and ready_ms is not None
        and after.get("backend_version")
        == EXPECTED_SOURCE_VERSION
        and after.get("worker_version")
        == EXPECTED_SOURCE_VERSION
        and live_present
        and journal_absent
    )
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            f"recovery_succeeded="
            f"{'true' if recovered else 'false'}\n"
        )
        handle.write(
            f"live_executables_present="
            f"{'true' if live_present else 'false'}\n"
        )
        handle.write(
            f"journal_absent="
            f"{'true' if journal_absent else 'false'}\n"
        )
        handle.write(
            f"backend_version="
            f"{after.get('backend_version') or ''}\n"
        )
        handle.write(
            f"worker_version="
            f"{after.get('worker_version') or ''}\n"
        )

    observations["trials"]["appliance_interruption"] = {
        "performed": True,
        "source_version": EXPECTED_SOURCE_VERSION,
        "observed_transaction_id": observed_id,
        "observed_revision": observed_revision,
        "observed_journal_from": observed.get("from"),
        "observed_journal_to": observed.get("to"),
        "observed_journal_state": observed.get("state"),
        "observed_swapped_count": len(
            observed.get("swapped") or []
        ),
        "observed_swapped_assets": list(
            observed.get("swapped") or []
        ),
        "updater_process_pid": process_pid,
        "updater_process_killed": killed,
        "recovery_exit_code": recovery.returncode,
        "recovery_succeeded": recovered,
        "live_executables_present": live_present,
        "journal_absent": journal_absent,
        "ready": ready_ms is not None,
        "backend_version": after.get("backend_version"),
        "worker_version": after.get("worker_version"),
        "evidence_path": (
            "validation/appliance-lifecycle-evidence/"
            "appliance_interruption.log"
        ),
        "evidence_sha256": legacy.sha256_file(log),
    }
    legacy.save_observations(observations)
    if not recovered:
        raise legacy.StageBError(
            "Interruption-recovery blev ikke bevist; "
            "behold loggen og stop Stage B"
        )
    state["appliance_interruption_done"] = True
    legacy.save_state(state)
    legacy.ok(
        "Mid-swap interruption blev recovered til "
        f"{EXPECTED_SOURCE_VERSION} med alle live exes"
    )


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
            "Good update er allerede gennemført uden det "
            "obligatoriske interruption-bevis; gendan source "
            f"{EXPECTED_SOURCE_VERSION} og start kampagnen forfra."
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
        print(
            "\nSIKKERT STOP: afbrudt af operatøren.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\nSIKKERT STOP: {type(exc).__name__}: "
            f"{str(exc)[:800]}",
            file=sys.stderr,
        )
        print(
            "Ingen release eller produktion blev aktiveret.",
            file=sys.stderr,
        )
        raise SystemExit(1)
