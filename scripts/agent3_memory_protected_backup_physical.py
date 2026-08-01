#!/usr/bin/env python3
"""Windows-rig operator for physical T-033 protected backup/restore evidence.

Commands:
- prepare: exact-candidate same-user DPAPI backup/restore and plaintext scan;
- probe: run from a different Windows account against the Public staging bundle;
- collect: import the probe, require an exact operator phrase and run the
  independent physical gate.

The operator uses a dedicated fixture database, never the active memory store.
It never prints or writes raw protected canaries after they enter the in-memory
fixture creation step, and it cannot merge, release or activate production.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import importlib.util
import json
import os
import platform
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKER = ROOT / "worker"
VALIDATION = ROOT / "validation"
CAMPAIGN_ROOT = VALIDATION / "agent3-memory-protected-backup-physical"
BRANCH = "agent/t033-memory-protected-backup-physical-operator"
VERSION = "1.58.147"
STATE_SCHEMA = "kaliv-agent3-memory-protected-backup-physical-state/v1"
REQUEST_SCHEMA = "kaliv-agent3-memory-protected-backup-cross-user-request/v1"
PROBE_SCHEMA = "kaliv-agent3-memory-protected-backup-cross-user-probe/v1"
ATTESTATION = "JEG HAR KØRT T-033 BACKUP RESTORE PÅ WINDOWS RIGGEN"
MAX_SCAN_BYTES = 8 * 1024 * 1024 * 1024

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(WORKER))

import stage_a_one_click as stage  # noqa: E402
from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_protected_backup import (  # noqa: E402
    BACKUP_DATABASE_NAME,
    BACKUP_MANIFEST_NAME,
    ProtectedMemoryBackupError,
    ProtectedMemoryBackupManager,
)
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
    ProtectedMemoryReader,
)
from app.agent3.memory_protection import (  # noqa: E402
    MemoryProtectionCodec,
    WindowsDpapiMemoryProtectionProvider,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402


class PhysicalBackupOperatorError(RuntimeError):
    """The physical operator cannot continue safely."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PhysicalBackupOperatorError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


