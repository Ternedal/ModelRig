#!/usr/bin/env python3
"""Independently validate physical T-033 protected backup/restore evidence.

The gate never decrypts memory. It rechecks the exact candidate, file inventory,
artifact hashes, same-user restore observations, sensitive-canary scan results and
a cross-user Windows SID probe. Missing or stale physical evidence stays red.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = "kaliv-agent3-memory-protected-backup-physical-state/v1"
PROBE_SCHEMA = "kaliv-agent3-memory-protected-backup-cross-user-probe/v1"
REPORT_SCHEMA = "kaliv-agent3-memory-protected-backup-physical/v1"
MAX_JSON_BYTES = 2_000_000
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024
MAX_AGE_HOURS = 24.0
MAX_WINDOW_HOURS = 12.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SID = re.compile(r"^S-\d-(?:\d+-)+\d+$", re.IGNORECASE)
_CAMPAIGN = re.compile(r"^[a-z0-9-]{12,100}$")


class PhysicalBackupGateError(RuntimeError):
    """Physical backup evidence cannot be read safely."""


def _load_identity_module():
    path = ROOT / "scripts" / "physical_validation_campaign.py"
    spec = importlib.util.spec_from_file_location("t033_physical_identity", path)
    if spec is None or spec.loader is None:
        raise PhysicalBackupGateError("cannot load candidate identity module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _resolve_under(root: Path, value: str | Path) -> Path:
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        raise PhysicalBackupGateError(f"path escapes repository: {value}")
    unresolved = root / raw
    if unresolved.is_symlink():
        raise PhysicalBackupGateError(f"path is a symlink: {value}")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PhysicalBackupGateError(f"path escapes repository: {value}") from exc
    return resolved


def _load_json(root: Path, path_value: str | Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve_under(root, path_value)
    if not path.is_file() or path.is_symlink():
        raise PhysicalBackupGateError(f"JSON evidence is missing or irregular: {path_value}")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise PhysicalBackupGateError(f"JSON evidence size is invalid: {path_value}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhysicalBackupGateError(f"JSON evidence is not UTF-8 JSON: {path_value}") from exc
    if not isinstance(value, dict):
        raise PhysicalBackupGateError(f"JSON evidence is not an object: {path_value}")
    return value, raw, path


def _candidate_errors(
    label: str,
    actual: Any,
    expected: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(actual, Mapping):
        return [f"{label} candidate is missing"]
    for key in ("version", "git_sha", "code_sha256", "identity_source"):
        if actual.get(key) != expected.get(key):
            errors.append(f"{label} candidate.{key} mismatch")
    git_sha = actual.get("git_sha")
    code_sha = actual.get("code_sha256")
    if not isinstance(git_sha, str) or _GIT_SHA.fullmatch(git_sha) is None:
        errors.append(f"{label} candidate.git_sha is invalid")
    if not isinstance(code_sha, str) or _SHA256.fullmatch(code_sha) is None:
        errors.append(f"{label} candidate.code_sha256 is invalid")
    return errors


def _artifact(
    *,
    root: Path,
    campaign_dir: Path,
    value: Any,
    errors: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append("artifact entry is not an object")
        return None
    name = value.get("name")
    path_value = value.get("path")
    digest = value.get("sha256")
    size = value.get("bytes")
    label = f"artifact {name!r}"
    if not isinstance(name, str) or not name or len(name) > 100:
        errors.append("artifact name is invalid")
        return None
    if not isinstance(path_value, str) or not path_value:
        errors.append(f"{label} path is missing")
        return None
    try:
        path = _resolve_under(root, path_value)
    except PhysicalBackupGateError as exc:
        errors.append(str(exc))
        return None
    try:
        path.relative_to(campaign_dir)
    except ValueError:
        errors.append(f"{label} is outside the physical campaign directory")
        return None
    if path.is_symlink() or not path.is_file():
        errors.append(f"{label} is missing or irregular")
        return None
    actual_size = path.stat().st_size
    if actual_size <= 0 or actual_size > MAX_ARTIFACT_BYTES:
        errors.append(f"{label} size is invalid")
        return None
    if isinstance(size, bool) or not isinstance(size, int) or size != actual_size:
        errors.append(f"{label} byte count mismatch")
    raw_digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                errors.append(f"{label} exceeds size limit")
                return None
            raw_digest.update(chunk)
    actual_digest = raw_digest.hexdigest()
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        errors.append(f"{label} SHA-256 is invalid")
    elif digest != actual_digest:
        errors.append(f"{label} SHA-256 mismatch")
    return {
        "name": name,
        "path": str(path.relative_to(root.resolve())).replace("\\", "/"),
        "sha256": actual_digest,
        "bytes": actual_size,
    }


def judge(
    *,
    root: Path,
    state: Mapping[str, Any],
    probe: Mapping[str, Any],
    candidate: Mapping[str, Any],
    now: datetime,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if state.get("schema") != STATE_SCHEMA:
        errors.append("physical backup state schema mismatch")
    if probe.get("schema") != PROBE_SCHEMA:
        errors.append("cross-user probe schema mismatch")
    if state.get("production_activation") is not False:
        errors.append("physical backup state activated production")
    if probe.get("production_activation") is not False:
        errors.append("cross-user probe activated production")

    campaign_id = state.get("campaign_id")
    if not isinstance(campaign_id, str) or _CAMPAIGN.fullmatch(campaign_id) is None:
        errors.append("physical backup campaign_id is invalid")
        campaign_id = "invalid"
    if probe.get("campaign_id") != campaign_id:
        errors.append("cross-user probe campaign_id mismatch")
    campaign_path = state.get("campaign_path")
    campaign_dir: Path | None = None
    if not isinstance(campaign_path, str) or not campaign_path:
        errors.append("physical backup campaign_path is missing")
    else:
        try:
            campaign_dir = _resolve_under(root, campaign_path)
            if campaign_dir.is_symlink() or not campaign_dir.is_dir():
                errors.append("physical backup campaign_path is not a regular directory")
        except PhysicalBackupGateError as exc:
            errors.append(str(exc))

    errors.extend(_candidate_errors("state", state.get("candidate"), candidate))
    errors.extend(_candidate_errors("probe", probe.get("candidate"), candidate))

    prepared_at = _parse_time(state.get("prepared_at"))
    observed_at = _parse_time(probe.get("observed_at"))
    for label, value in (("prepared_at", prepared_at), ("probe.observed_at", observed_at)):
        if value is None:
            errors.append(f"{label} is not timezone-aware")
        else:
            age = (now - value).total_seconds() / 3600.0
            if age < -0.25:
                errors.append(f"{label} is in the future")
            elif age > MAX_AGE_HOURS:
                errors.append(f"{label} is {age:.1f}h old; max is {MAX_AGE_HOURS:.1f}h")
    if prepared_at is not None and observed_at is not None:
        if observed_at < prepared_at:
            errors.append("cross-user probe predates same-user preparation")
        window = (observed_at - prepared_at).total_seconds() / 3600.0
        if window > MAX_WINDOW_HOURS:
            errors.append(
                f"physical backup campaign spans {window:.1f}h; max is {MAX_WINDOW_HOURS:.1f}h"
            )
    else:
        window = None

    owner = state.get("owner") if isinstance(state.get("owner"), Mapping) else {}
    probe_identity = (
        probe.get("probe_identity")
        if isinstance(probe.get("probe_identity"), Mapping)
        else {}
    )
    owner_sid = owner.get("sid")
    probe_sid = probe_identity.get("sid")
    for label, sid in (("owner.sid", owner_sid), ("probe_identity.sid", probe_sid)):
        if not isinstance(sid, str) or _SID.fullmatch(sid) is None:
            errors.append(f"{label} is invalid")
    if owner_sid == probe_sid and owner_sid is not None:
        errors.append("cross-user probe ran under the owner Windows SID")
    if probe.get("owner_sid") != owner_sid:
        errors.append("cross-user probe owner_sid mismatch")

    canaries = state.get("canaries") if isinstance(state.get("canaries"), Mapping) else {}
    for key in (
        "private_value_sha256",
        "private_source_sha256",
        "secret_value_sha256",
    ):
        value = canaries.get(key)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            errors.append(f"canaries.{key} is invalid")
    memory_ids = canaries.get("memory_ids")
    if (
        not isinstance(memory_ids, Mapping)
        or set(memory_ids) != {"private", "secret"}
        or any(not isinstance(value, str) or not value for value in memory_ids.values())
    ):
        errors.append("canary memory id inventory mismatch")

    checks = state.get("checks") if isinstance(state.get("checks"), Mapping) else {}
    for key in (
        "source_migrated",
        "bundle_verified",
        "same_user_restore",
        "destination_absent_before_restore",
        "restored_single_file",
    ):
        if checks.get(key) is not True:
            errors.append(f"state check {key} is not true")
    if checks.get("protected_values_reopened") != 2:
        errors.append("same-user restore did not reopen exactly two protected values")
    if checks.get("sensitive_plaintext_matches") != 0:
        errors.append("sensitive canary plaintext was found in physical artifacts")

    artifacts = state.get("artifacts")
    validated_artifacts: list[dict[str, Any]] = []
    if not isinstance(artifacts, list):
        errors.append("physical artifact inventory is missing")
        artifacts = []
    names = [item.get("name") for item in artifacts if isinstance(item, Mapping)]
    required_names = {
        "source_database",
        "backup_database",
        "backup_manifest",
        "restored_database",
        "same_user_log",
    }
    if set(names) != required_names or len(names) != len(required_names):
        errors.append("physical artifact inventory mismatch")
    if campaign_dir is not None:
        for artifact_value in artifacts:
            validated = _artifact(
                root=root,
                campaign_dir=campaign_dir,
                value=artifact_value,
                errors=errors,
            )
            if validated is not None:
                validated_artifacts.append(validated)

    artifact_by_name = {item["name"]: item for item in validated_artifacts}
    backup_digest = artifact_by_name.get("backup_database", {}).get("sha256")
    if probe.get("backup_database_sha256") != backup_digest:
        errors.append("cross-user probe backup digest mismatch")
    if probe.get("result") != "dpapi_denied":
        errors.append("cross-user probe did not prove DPAPI denial")
    if probe.get("destination_absent") is not True:
        errors.append("cross-user probe left a visible restore destination")
    if probe.get("error_type") != "ProtectedMemoryBackupError":
        errors.append("cross-user probe error type mismatch")
    error_code = probe.get("error_code")
    if error_code not in {"current_key_scope_denied", "dpapi_unprotect_denied"}:
        errors.append("cross-user probe error code is not a bounded DPAPI denial")

    summary = {
        "campaign_id": campaign_id,
        "campaign_path": campaign_path,
        "candidate": dict(state.get("candidate") or {}),
        "owner": {"username": owner.get("username"), "sid": owner_sid},
        "probe_identity": {
            "username": probe_identity.get("username"),
            "sid": probe_sid,
        },
        "window_hours": round(window, 3) if window is not None else None,
        "artifacts": validated_artifacts,
        "same_user_restore": checks.get("same_user_restore") is True,
        "cross_user_dpapi_denied": probe.get("result") == "dpapi_denied",
        "sensitive_plaintext_matches": checks.get("sensitive_plaintext_matches"),
        "production_activation": False,
    }
    return errors, summary


def verify(
    *,
    state_path: Path,
    probe_path: Path,
    report_path: Path,
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    state, state_raw, state_file = _load_json(root, state_path)
    probe, probe_raw, probe_file = _load_json(root, probe_path)
    identity = _load_identity_module().candidate_identity(root)
    errors, summary = judge(
        root=root,
        state=state,
        probe=probe,
        candidate=identity,
        now=now or datetime.now(timezone.utc),
    )
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": _iso(now or datetime.now(timezone.utc)),
        "success": not errors,
        "candidate": {
            key: identity.get(key)
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "state": {
            "path": str(state_file.relative_to(root.resolve())).replace("\\", "/"),
            "sha256": _sha(state_raw),
            "bytes": len(state_raw),
        },
        "probe": {
            "path": str(probe_file.relative_to(root.resolve())).replace("\\", "/"),
            "sha256": _sha(probe_raw),
            "bytes": len(probe_raw),
        },
        "summary": summary,
        "errors": errors,
        "production_activation": False,
    }
    destination = _resolve_under(root, report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=destination.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(destination)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("validation/agent3-memory-protected-backup-physical-latest.json"),
    )
    args = parser.parse_args(argv)
    try:
        report = verify(
            state_path=args.state,
            probe_path=args.probe,
            report_path=args.report,
        )
    except Exception as exc:
        print(
            f"protected backup physical gate error: {type(exc).__name__}: {str(exc)[:500]}",
            file=sys.stderr,
        )
        return 2
    print(
        "protected backup physical gate: "
        + ("PASS" if report["success"] else "BLOCKED")
    )
    for error in report["errors"]:
        print(f"  - {error}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
