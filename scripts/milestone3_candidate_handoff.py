#!/usr/bin/env python3
"""Build an offline, exact-head Milestone 3 physical-candidate handoff kit.

The kit contains a verified Git bundle, the exact Android debug APK, the Windows
Compose uber-jar, a bootstrap launcher, and SHA-256 metadata. It is deliberately
local-only: no push, tag, release, upload, merge, or production activation exists
in this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "agent/milestone3-physical-candidate-v1"
VERSION = "1.58.146"
SCHEMA = "kaliv-milestone3-candidate-handoff/v1"
DEFAULT_OUTPUT = ROOT / "handoff"
ANDROID_APK = (
    ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
)
DESKTOP_JARS = ROOT / "desktop" / "composeApp" / "build" / "compose" / "jars"
MAX_ARTIFACT_BYTES = 1_500_000_000


class HandoffError(RuntimeError):
    pass


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(
    args: list[str],
    *,
    cwd: Path = ROOT,
    capture: bool = False,
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=os.environ.copy(),
            text=True,
            capture_output=capture,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HandoffError(f"cannot run {args[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "")[-2000:] if capture else ""
        raise HandoffError(
            f"command failed ({result.returncode}): {' '.join(args)}"
            + (f"\n{detail}" if detail else "")
        )
    return result


def git(*args: str, capture: bool = True) -> str:
    return run(["git", *args], capture=capture).stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def ensure_candidate() -> dict[str, Any]:
    if shutil.which("git") is None:
        raise HandoffError("git is required to build the offline candidate bundle")
    branch = git("branch", "--show-current")
    sha = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain=v1")
    if branch != BRANCH:
        raise HandoffError(f"wrong branch: expected {BRANCH}, got {branch or '<detached>'}")
    if dirty:
        raise HandoffError("working tree is not clean; handoff must bind committed bytes only")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != VERSION:
        raise HandoffError(f"VERSION mismatch: expected {VERSION}, got {version}")
    run([sys.executable, str(ROOT / "scripts" / "version_tool.py"), "check"])
    return {
        "version": version,
        "git_sha": sha,
        "branch": branch,
        "working_tree_clean": True,
    }


def gradle_wrapper(project: Path) -> Path:
    candidate = project / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not candidate.is_file():
        raise HandoffError(f"Gradle wrapper is missing: {candidate}")
    return candidate


def build_artifacts() -> tuple[Path, Path]:
    android_gradle = gradle_wrapper(ROOT / "android")
    desktop_gradle = gradle_wrapper(ROOT / "desktop")
    run(
        [str(android_gradle), ":app:assembleDebug", "--no-daemon", "--console=plain"],
        cwd=ROOT / "android",
    )
    if not ANDROID_APK.is_file() or ANDROID_APK.stat().st_size <= 0:
        raise HandoffError(f"Android APK was not produced: {ANDROID_APK}")

    run(
        [
            str(desktop_gradle),
            ":composeApp:packageUberJarForCurrentOS",
            "--no-daemon",
            "--console=plain",
        ],
        cwd=ROOT / "desktop",
    )
    jars = sorted(
        (path for path in DESKTOP_JARS.glob("*.jar") if path.is_file()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if len(jars) != 1:
        raise HandoffError(
            f"expected exactly one packaged desktop jar in {DESKTOP_JARS}; found {len(jars)}"
        )
    if jars[0].stat().st_size <= 0:
        raise HandoffError("desktop jar is empty")
    return ANDROID_APK, jars[0]


def checked_artifact(path: Path, relative: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HandoffError(f"artifact is missing or irregular: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise HandoffError(f"artifact size is invalid: {path} ({size})")
    return {
        "path": relative.as_posix(),
        "sha256": sha256_file(path),
        "bytes": size,
    }


def write_bootstrap(path: Path, *, sha: str, bundle_name: str) -> None:
    destination = f"ModelRig-Milestone3-{sha[:12]}"
    text = f"""@echo off\r
setlocal\r
cd /d "%~dp0"\r
\r
where git >nul 2>nul\r
if errorlevel 1 (\r
  echo FEJL: git blev ikke fundet paa PATH.\r
  pause\r
  exit /b 1\r
)\r
\r
set "EXPECTED_SHA={sha}"\r
set "EXPECTED_BRANCH={BRANCH}"\r
set "BUNDLE={bundle_name}"\r
set "DEST={destination}"\r
\r
if exist "%DEST%" (\r
  echo FEJL: %DEST% findes allerede. Flyt eller slet den bevidst foerst.\r
  pause\r
  exit /b 1\r
)\r
\r
git bundle verify "%BUNDLE%"\r
if errorlevel 1 goto fail\r
git clone "%BUNDLE%" "%DEST%"\r
if errorlevel 1 goto fail\r
cd /d "%DEST%"\r
git checkout "%EXPECTED_BRANCH%"\r
if errorlevel 1 goto fail\r
for /f %%S in ('git rev-parse HEAD') do set "ACTUAL_SHA=%%S"\r
if /I not "%ACTUAL_SHA%"=="%EXPECTED_SHA%" (\r
  echo FEJL: Klonet SHA matcher ikke handoff-manifestet.\r
  goto fail\r
)\r
for /f "delims=" %%D in ('git status --porcelain') do (\r
  echo FEJL: Den klonede kandidat er ikke ren: %%D\r
  goto fail\r
)\r
call START_MILESTONE3_PHYSICAL.cmd\r
exit /b %ERRORLEVEL%\r
\r
:fail\r
echo.\r
echo Handoff-bootstrap stoppede sikkert. Ingen release eller aktivering blev udfoert.\r
pause\r
exit /b 1\r
"""
    path.write_bytes(text.encode("utf-8"))


def create_bundle(path: Path) -> None:
    run(["git", "bundle", "create", str(path), BRANCH])
    run(["git", "bundle", "verify", str(path)], capture=True)


def write_readme(path: Path, *, sha: str) -> None:
    atomic_text(
        path,
        f"""Kaliv / ModelRig Milestone 3 physical candidate handoff

