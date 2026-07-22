from __future__ import annotations

import uuid
from typing import Any

from .memory_protection import (
    MemoryProtectionError,
    MemoryProtector,
    open_text,
    parse_envelope,
    seal_text,
)


def _protector_identity(protector: MemoryProtector) -> tuple[str, str]:
    provider = getattr(protector, "provider", None)
    key_id = getattr(protector, "key_id", None)
    if not isinstance(provider, str) or not provider.strip():
        raise MemoryProtectionError("rotation protector provider is missing")
    if not isinstance(key_id, str) or not key_id.strip():
        raise MemoryProtectionError("rotation protector key id is missing")
    if len(provider.strip()) > 100 or len(key_id.strip()) > 200:
        raise MemoryProtectionError("rotation protector identity is too long")
    return provider.strip(), key_id.strip()


def rotate_protection(
    self: Any,
    new_protector: MemoryProtector,
    *,
    rotate_scope: bool = False,
) -> dict[str, Any]:
    """Atomically rewrap every live sensitive field.

    The whole row set and optional database scope move in one SQLite transaction.
    Any open/seal/verification failure rolls every row back and keeps the current
    protector active. After commit, old ciphertext pages are compacted; if that
    final physical cleanup fails, the committed rotation remains usable and a
    durable marker makes the next store open retry compaction before returning.
    """
    try:
        target_provider, target_key_id = _protector_identity(new_protector)
    except MemoryProtectionError as exc:
        raise self._store_error("invalid memory rotation protector") from exc

    old_protector = self._protector
    old_scope = self._store_scope
    target_scope = uuid.uuid4().hex if rotate_scope else old_scope

    with self._lock:
        rows = self._conn.execute(
            "SELECT id,value,source_ref,lifecycle_status "
            "FROM agent_memories "
            "WHERE sensitivity IN ('private','secret') ORDER BY id"
        ).fetchall()

        live_rows = [row for row in rows if row["lifecycle_status"] != "deleted"]
        already_target = bool(live_rows) and all(
            parse_envelope(row["value"]).provider == target_provider
            and parse_envelope(row["value"]).key_id == target_key_id
            and parse_envelope(row["value"]).store_scope == target_scope
            and (
                row["source_ref"] is None
                or (
                    parse_envelope(row["source_ref"]).provider == target_provider
                    and parse_envelope(row["source_ref"]).key_id == target_key_id
                    and parse_envelope(row["source_ref"]).store_scope == target_scope
                )
            )
            for row in live_rows
        )
        if already_target and not rotate_scope:
            self._protector = new_protector
            return {
                "rotated_records": 0,
                "old_store_scope": old_scope,
                "new_store_scope": old_scope,
                "provider": target_provider,
                "key_id": target_key_id,
                "generation": int(self._meta_value("protection_rotation_generation") or 0),
                "compaction_pending": False,
                "no_op": True,
            }

        generation = int(self._meta_value("protection_rotation_generation") or 0) + 1
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            rotated = 0
            for row in live_rows:
                memory_id = str(row["id"])
                try:
                    plaintext_value = open_text(
                        old_protector,
                        row["value"],
                        store_scope=old_scope,
                        record_id=memory_id,
                        field="value",
                    )
                    stored_value = seal_text(
                        new_protector,
                        plaintext_value,
                        store_scope=target_scope,
                        record_id=memory_id,
                        field="value",
                    )
                    # Verify the newly produced envelope before any row is updated.
                    if open_text(
                        new_protector,
                        stored_value,
                        store_scope=target_scope,
                        record_id=memory_id,
                        field="value",
                    ) != plaintext_value:
                        raise MemoryProtectionError("rotation value verification failed")

                    stored_source_ref = row["source_ref"]
                    if row["source_ref"] is not None:
                        plaintext_source = open_text(
                            old_protector,
                            row["source_ref"],
                            store_scope=old_scope,
                            record_id=memory_id,
                            field="source_ref",
                        )
                        stored_source_ref = seal_text(
                            new_protector,
                            plaintext_source,
                            store_scope=target_scope,
                            record_id=memory_id,
                            field="source_ref",
                        )
                        if open_text(
                            new_protector,
                            stored_source_ref,
                            store_scope=target_scope,
                            record_id=memory_id,
                            field="source_ref",
                        ) != plaintext_source:
                            raise MemoryProtectionError(
                                "rotation source reference verification failed"
                            )
                except MemoryProtectionError as exc:
                    raise self._store_error(
                        f"sensitive memory rotation failed for {memory_id}"
                    ) from exc

                changed = self._conn.execute(
                    "UPDATE agent_memories SET value=?,source_ref=? "
                    "WHERE id=? AND value=? AND "
                    "((source_ref IS NULL AND ? IS NULL) OR source_ref=?)",
                    (
                        stored_value,
                        stored_source_ref,
                        memory_id,
                        row["value"],
                        row["source_ref"],
                        row["source_ref"],
                    ),
                ).rowcount
                if changed != 1:
                    raise self._store_error(
                        "sensitive memory changed during protection rotation"
                    )
                rotated += 1

            self._conn.execute(
                "INSERT OR REPLACE INTO agent_memory_meta(key,value) "
                "VALUES('store_scope',?)",
                (target_scope,),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO agent_memory_meta(key,value) "
                "VALUES('protection_provider',?)",
                (target_provider,),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO agent_memory_meta(key,value) "
                "VALUES('protection_key_id',?)",
                (target_key_id,),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO agent_memory_meta(key,value) "
                "VALUES('protection_rotation_generation',?)",
                (str(generation),),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO agent_memory_meta(key,value) "
                "VALUES('protection_compaction_pending','1')"
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        # The durable store now requires the new protector/scope. Switch the live
        # object immediately, even if physical page compaction must be retried.
        self._protector = new_protector
        self._store_scope = target_scope

    compaction_pending = False
    try:
        self._compact_after_sensitive_migration()
    except self._store_error:
        compaction_pending = True
    else:
        with self._transaction():
            self._conn.execute(
                "DELETE FROM agent_memory_meta "
                "WHERE key='protection_compaction_pending'"
            )

    return {
        "rotated_records": len(live_rows),
        "old_store_scope": old_scope,
        "new_store_scope": target_scope,
        "provider": target_provider,
        "key_id": target_key_id,
        "generation": generation,
        "compaction_pending": compaction_pending,
        "no_op": False,
    }


def install(memory_store_cls: type) -> None:
    if getattr(memory_store_cls, "_kaliv_protection_rotation_installed", False):
        return
    memory_store_cls.rotate_protection = rotate_protection
    memory_store_cls._kaliv_protection_rotation_installed = True