identity_module = _load_module(
    "t033_backup_physical_identity",
    SCRIPTS / "physical_validation_campaign.py",
)
gate_module = _load_module(
    "t033_backup_physical_gate",
    SCRIPTS / "agent3_memory_protected_backup_physical_gate.py",
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SCAN_BYTES:
                raise PhysicalBackupOperatorError(f"artifact exceeds scan limit: {path}")
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PhysicalBackupOperatorError(f"JSON file is missing or irregular: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhysicalBackupOperatorError(f"JSON file is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise PhysicalBackupOperatorError(f"JSON file is not an object: {path}")
    return value


def _require_windows() -> None:
    if os.name != "nt" or platform.system() != "Windows":
        raise PhysicalBackupOperatorError("T-033 physical backup operator requires Windows")


def _run(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=os.environ.copy(),
            text=True,
            capture_output=capture,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PhysicalBackupOperatorError(f"cannot run {args[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "")[-500:]
        raise PhysicalBackupOperatorError(
            f"command failed ({result.returncode}): {' '.join(args)}"
            + (f" — {detail}" if detail else "")
        )
    return result


def _windows_identity() -> dict[str, str]:
    username = _run(["whoami"]).stdout.strip()
    row_text = _run(["whoami", "/user", "/fo", "csv", "/nh"]).stdout.strip()
    rows = list(csv.reader([row_text]))
    sid = rows[0][-1].strip() if rows and rows[0] else ""
    if not username or not gate_module._SID.fullmatch(sid):
        raise PhysicalBackupOperatorError("cannot resolve the current Windows username/SID")
    return {"username": username, "sid": sid}


def _candidate(*, checkout: bool) -> dict[str, Any]:
    if checkout:
        stage.BRANCH = BRANCH
        stage.VERSION = VERSION
        stage.ensure_candidate()
    identity = identity_module.candidate_identity(ROOT)
    if (
        identity.get("version") != VERSION
        or identity.get("working_tree_clean") is not True
        or identity.get("version_stamps_consistent") is not True
    ):
        raise PhysicalBackupOperatorError(
            "candidate is not clean, version-consistent and exact-head bound"
        )
    return {
        key: identity.get(key)
        for key in ("version", "git_sha", "code_sha256", "identity_source")
    }


def _public_root() -> Path:
    value = os.environ.get("PUBLIC", "").strip()
    if value:
        root = Path(value)
    else:
        drive = Path(ROOT.drive + "\\") if ROOT.drive else Path("C:\\")
        root = drive / "Users" / "Public"
    destination = root / "Documents" / "Kaliv-T033"
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or not destination.is_dir():
        raise PhysicalBackupOperatorError("Public staging directory is irregular")
    return destination


def _normalize_sqlite(path: Path) -> None:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        mode = str(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
        if mode != "delete":
            raise PhysicalBackupOperatorError("fixture SQLite could not enter DELETE mode")
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
    for suffix in ("-wal", "-shm", "-journal"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _artifact(root: Path, name: str, path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PhysicalBackupOperatorError(f"artifact is missing or irregular: {path}")
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PhysicalBackupOperatorError(f"artifact is outside repository: {path}") from exc
    return {
        "name": name,
        "path": str(relative).replace("\\", "/"),
        "sha256": _sha_file(path),
        "bytes": path.stat().st_size,
    }


def _sensitive_patterns(values: list[str]) -> list[bytes]:
    patterns: list[bytes] = []
    for value in values:
        for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
            encoded = value.encode(encoding)
            if encoded not in patterns:
                patterns.append(encoded)
    return patterns


def _scan_sensitive(files: list[Path], values: list[str]) -> tuple[int, list[str]]:
    patterns = _sensitive_patterns(values)
    matches = 0
    scanned: list[str] = []
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise PhysicalBackupOperatorError(f"scan target is irregular: {path}")
        raw = path.read_bytes()
        if len(raw) > MAX_SCAN_BYTES:
            raise PhysicalBackupOperatorError(f"scan target exceeds size limit: {path}")
        scanned.append(str(path.relative_to(ROOT.resolve())).replace("\\", "/"))
        for pattern in patterns:
            matches += raw.count(pattern)
    return matches, sorted(scanned)


def _source_family(path: Path) -> list[Path]:
    values = [path]
    for suffix in ("-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        if candidate.exists() or candidate.is_symlink():
            values.append(candidate)
    return values


def _write_same_user_log(
    path: Path,
    *,
    campaign_id: str,
    candidate: Mapping[str, Any],
    owner: Mapping[str, str],
    backup_summary: Mapping[str, Any],
    restore_summary: Mapping[str, Any],
    canary_hashes: Mapping[str, Any],
) -> None:
    _atomic_json(
        path,
        {
            "schema": "kaliv-agent3-memory-protected-backup-same-user-log/v1",
            "observed_at": _iso_now(),
            "campaign_id": campaign_id,
            "candidate": dict(candidate),
            "owner": dict(owner),
            "backup_summary": dict(backup_summary),
            "restore_summary": dict(restore_summary),
            "canaries": dict(canary_hashes),
            "raw_values_logged": False,
            "production_activation": False,
        },
    )


def _request_payload(
    *,
    campaign_id: str,
    candidate: Mapping[str, Any],
    owner: Mapping[str, str],
    public_bundle: Path,
    backup_digest: str,
) -> dict[str, Any]:
    return {
        "schema": REQUEST_SCHEMA,
        "prepared_at": _iso_now(),
        "campaign_id": campaign_id,
        "candidate": dict(candidate),
        "owner": dict(owner),
        "bundle_path": str(public_bundle),
        "backup_database_sha256": backup_digest,
        "production_activation": False,
    }


def prepare(operator: str) -> int:
    _require_windows()
    candidate = _candidate(checkout=True)
    owner = _windows_identity()
    campaign_id = "t033-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
    campaign_dir = CAMPAIGN_ROOT / campaign_id
    if campaign_dir.exists() or campaign_dir.is_symlink():
        raise PhysicalBackupOperatorError("physical campaign directory already exists")
    campaign_dir.mkdir(parents=True)

    source = campaign_dir / "source-memory.sqlite3"
    bundle = campaign_dir / "backup-bundle"
    restored = campaign_dir / "restored-memory.sqlite3"
    same_user_log = campaign_dir / "same-user-log.json"
    request_copy = campaign_dir / "cross-user-request.json"
    state_path = campaign_dir / "state.json"

    private_value = "T033-PRIVATE-VALUE-" + secrets.token_hex(24)
    private_source = "T033-PRIVATE-SOURCE-" + secrets.token_hex(24)
    secret_value = "T033-SECRET-VALUE-" + secrets.token_hex(24)
    codec = MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider())

    store = MemoryStore(str(source))
    try:
        public_id = store.create(
            subject="system",
            predicate="t033_backup_public",
            value="T033-PUBLIC-CONTROL",
            sensitivity="public",
        ).id
        private_id = store.create(
            subject="physical-operator",
            predicate="t033_backup_private",
            value=private_value,
            sensitivity="private",
            source_ref=private_source,
        ).id
        secret_id = store.create(
            subject="physical-operator",
            predicate="t033_backup_secret",
            value=secret_value,
            sensitivity="secret",
        ).id
    finally:
        store.close()

    migration = MemoryProtectionMigrator(source, codec).migrate()
    if not migration.complete:
        raise PhysicalBackupOperatorError("physical fixture migration did not complete")
    _normalize_sqlite(source)

    manager = ProtectedMemoryBackupManager(codec)
    backup_summary = manager.create(source, bundle)
    manager.verify(bundle)
    destination_absent = not restored.exists() and not restored.is_symlink()
    restore_summary = manager.restore(bundle, restored)
    _normalize_sqlite(restored)

    with ProtectedMemoryReader(restored, codec) as reader:
        private_record = reader.get(
            private_id,
            access=MemoryReadAccess.LOCAL_MANAGEMENT,
        )
        secret_record = reader.get(
            secret_id,
            access=MemoryReadAccess.LOCAL_MANAGEMENT,
        )
        public_record = reader.get(
            public_id,
            access=MemoryReadAccess.LOCAL_MANAGEMENT,
        )
    if (
        private_record.value != private_value
        or private_record.source_ref != private_source
        or secret_record.value != secret_value
        or public_record.value != "T033-PUBLIC-CONTROL"
    ):
        raise PhysicalBackupOperatorError("same-user restored values did not match")

    canary_hashes = {
        "private_value_sha256": _sha_bytes(private_value.encode("utf-8")),
        "private_source_sha256": _sha_bytes(private_source.encode("utf-8")),
        "secret_value_sha256": _sha_bytes(secret_value.encode("utf-8")),
        "memory_ids": {"private": private_id, "secret": secret_id},
    }
    _write_same_user_log(
        same_user_log,
        campaign_id=campaign_id,
        candidate=candidate,
        owner=owner,
        backup_summary=backup_summary.to_dict(),
        restore_summary=restore_summary.to_dict(),
        canary_hashes=canary_hashes,
    )

    public_dir = _public_root() / campaign_id
    if public_dir.exists() or public_dir.is_symlink():
        raise PhysicalBackupOperatorError("Public cross-user staging directory exists")
    public_dir.mkdir()
    public_bundle = public_dir / "backup-bundle"
    shutil.copytree(bundle, public_bundle)
    public_request = public_dir / "request.json"
    public_probe = public_dir / "probe.json"
    request = _request_payload(
        campaign_id=campaign_id,
        candidate=candidate,
        owner=owner,
        public_bundle=public_bundle,
        backup_digest=backup_summary.artifact_sha256,
    )
    _atomic_json(public_request, request)
    _atomic_json(request_copy, request)

    artifact_values = [
        _artifact(ROOT, "source_database", source),
        _artifact(ROOT, "backup_database", bundle / BACKUP_DATABASE_NAME),
        _artifact(ROOT, "backup_manifest", bundle / BACKUP_MANIFEST_NAME),
        _artifact(ROOT, "restored_database", restored),
        _artifact(ROOT, "same_user_log", same_user_log),
        _artifact(ROOT, "probe_request", request_copy),
    ]
    scan_files = (
        _source_family(source)
        + list(bundle.iterdir())
        + _source_family(restored)
        + [same_user_log, request_copy]
    )
    matches, scanned = _scan_sensitive(
        scan_files,
        [private_value, private_source, secret_value],
    )

    state = {
        "schema": STATE_SCHEMA,
        "prepared_at": _iso_now(),
        "campaign_id": campaign_id,
        "campaign_path": str(campaign_dir.relative_to(ROOT)).replace("\\", "/"),
        "operator": operator,
        "candidate": candidate,
        "owner": owner,
        "canaries": canary_hashes,
        "checks": {
            "source_migrated": migration.complete,
            "bundle_verified": True,
            "same_user_restore": True,
            "destination_absent_before_restore": destination_absent,
            "protected_values_reopened": 2,
            "restored_single_file": len(_source_family(restored)) == 1,
            "sensitive_plaintext_matches": matches,
            "scanned_files": scanned,
        },
        "artifacts": artifact_values,
        "probe_request": {
            "public_request_path": str(public_request),
            "public_probe_path": str(public_probe),
            "backup_database_sha256": backup_summary.artifact_sha256,
        },
        "production_activation": False,
    }
    _atomic_json(state_path, state)

    private_value = private_source = secret_value = ""
    if matches != 0:
        raise PhysicalBackupOperatorError(
            f"sensitive plaintext scan found {matches} match(es); campaign remains red"
        )

    launcher = ROOT / "START_AGENT3_MEMORY_BACKUP_PHYSICAL.cmd"
    print("\nSAME-USER FASE: BESTÅET, MEN KAMPAGNEN ER IKKE GRØN.")
    print(f"Campaign: {campaign_id}")
    print("Kør nu nedenstående fra en ANDEN Windows-bruger/SID:")
    print(
        f'runas /user:<ANDEN-BRUGER> "\\\"{launcher}\\\" probe '
        f'--request \\\"{public_request}\\\" --output \\\"{public_probe}\\\""'
    )
    print("Når probe.json findes, gå tilbage til ejerbrugeren og kør:")
    print(
        f'"{launcher}" collect --state "{state_path}" --probe "{public_probe}"'
    )
    return 0


def probe(request_path: Path, output: Path) -> int:
    _require_windows()
    request = _load_json(request_path)
    if request.get("schema") != REQUEST_SCHEMA:
        raise PhysicalBackupOperatorError("cross-user request schema mismatch")
    if request.get("production_activation") is not False:
        raise PhysicalBackupOperatorError("cross-user request activated production")
    candidate = _candidate(checkout=False)
    if request.get("candidate") != candidate:
        raise PhysicalBackupOperatorError("cross-user request candidate mismatch")
    identity = _windows_identity()
    owner = request.get("owner") if isinstance(request.get("owner"), Mapping) else {}
    owner_sid = owner.get("sid")
    if identity["sid"].lower() == str(owner_sid).lower():
        result = "same_sid"
        error_code = "same_sid"
        error_type = None
        destination_absent = True
        exit_code = 1
    else:
        bundle = Path(str(request.get("bundle_path") or ""))
        database = bundle / BACKUP_DATABASE_NAME
        if not database.is_file() or database.is_symlink():
            raise PhysicalBackupOperatorError("cross-user bundle is missing")
        if _sha_file(database) != request.get("backup_database_sha256"):
            raise PhysicalBackupOperatorError("cross-user bundle digest mismatch")
        codec = MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider())
        manager = ProtectedMemoryBackupManager(codec)
        probe_root = Path(tempfile.mkdtemp(prefix="kaliv-t033-cross-user-"))
        destination = probe_root / "restored.sqlite3"
        try:
            manager.restore(bundle, destination)
        except ProtectedMemoryBackupError as exc:
            message = str(exc)
            result = "dpapi_denied"
            error_type = type(exc).__name__
            error_code = (
                "current_key_scope_denied"
                if "current key scope" in message
                else "dpapi_unprotect_denied"
            )
            destination_absent = not destination.exists() and not destination.is_symlink()
            exit_code = 0
        else:
            result = "unexpected_success"
            error_type = None
            error_code = "cross_user_restore_succeeded"
            destination_absent = not destination.exists()
            exit_code = 1
        finally:
            shutil.rmtree(probe_root, ignore_errors=True)
    value = {
        "schema": PROBE_SCHEMA,
        "observed_at": _iso_now(),
        "campaign_id": request.get("campaign_id"),
        "candidate": candidate,
        "owner_sid": owner_sid,
        "probe_identity": identity,
        "backup_database_sha256": request.get("backup_database_sha256"),
        "result": result,
        "error_type": error_type,
        "error_code": error_code,
        "destination_absent": destination_absent,
        "production_activation": False,
    }
    if output.exists() or output.is_symlink():
        raise PhysicalBackupOperatorError("cross-user probe output already exists")
    _atomic_json(output, value)
    print(f"Cross-user probe: {result}. Report: {output}")
    return exit_code


def collect(state_path: Path, external_probe: Path) -> int:
    _require_windows()
    state = _load_json(state_path)
    candidate = _candidate(checkout=False)
    if state.get("candidate") != candidate:
        raise PhysicalBackupOperatorError("physical state candidate mismatch")
    campaign_path = ROOT / str(state.get("campaign_path") or "")
    if campaign_path.is_symlink() or not campaign_path.is_dir():
        raise PhysicalBackupOperatorError("physical campaign directory is missing")
    imported_probe = campaign_path / "cross-user-probe.json"
    if imported_probe.exists() or imported_probe.is_symlink():
        raise PhysicalBackupOperatorError("cross-user probe was already imported")
    probe_value = _load_json(external_probe)
    _atomic_json(imported_probe, probe_value)

    entered = input(f"Skriv præcis '{ATTESTATION}' for at samle rapporten: ").strip()
    if entered != ATTESTATION:
        raise PhysicalBackupOperatorError(
            "operator attestation did not match; physical evidence remains red"
        )
    report_path = campaign_path / "physical-report.json"
    report = gate_module.verify(
        state_path=state_path.relative_to(ROOT),
        probe_path=imported_probe.relative_to(ROOT),
        report_path=report_path.relative_to(ROOT),
    )
    if not report.get("success"):
        print("T-033 fysisk backup/restore: BLOKERET")
        for error in report.get("errors", []):
            print(f"  - {error}")
        return 1
    latest = VALIDATION / "agent3-memory-protected-backup-physical-latest.json"
    if latest.exists() or latest.is_symlink():
        archive = VALIDATION / "archive" / (
            "t033-memory-backup-" + time.strftime("%Y%m%d-%H%M%S")
        )
        archive.mkdir(parents=True, exist_ok=True)
        latest.replace(archive / latest.name)
    shutil.copy2(report_path, latest)
    print("T-033 fysisk backup/restore: PASS")
    print(f"Report: {report_path}")
    print("production_activation=false")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument(
        "--operator",
        default=os.environ.get("USERNAME") or getpass.getuser(),
    )
    probe_parser = sub.add_parser("probe")
    probe_parser.add_argument("--request", type=Path, required=True)
    probe_parser.add_argument("--output", type=Path, required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--state", type=Path, required=True)
    collect_parser.add_argument("--probe", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        return prepare(args.operator)
    if args.command == "probe":
        return probe(args.request, args.output)
    return collect(args.state, args.probe)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nSIKKERT STOP: afbrudt; eksisterende artifacts er bevaret.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1000]}",
            file=sys.stderr,
        )
        raise SystemExit(1)
