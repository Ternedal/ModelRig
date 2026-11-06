"""Collect the rig qualification reports into one machine-readable evidence manifest (#2296 C3).

    python scripts/media_rig_evidence.py --repo <qual worktree> --out <$Out> [--expect-sha <40 hex>]

Reads every report-*.json the harness (scripts/media_rig_qualification.py) wrote to --out and
writes evidence-manifest-<stamp>.json next to them:

- the qualified SHA (git HEAD of --repo) and whether every report was produced at that SHA;
- per report: file name and SHA-256, mode, profile, result, its own head, the failed checks by
  name, and the measurements a reviewer needs (load/render seconds, cleanup, sqlite version...);
- facts about this machine that the harness cannot fake: OS, Python, nvidia-smi's GPU list and
  driver, and the media volume's file system (Windows: GetVolumeInformationW);
- a summary: which modes passed, which failed, which expected modes are missing.

It reads reports only. It never reads the job databases (they hold prompts) and writes nothing
but the manifest. A PASS in the manifest is only what the reports say; it is evidence for review,
not a qualification decision.

Exit code 0 = every report passed and all were made at the qualified SHA; 1 = otherwise; 2 = usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = "kaliv-media-rig-evidence/v1"
# What the runbook expects (#2296 6642831318). R12/R13 and the optional steps may be absent.
EXPECTED_MODES = ("image", "executor", "pins", "video", "lease")
OPTIONAL_MODES = ("chatfirst", "remount", "bench")
_MEASUREMENTS = ("load_seconds", "render_seconds", "start_seconds", "cleanup", "sqlite_version", "gpu_uuid",
                 "comfyui_version", "comfyui_version_pin", "template_sha256", "weight_pins", "revision", "task",
                 "free_vram_mib_before", "profile_needs_mib", "job_id", "exit_codes", "cells", "matrix_sha256", "fps")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _volume_filesystem(path: Path) -> str | None:
    """NTFS/ReFS/exFAT... for the volume holding path (Windows); the mount's type elsewhere."""
    if os.name == "nt":
        import ctypes
        root = os.path.splitdrive(str(path.resolve()))[0] + "\\"
        name = ctypes.create_unicode_buffer(64)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), None, 0, None, None, None,
                                                          name, len(name))
        return name.value if ok else None
    best, kind = "", None
    try:
        with open("/proc/mounts", encoding="utf-8") as mounts:
            for line in mounts:
                parts = line.split()
                if len(parts) >= 3 and str(path.resolve()).startswith(parts[1]) and len(parts[1]) > len(best):
                    best, kind = parts[1], parts[2]
    except OSError:
        return None
    return kind


def _report_entry(path: Path) -> dict:
    entry = {"file": path.name, "sha256": _sha256(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        entry.update(result="UNREADABLE", error=type(exc).__name__)
        return entry
    checks = data.get("checks") if isinstance(data.get("checks"), dict) else {}
    entry.update(
        mode=data.get("mode"), profile=data.get("profile"), result=data.get("result"), head=data.get("head"),
        started=data.get("started"), checks=len(checks),
        failed_checks=sorted(name for name, item in checks.items() if not (isinstance(item, dict) and item.get("ok"))),
        measurements={key: data[key] for key in _MEASUREMENTS if key in data},
    )
    return entry


def build_manifest(repo: Path, out: Path, expect_sha: str | None) -> dict:
    head = _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    reports = [_report_entry(path) for path in sorted(out.glob("report-*.json"))]
    passed = sorted({r["mode"] for r in reports if r.get("result") == "PASS" and r.get("mode")})
    failed = sorted({r["mode"] for r in reports if r.get("result") != "PASS" and r.get("mode")})
    seen = {r.get("mode") for r in reports}
    heads = {r.get("head") for r in reports if r.get("head")}
    return {
        "schema": SCHEMA,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "qualified_sha": head,
        "expected_sha": expect_sha,
        "expected_sha_matches": (head == expect_sha) if expect_sha else None,
        "all_reports_at_qualified_sha": bool(reports) and heads == {head},
        "host": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "gpus": _run(["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,driver_version",
                          "--format=csv,noheader"]),
            "media_volume_filesystem": _volume_filesystem(out),
        },
        "reports": reports,
        "summary": {
            "modes_passed": passed,
            "modes_with_a_failure": failed,
            "expected_modes_missing": [m for m in EXPECTED_MODES if m not in seen],
            "optional_modes_run": [m for m in OPTIONAL_MODES if m in seen],
            "reports": len(reports),
            "reports_failed": sum(1 for r in reports if r.get("result") != "PASS"),
        },
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="the qualification worktree ($Qual)")
    parser.add_argument("--out", required=True, help="the folder with the report-*.json files ($Out)")
    parser.add_argument("--expect-sha", help="the SHA the runbook names ($QualSha)")
    args = parser.parse_args(argv)
    out = Path(args.out)
    if not out.is_dir():
        print("usage error: --out must be an existing folder", file=sys.stderr)
        return 2
    manifest = build_manifest(Path(args.repo), out, args.expect_sha)
    target = out / f"evidence-manifest-{time.strftime('%Y%m%d-%H%M%S')}.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for report in manifest["reports"]:
        failed = report.get("failed_checks") or []
        print(f"{report.get('result', '?'):10} {report.get('mode') or '?':10} {report.get('profile') or '':18} "
              f"{report['file']}" + (f"  failed: {', '.join(failed)}" if failed else ""))
    summary = manifest["summary"]
    print(f"qualified_sha={manifest['qualified_sha']} expected_match={manifest['expected_sha_matches']} "
          f"all_at_sha={manifest['all_reports_at_qualified_sha']}")
    print(f"missing={summary['expected_modes_missing']} failed_modes={summary['modes_with_a_failure']}")
    print(f"manifest: {target}")
    clean = (summary["reports_failed"] == 0 and manifest["all_reports_at_qualified_sha"]
             and manifest["expected_sha_matches"] is not False)
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
