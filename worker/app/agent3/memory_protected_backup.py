from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .memory_protected_reader import (
    MemoryReadAccess,
    ProtectedMemoryReadError,
    ProtectedMemoryReader,
)
from .memory_protection import MemoryProtectionCodec, MemoryProtectionError
from .memory_protection_migration import MIGRATION_ID, MIGRATION_SCHEMA


BACKUP_SCHEMA = "kaliv-agent3-memory-protected-backup/v1"
BACKUP_REVISION = 1
BACKUP_DATABASE_NAME = "memory.sqlite3"
BACKUP_MANIFEST_NAME = "manifest.json"
MAX_BACKUP_BYTES = 8 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 256_000
MAX_VERIFICATION_IDS = 3

_MANIFEST_KEYS = {
    "schema",
    "revision",
    "created_at",
    "source",
    "artifact",
    "verification_memory_ids",
    "restore_policy",
    "production_activation",
}
_SOURCE_KEYS = {
    "migration_schema",
    "migration_id",
    "provider",
    "key_scope",
    "migration_state",
    "protected_rows",
    "redacted_rows",
    "public_operational_rows",
}
_ARTIFACT_KEYS = {
    "name",
    "sha256",
    "bytes",
    "page_count",
    "page_size",
}
_POLICY_KEYS = {
    "destination_must_be_absent",
    "same_provider_required",
    "same_key_scope_required",
    "bounded_key_open_required",
    "physical_windows_restore_required",
}


class ProtectedMemoryBackupError(RuntimeError):
    """Protected memory cannot be backed up or restored without weakening scope."""


@dataclass(frozen=True)
class ProtectedMemoryBackupSummary:
    schema: str
    revision: int
    provider: str
    key_scope: str
    artifact_sha256: str
    artifact_bytes: int
    protected_rows: int
    redacted_rows: int
    public_operational_rows: int
    verification_ids: int
    key_open_verified: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "revision": self.revision,
            "provider": self.provider,
            "key_scope": self.key_scope,
            "artifact_sha256": self.artifact_sha256,
            "artifact_bytes": self.artifact_bytes,
            "protected_rows": self.protected_rows,
            "redacted_rows": self.redacted_rows,
            "public_operational_rows": self.public_operational_rows,
            "verification_ids": self.verification_ids,
            "key_open_verified": self.key_open_verified,
            "production_activation": False,
        }