Version: {VERSION}
Branch: {BRANCH}
Commit: {sha}

1. Copy this entire folder to the Windows rig.
2. Verify SHA256SUMS.txt if the folder crossed an untrusted medium.
3. Double-click START_HERE.cmd.
4. The bootstrap verifies the Git bundle, clones the exact candidate, checks the
   exact SHA and clean tree, then starts START_MILESTONE3_PHYSICAL.cmd.

artifacts/android contains the exact debug APK built from this candidate.
artifacts/desktop contains the exact Windows Compose uber-jar.
The physical operator may rebuild them and must still collect real device evidence.

This handoff does not merge, publish, release, upload or activate production.
""",
    )


def write_sums(path: Path, files: list[Path], base: Path) -> None:
    lines = [
        f"{sha256_file(item)}  {item.relative_to(base).as_posix()}"
        for item in sorted(files, key=lambda value: value.relative_to(base).as_posix())
    ]
    atomic_text(path, "\n".join(lines) + "\n")


def zip_directory(source: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source.parent).as_posix())
    with zipfile.ZipFile(temporary, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise HandoffError(f"ZIP verification failed at {bad}")
    temporary.replace(destination)


def build_handoff(output_root: Path) -> tuple[Path, dict[str, Any]]:
    identity = ensure_candidate()
    sha = str(identity["git_sha"])
    apk, jar = build_artifacts()
    output_root.mkdir(parents=True, exist_ok=True)
    final_dir = output_root / f"ModelRig-Milestone3-{VERSION}-{sha[:12]}"
    final_zip = output_root / f"ModelRig-Milestone3-{VERSION}-{sha[:12]}.zip"
    if final_dir.exists() or final_zip.exists():
        raise HandoffError("handoff destination already exists; archive or remove it deliberately")

    staging = Path(tempfile.mkdtemp(prefix="milestone3-handoff-", dir=output_root))
    try:
        kit = staging / final_dir.name
        artifacts_android = kit / "artifacts" / "android"
        artifacts_desktop = kit / "artifacts" / "desktop"
        artifacts_android.mkdir(parents=True)
        artifacts_desktop.mkdir(parents=True)

        bundle = kit / f"ModelRig-Milestone3-{sha[:12]}.bundle"
        create_bundle(bundle)
        copied_apk = artifacts_android / f"kaliv-{VERSION}-{sha[:12]}-debug.apk"
        copied_jar = artifacts_desktop / f"kaliv-desktop-{VERSION}-{sha[:12]}.jar"
        shutil.copy2(apk, copied_apk)
        shutil.copy2(jar, copied_jar)
        bootstrap = kit / "START_HERE.cmd"
        readme = kit / "README.txt"
        write_bootstrap(bootstrap, sha=sha, bundle_name=bundle.name)
        write_readme(readme, sha=sha)

        manifest_path = kit / "candidate-manifest.json"
        manifest = {
            "schema": SCHEMA,
            "generated_at": iso_now(),
            "candidate": identity,
            "artifacts": {
                "git_bundle": checked_artifact(bundle, bundle.relative_to(kit)),
                "android_apk": checked_artifact(copied_apk, copied_apk.relative_to(kit)),
                "desktop_jar": checked_artifact(copied_jar, copied_jar.relative_to(kit)),
                "bootstrap": checked_artifact(bootstrap, bootstrap.relative_to(kit)),
                "readme": checked_artifact(readme, readme.relative_to(kit)),
            },
            "physical_evidence_collected": False,
            "published": False,
            "production_activation": False,
        }
        atomic_json(manifest_path, manifest)
        sums = kit / "SHA256SUMS.txt"
        write_sums(
            sums,
            [bundle, copied_apk, copied_jar, bootstrap, readme, manifest_path],
            kit,
        )

        kit.replace(final_dir)
        zip_directory(final_dir, final_zip)
        return final_zip, manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        archive, manifest = build_handoff(args.output.expanduser().resolve())
    except (HandoffError, OSError) as exc:
        print(f"Milestone 3 handoff: BLOCKED — {exc}", file=sys.stderr)
        return 2
    print(f"Milestone 3 handoff: READY — {archive}")
    print(f"candidate: {manifest['candidate']['git_sha']}")
    print("physical_evidence_collected=false")
    print("production_activation=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
