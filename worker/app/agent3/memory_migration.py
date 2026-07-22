from __future__ import annotations

import sqlite3
from typing import Any

from .memory_protection import is_protected


def _meta_value(self: Any, key: str) -> str | None:
    row = self._conn.execute(
        "SELECT value FROM agent_memory_meta WHERE key=?", (key,)
    ).fetchone()
    return None if row is None else str(row[0])


def _migrate_legacy_sensitive_rows(self: Any) -> int:
    """Atomically protect every non-deleted legacy sensitive row.

    A mixed batch is never committed. Existing v2 rows are authenticated before
    the store opens, while deleted tombstones remain content-free. Compaction is
    tracked separately because VACUUM cannot run inside the migration transaction;
    a crash between the two is resumed on reopen.
    """
    migrated = 0
    with self._lock:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            rows = self._conn.execute(
                "SELECT id,value,source_ref,schema_version,lifecycle_status "
                "FROM agent_memories "
                "WHERE sensitivity IN ('private','secret') ORDER BY id"
            ).fetchall()
            for row in rows:
                if row["lifecycle_status"] == "deleted":
                    continue
                memory_id = str(row["id"])
                value = row["value"]
                source_ref = row["source_ref"]
                schema_version = int(row["schema_version"])
                if schema_version == 2:
                    if not is_protected(value) or (
                        source_ref is not None and not is_protected(source_ref)
                    ):
                        raise self._store_error(
                            "protected memory schema does not match stored fields"
                        )
                    self._open_field(value, memory_id=memory_id, field="value")
                    if source_ref is not None:
                        self._open_field(
                            source_ref,
                            memory_id=memory_id,
                            field="source_ref",
                        )
                    continue
                if schema_version != 1:
                    raise self._store_error(
                        f"unsupported sensitive memory schema: {schema_version}"
                    )
                if is_protected(value) or (
                    source_ref is not None and is_protected(source_ref)
                ):
                    raise self._store_error(
                        "partial sensitive memory migration detected"
                    )
                stored_value = self._seal_field(
                    value,
                    memory_id=memory_id,
                    field="value",
                )
                stored_source_ref = source_ref
                if source_ref is not None:
                    stored_source_ref = self._seal_field(
                        source_ref,
                        memory_id=memory_id,
                        field="source_ref",
                    )
                changed = self._conn.execute(
                    "UPDATE agent_memories "
                    "SET value=?,source_ref=?,schema_version=2 "
                    "WHERE id=? AND schema_version=1",
                    (stored_value, stored_source_ref, memory_id),
                ).rowcount
                if changed != 1:
                    raise self._store_error(
                        "sensitive memory changed during migration"
                    )
                migrated += 1
            self._conn.execute(
                "INSERT OR REPLACE INTO agent_memory_meta(key,value) "
                "VALUES('protection_schema','2')"
            )
            if migrated:
                self._conn.execute(
                    "INSERT OR REPLACE INTO agent_memory_meta(key,value) "
                    "VALUES('protection_compaction_pending','1')"
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
    return migrated


def _compact_after_sensitive_migration(self: Any) -> None:
    if self._migration_path == ":memory:":
        return
    try:
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("VACUUM")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        raise self._store_error(
            "protected memory migration compaction failed"
        ) from exc


def install(memory_store_cls: type, store_error_cls: type[Exception]) -> None:
    """Install migration on MemoryStore once without changing its public API."""
    if getattr(memory_store_cls, "_kaliv_protection_migration_installed", False):
        return

    original_init = memory_store_cls.__init__

    def guarded_init(self, path: str, *args, **kwargs):
        self._migration_path = path
        self._store_error = store_error_cls
        try:
            original_init(self, path, *args, **kwargs)
            migrated = self._migrate_legacy_sensitive_rows()
            if (
                migrated
                or self._meta_value("protection_compaction_pending") == "1"
            ):
                self._compact_after_sensitive_migration()
                with self._transaction():
                    self._conn.execute(
                        "DELETE FROM agent_memory_meta "
                        "WHERE key='protection_compaction_pending'"
                    )
        except Exception:
            connection = getattr(self, "_conn", None)
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            raise

    memory_store_cls.__init__ = guarded_init
    memory_store_cls._meta_value = _meta_value
    memory_store_cls._migrate_legacy_sensitive_rows = _migrate_legacy_sensitive_rows
    memory_store_cls._compact_after_sensitive_migration = (
        _compact_after_sensitive_migration
    )
    memory_store_cls._kaliv_protection_migration_installed = True