class ProtectedMemoryBackupManager:
    """Ciphertext-only offline backup and atomic restore boundary.

    The manager is deliberately not imported by worker startup. Backup uses
    SQLite's online backup API to capture a consistent snapshot, then validates
    the copy through ``ProtectedMemoryReader``. Restore writes to a temporary
    sibling and becomes visible only after manifest, digest, schema and bounded
    key/scope checks pass. It never logs or returns decrypted memory values.
    """

    def __init__(
        self,
        codec: MemoryProtectionCodec,
        *,
        clock: Callable[[], float] = time.time,
        busy_timeout_ms: int = 5_000,
    ):
        self.codec = codec
        self.clock = clock
        self.busy_timeout_ms = max(1, min(int(busy_timeout_ms), 120_000))

    def create(
        self,
        source: str | Path,
        bundle: str | Path,
    ) -> ProtectedMemoryBackupSummary:
        source_path = self._regular_database(Path(source), "source")
        bundle_path = Path(bundle)
        self._require_absent(bundle_path, "backup bundle")
        self._require_regular_parent(bundle_path)

        source_status = self._reader_status(source_path)
        temporary = bundle_path.with_name(
            f".{bundle_path.name}.tmp-{secrets.token_hex(8)}"
        )
        self._require_absent(temporary, "temporary backup bundle")
        temporary.mkdir(mode=0o700)
        database_path = temporary / BACKUP_DATABASE_NAME
        manifest_path = temporary / BACKUP_MANIFEST_NAME
        try:
            self._sqlite_backup(source_path, database_path)
            copied_status = self._reader_status(database_path)
            self._require_status_equal(source_status, copied_status)
            integrity, page_count, page_size = self._database_integrity(database_path)
            if integrity != "ok":
                raise ProtectedMemoryBackupError(
                    "protected memory backup failed SQLite integrity_check"
                )
            verification_ids = self._verification_ids(database_path)
            artifact_bytes = database_path.stat().st_size
            artifact_sha256 = self._sha256_file(database_path)
            manifest = {
                "schema": BACKUP_SCHEMA,
                "revision": BACKUP_REVISION,
                "created_at": float(self.clock()),
                "source": self._status_projection(copied_status),
                "artifact": {
                    "name": BACKUP_DATABASE_NAME,
                    "sha256": artifact_sha256,
                    "bytes": artifact_bytes,
                    "page_count": page_count,
                    "page_size": page_size,
                },
                "verification_memory_ids": verification_ids,
                "restore_policy": {
                    "destination_must_be_absent": True,
                    "same_provider_required": True,
                    "same_key_scope_required": True,
                    "bounded_key_open_required": True,
                    "physical_windows_restore_required": True,
                },
                "production_activation": False,
            }
            self._write_manifest(manifest_path, manifest)
            self._require_exact_bundle_files(temporary)
            temporary.replace(bundle_path)
            return ProtectedMemoryBackupSummary(
                schema=BACKUP_SCHEMA,
                revision=BACKUP_REVISION,
                provider=str(copied_status.provider),
                key_scope=str(copied_status.key_scope),
                artifact_sha256=artifact_sha256,
                artifact_bytes=artifact_bytes,
                protected_rows=int(copied_status.protected_rows),
                redacted_rows=int(copied_status.redacted_rows),
                public_operational_rows=int(copied_status.public_operational_rows),
                verification_ids=len(verification_ids),
                key_open_verified=0,
            )
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def verify(self, bundle: str | Path) -> ProtectedMemoryBackupSummary:
        bundle_path, manifest, database_path = self._validated_bundle(Path(bundle))
        del bundle_path
        status = self._reader_status(database_path)
        self._validate_status_manifest(status, manifest)
        integrity, page_count, page_size = self._database_integrity(database_path)
        if integrity != "ok":
            raise ProtectedMemoryBackupError(
                "protected memory backup failed SQLite integrity_check"
            )
        artifact = manifest["artifact"]
        if (
            int(artifact["page_count"]) != page_count
            or int(artifact["page_size"]) != page_size
        ):
            raise ProtectedMemoryBackupError(
                "protected memory backup SQLite geometry changed"
            )
        verification_ids = self._validate_verification_ids(
            database_path,
            manifest["verification_memory_ids"],
        )
        return ProtectedMemoryBackupSummary(
            schema=BACKUP_SCHEMA,
            revision=BACKUP_REVISION,
            provider=str(status.provider),
            key_scope=str(status.key_scope),
            artifact_sha256=str(artifact["sha256"]),
            artifact_bytes=int(artifact["bytes"]),
            protected_rows=int(status.protected_rows),
            redacted_rows=int(status.redacted_rows),
            public_operational_rows=int(status.public_operational_rows),
            verification_ids=len(verification_ids),
            key_open_verified=0,
        )

    def restore(
        self,
        bundle: str | Path,
        destination: str | Path,
    ) -> ProtectedMemoryBackupSummary:
        bundle_path, manifest, database_path = self._validated_bundle(Path(bundle))
        del bundle_path
        destination_path = Path(destination)
        self._require_absent(destination_path, "restore destination")
        self._require_regular_parent(destination_path)
        verification_ids = self._validate_verification_ids(
            database_path,
            manifest["verification_memory_ids"],
        )

        temporary = destination_path.with_name(
            f".{destination_path.name}.tmp-{secrets.token_hex(8)}"
        )
        self._require_absent(temporary, "temporary restore destination")
        try:
            self._sqlite_backup(database_path, temporary)
            restored_status = self._reader_status(temporary)
            self._validate_status_manifest(restored_status, manifest)
            integrity, page_count, page_size = self._database_integrity(temporary)
            if integrity != "ok":
                raise ProtectedMemoryBackupError(
                    "restored protected memory failed SQLite integrity_check"
                )
            artifact = manifest["artifact"]
            if (
                int(artifact["page_count"]) != page_count
                or int(artifact["page_size"]) != page_size
            ):
                raise ProtectedMemoryBackupError(
                    "restored protected memory SQLite geometry changed"
                )
            key_open_verified = self._bounded_key_open(temporary, verification_ids)
            temporary.replace(destination_path)
            return ProtectedMemoryBackupSummary(
                schema=BACKUP_SCHEMA,
                revision=BACKUP_REVISION,
                provider=str(restored_status.provider),
                key_scope=str(restored_status.key_scope),
                artifact_sha256=str(artifact["sha256"]),
                artifact_bytes=int(artifact["bytes"]),
                protected_rows=int(restored_status.protected_rows),
                redacted_rows=int(restored_status.redacted_rows),
                public_operational_rows=int(restored_status.public_operational_rows),
                verification_ids=len(verification_ids),
                key_open_verified=key_open_verified,
            )
        except Exception:
            self._remove_database_family(temporary)
            raise

    def _reader_status(self, path: Path):
        try:
            with ProtectedMemoryReader(
                path,
                self.codec,
                busy_timeout_ms=self.busy_timeout_ms,
            ) as reader:
                return reader.status
        except (ProtectedMemoryReadError, MemoryProtectionError) as exc:
            raise ProtectedMemoryBackupError(
                f"protected memory store failed closed: {type(exc).__name__}"
            ) from exc

    def _bounded_key_open(self, path: Path, memory_ids: list[str]) -> int:
        if not memory_ids:
            return 0
        opened = 0
        try:
            with ProtectedMemoryReader(
                path,
                self.codec,
                busy_timeout_ms=self.busy_timeout_ms,
            ) as reader:
                for memory_id in memory_ids:
                    record = reader.get(
                        memory_id,
                        access=MemoryReadAccess.LOCAL_MANAGEMENT,
                        include_deleted=True,
                    )
                    if (
                        record.sensitivity not in {"private", "secret"}
                        or not record.value
                    ):
                        raise ProtectedMemoryBackupError(
                            "restore verification id did not open a protected value"
                        )
                    opened += 1
        except ProtectedMemoryBackupError:
            raise
        except Exception as exc:
            raise ProtectedMemoryBackupError(
                "restored protected memory could not be opened in the current key scope"
            ) from exc
        return opened

    def _validated_bundle(
        self,
        bundle: Path,
    ) -> tuple[Path, dict[str, Any], Path]:
        if bundle.is_symlink() or not bundle.is_dir():
            raise ProtectedMemoryBackupError(
                "protected memory backup bundle must be a regular directory"
            )
        self._require_exact_bundle_files(bundle)
        manifest_path = bundle / BACKUP_MANIFEST_NAME
        database_path = self._regular_database(
            bundle / BACKUP_DATABASE_NAME,
            "backup artifact",
        )
        manifest = self._read_manifest(manifest_path)
        self._validate_manifest_shape(manifest)
        artifact = manifest["artifact"]
        if artifact["name"] != BACKUP_DATABASE_NAME:
            raise ProtectedMemoryBackupError(
                "protected memory backup artifact name mismatch"
            )
        if str(artifact["sha256"]) != self._sha256_file(database_path):
            raise ProtectedMemoryBackupError("protected memory backup digest mismatch")
        actual_bytes = database_path.stat().st_size
        if int(artifact["bytes"]) != actual_bytes:
            raise ProtectedMemoryBackupError(
                "protected memory backup byte count mismatch"
            )
        return bundle, manifest, database_path

    def _validate_manifest_shape(self, manifest: dict[str, Any]) -> None:
        if set(manifest) != _MANIFEST_KEYS:
            raise ProtectedMemoryBackupError(
                "protected memory backup manifest keys mismatch"
            )
        if manifest.get("schema") != BACKUP_SCHEMA:
            raise ProtectedMemoryBackupError("protected memory backup schema mismatch")
        if manifest.get("revision") != BACKUP_REVISION:
            raise ProtectedMemoryBackupError("protected memory backup revision mismatch")
        created_at = manifest.get("created_at")
        if (
            isinstance(created_at, bool)
            or not isinstance(created_at, (int, float))
            or created_at <= 0
        ):
            raise ProtectedMemoryBackupError(
                "protected memory backup created_at is invalid"
            )
        if set(manifest.get("source", {})) != _SOURCE_KEYS:
            raise ProtectedMemoryBackupError(
                "protected memory backup source keys mismatch"
            )
        if set(manifest.get("artifact", {})) != _ARTIFACT_KEYS:
            raise ProtectedMemoryBackupError(
                "protected memory backup artifact keys mismatch"
            )
        if set(manifest.get("restore_policy", {})) != _POLICY_KEYS:
            raise ProtectedMemoryBackupError(
                "protected memory backup restore policy keys mismatch"
            )
        policy = manifest["restore_policy"]
        if any(policy.get(key) is not True for key in _POLICY_KEYS):
            raise ProtectedMemoryBackupError(
                "protected memory backup restore policy weakened"
            )
        if manifest.get("production_activation") is not False:
            raise ProtectedMemoryBackupError(
                "protected memory backup activated production"
            )
        artifact = manifest["artifact"]
        digest = artifact.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ProtectedMemoryBackupError(
                "protected memory backup digest is invalid"
            )
        for key in ("bytes", "page_count", "page_size"):
            value = artifact.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ProtectedMemoryBackupError(
                    f"protected memory backup artifact {key} is invalid"
                )
        if int(artifact["bytes"]) > MAX_BACKUP_BYTES:
            raise ProtectedMemoryBackupError(
                "protected memory backup exceeds size limit"
            )
        ids = manifest.get("verification_memory_ids")
        if not isinstance(ids, list):
            raise ProtectedMemoryBackupError(
                "protected memory backup verification ids are invalid"
            )
        if len(ids) > MAX_VERIFICATION_IDS or len(ids) != len(set(ids)):
            raise ProtectedMemoryBackupError(
                "protected memory backup verification ids are not bounded and unique"
            )
        for memory_id in ids:
            if (
                not isinstance(memory_id, str)
                or not memory_id
                or len(memory_id) > 100
            ):
                raise ProtectedMemoryBackupError(
                    "protected memory backup verification id is invalid"
                )

    def _validate_status_manifest(self, status, manifest: dict[str, Any]) -> None:
        source = manifest["source"]
        expected = self._status_projection(status)
        if source != expected:
            raise ProtectedMemoryBackupError(
                "protected memory backup source status does not match the artifact"
            )
        if status.provider != self.codec.provider.provider_id:
            raise ProtectedMemoryBackupError(
                "protected memory backup provider mismatch"
            )
        if status.key_scope != self.codec.provider.key_scope:
            raise ProtectedMemoryBackupError(
                "protected memory backup key scope mismatch"
            )

    @staticmethod
    def _status_projection(status) -> dict[str, Any]:
        return {
            "migration_schema": MIGRATION_SCHEMA,
            "migration_id": MIGRATION_ID,
            "provider": str(status.provider),
            "key_scope": str(status.key_scope),
            "migration_state": str(status.migration_state),
            "protected_rows": int(status.protected_rows),
            "redacted_rows": int(status.redacted_rows),
            "public_operational_rows": int(status.public_operational_rows),
        }

    @staticmethod
    def _require_status_equal(left, right) -> None:
        if (
            ProtectedMemoryBackupManager._status_projection(left)
            != ProtectedMemoryBackupManager._status_projection(right)
        ):
            raise ProtectedMemoryBackupError(
                "protected memory backup changed the validated store status"
            )

    def _verification_ids(self, database: Path) -> list[str]:
        conn = self._open_read_only(database)
        try:
            rows = conn.execute(
                "SELECT id FROM agent_memories "
                "WHERE protection_state='protected' ORDER BY id LIMIT ?",
                (MAX_VERIFICATION_IDS,),
            ).fetchall()
        finally:
            conn.close()
        return [str(row[0]) for row in rows]

    def _validate_verification_ids(
        self,
        database: Path,
        values: Any,
    ) -> list[str]:
        if not isinstance(values, list):
            raise ProtectedMemoryBackupError(
                "protected memory backup verification ids are invalid"
            )
        expected = self._verification_ids(database)
        if values != expected:
            raise ProtectedMemoryBackupError(
                "protected memory backup verification ids do not match the artifact"
            )
        return list(expected)

    def _sqlite_backup(self, source: Path, destination: Path) -> None:
        self._require_absent(destination, "SQLite backup destination")
        source_conn = self._open_read_only(source)
        target_conn: sqlite3.Connection | None = None
        try:
            target_conn = sqlite3.connect(
                destination,
                timeout=self.busy_timeout_ms / 1000.0,
                isolation_level=None,
            )
            target_conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            source_conn.backup(target_conn)
            target_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            mode = str(
                target_conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            ).lower()
            if mode != "delete":
                raise ProtectedMemoryBackupError(
                    "protected memory backup could not enter single-file journal mode"
                )
            target_conn.commit()
        except (sqlite3.Error, OSError) as exc:
            raise ProtectedMemoryBackupError(
                f"protected memory SQLite backup failed closed: {type(exc).__name__}"
            ) from exc
        finally:
            source_conn.close()
            if target_conn is not None:
                target_conn.close()
        self._remove_auxiliary_files(destination)
        self._regular_database(destination, "SQLite backup destination")

    def _database_integrity(self, path: Path) -> tuple[str, int, int]:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._open_read_only(path)
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
            return integrity, page_count, page_size
        except sqlite3.Error as exc:
            raise ProtectedMemoryBackupError(
                f"protected memory SQLite inspection failed: {type(exc).__name__}"
            ) from exc
        finally:
            if conn is not None:
                conn.close()

    def _open_read_only(self, path: Path) -> sqlite3.Connection:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=self.busy_timeout_ms / 1000.0,
        )
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute("PRAGMA query_only=ON")
        return conn

    @staticmethod
    def _regular_database(path: Path, label: str) -> Path:
        if path.is_symlink() or not path.is_file():
            raise ProtectedMemoryBackupError(f"{label} must be a regular file")
        size = path.stat().st_size
        if size <= 0 or size > MAX_BACKUP_BYTES:
            raise ProtectedMemoryBackupError(f"{label} size is invalid")
        return path

    @staticmethod
    def _require_absent(path: Path, label: str) -> None:
        if path.exists() or path.is_symlink():
            raise ProtectedMemoryBackupError(f"{label} must not already exist")

    @staticmethod
    def _require_regular_parent(path: Path) -> None:
        parent = path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise ProtectedMemoryBackupError(
                "protected memory backup/restore parent must be a regular directory"
            )

    @staticmethod
    def _require_exact_bundle_files(bundle: Path) -> None:
        entries = {entry.name for entry in bundle.iterdir()}
        if entries != {BACKUP_DATABASE_NAME, BACKUP_MANIFEST_NAME}:
            raise ProtectedMemoryBackupError(
                "protected memory backup bundle file inventory mismatch"
            )
        for entry in bundle.iterdir():
            if entry.is_symlink() or not entry.is_file():
                raise ProtectedMemoryBackupError(
                    "protected memory backup bundle contains an irregular entry"
                )

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BACKUP_BYTES:
                    raise ProtectedMemoryBackupError(
                        "protected memory backup exceeds size limit"
                    )
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        raw = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ProtectedMemoryBackupError(
                "protected memory backup manifest is too large"
            )
        path.write_bytes(raw)

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file():
            raise ProtectedMemoryBackupError(
                "protected memory backup manifest must be a regular file"
            )
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_MANIFEST_BYTES:
            raise ProtectedMemoryBackupError(
                "protected memory backup manifest size is invalid"
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtectedMemoryBackupError(
                "protected memory backup manifest is not UTF-8 JSON"
            ) from exc
        if not isinstance(value, dict):
            raise ProtectedMemoryBackupError(
                "protected memory backup manifest must be an object"
            )
        return value

    @staticmethod
    def _remove_auxiliary_files(path: Path) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            auxiliary = Path(str(path) + suffix)
            if auxiliary.exists() or auxiliary.is_symlink():
                auxiliary.unlink(missing_ok=True)

    @classmethod
    def _remove_database_family(cls, path: Path) -> None:
        path.unlink(missing_ok=True)
        cls._remove_auxiliary_files(path)
