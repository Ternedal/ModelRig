#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
    WindowsDpapiMemoryProtectionProvider,
)
from app.agent3.memory_protection_migration import (  # noqa: E402
    MIGRATION_ID,
    MIGRATION_SCHEMA,
    MemoryProtectionMigrationError,
    MemoryProtectionMigrator,
)


class TestAeadProvider:
    provider_id = "test-memory-migration-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(
        self,
        key: bytes = b"t033-migration-test-key-not-for-production",
        *,
        fail_on_protect_call: int | None = None,
    ):
        self.key = key
        self.calls = 0
        self.fail_on_protect_call = fail_on_protect_call

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        result = bytearray()
        block = 0
        while len(result) < length:
            result.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
        return bytes(result[:length])

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        self.calls += 1
        if self.fail_on_protect_call == self.calls:
            raise MemoryProtectionError("injected migration interruption")
        nonce = hashlib.sha256(
            self.key + entropy + self.calls.to_bytes(8, "big")
        ).digest()[:16]
        stream = self._stream(entropy, nonce, len(plaintext))
        encrypted = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(
            self.key, b"tag\x00" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        return nonce + tag + encrypted

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        if len(ciphertext) < 48:
            raise MemoryProtectionError("test migration ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key, b"tag\x00" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("test migration authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


SECRETS = {
    "private": "KALIV-T033-PRIVATE-VALUE-8a7f1c",
    "secret": "KALIV-T033-SECRET-VALUE-9b2d4e",
    "source": "KALIV-T033-SOURCE-REF-4c6f8a",
    "old": "KALIV-T033-SUPERSEDED-OLD-1d3f5b",
    "new": "KALIV-T033-SUPERSEDED-NEW-2e4a6c",
}
PUBLIC_VALUE = "KALIV-T033-PUBLIC-VISIBLE"
OPERATIONAL_VALUE = "KALIV-T033-OPERATIONAL-VISIBLE"

checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def expect_error(label: str, fn, contains: str | None = None) -> None:
    try:
        fn()
    except MemoryProtectionMigrationError as exc:
        check(label, contains is None or contains in str(exc))
    except Exception:
        check(label, False)
    else:
        check(label, False)


def seed(path: Path) -> dict[str, str]:
    store = MemoryStore(str(path))
    ids: dict[str, str] = {}
    try:
        ids["public"] = store.create(
            subject="system",
            predicate="public_value",
            value=PUBLIC_VALUE,
            sensitivity="public",
        ).id
        ids["operational"] = store.create(
            subject="system",
            predicate="operational_value",
            value=OPERATIONAL_VALUE,
            sensitivity="operational",
        ).id
        ids["private"] = store.create(
            subject="Anders",
            predicate="private_value",
            value=SECRETS["private"],
            sensitivity="private",
            source_ref=SECRETS["source"],
        ).id
        ids["secret"] = store.create(
            subject="Anders",
            predicate="secret_value",
            value=SECRETS["secret"],
            sensitivity="secret",
        ).id
        ids["deleted"] = store.create(
            subject="Anders",
            predicate="deleted_value",
            value="KALIV-T033-DELETED-ERASED",
            sensitivity="private",
        ).id
        store.delete(ids["deleted"])
        old = store.create(
            subject="Anders",
            predicate="corrected_value",
            value=SECRETS["old"],
            sensitivity="private",
        )
        ids["old"] = old.id
        ids["new"] = store.correct(old.id, value=SECRETS["new"]).id
    finally:
        store.close()
    return ids


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def family_bytes(path: Path) -> bytes:
    result = bytearray()
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        if candidate.is_file():
            result.extend(candidate.read_bytes())
    return bytes(result)


def has_no_protected_plaintext(path: Path) -> bool:
    raw = family_bytes(path)
    return all(value.encode("utf-8") not in raw for value in SECRETS.values())


def clone(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
    for suffix in ("-wal", "-shm", "-journal"):
        companion = Path(str(source) + suffix)
        if companion.is_file():
            shutil.copy2(companion, Path(str(destination) + suffix))


def completed_store(root: Path) -> tuple[Path, dict[str, str]]:
    path = root / "memory.db"
    ids = seed(path)
    summary = MemoryProtectionMigrator(
        path,
        MemoryProtectionCodec(TestAeadProvider()),
        clock=lambda: 1_900_000_001.0,
    ).migrate()
    check("complete migration reaches completed state", summary.complete)
    return path, ids


with tempfile.TemporaryDirectory(prefix="kaliv-t033-partial-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    seed(db)
    migrator = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        clock=lambda: 1_900_000_000.0,
    )
    partial = migrator.migrate(batch_limit=1)
    check("one-row batch remains incomplete", not partial.complete)
    check("partial migration stays running", partial.state == "running")
    check("partial migration commits exactly one complete row", partial.batch_commits == 1)
    check("partial migration reports remaining plaintext", partial.rows_remaining_plaintext > 0)
    check("partial migration does not claim scrub", partial.scrub_completed is False)
    check("partial migration can be inspected", migrator.inspect().batch_commits == 1)

    resumed = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        clock=lambda: 1_900_000_001.0,
    ).migrate()
    check("partial migration resumes to completion", resumed.complete)
    check("resume leaves no protected plaintext rows", resumed.rows_remaining_plaintext == 0)
    check("deleted protected row is redacted", resumed.rows_redacted == 1)
    check("source-ref count is metadata only", resumed.source_refs_protected == 1)
    check("summary remains non-activating", resumed.to_dict()["production_activation"] is False)
    check("completed database family has no protected plaintext", has_no_protected_plaintext(db))

with tempfile.TemporaryDirectory(prefix="kaliv-t033-complete-") as tmp:
    root = Path(tmp)
    db, ids = completed_store(root)
    conn = connect(db)
    try:
        rows = {
            row["id"]: row
            for row in conn.execute("SELECT * FROM agent_memories").fetchall()
        }
        check("public row remains readable", rows[ids["public"]]["value"] == PUBLIC_VALUE)
        check(
            "operational row remains readable",
            rows[ids["operational"]]["value"] == OPERATIONAL_VALUE,
        )
        for name in ("private", "secret", "old", "new"):
            row = rows[ids[name]]
            check(f"{name} plaintext is cleared", row["value"] == "")
            check(f"{name} row is protected", row["protection_state"] == "protected")
            check(
                f"{name} envelope exists",
                isinstance(row["value_protected"], str) and bool(row["value_protected"]),
            )
        private = rows[ids["private"]]
        check("source-ref plaintext is cleared", private["source_ref"] is None)
        check(
            "source-ref envelope exists",
            isinstance(private["source_ref_protected"], str)
            and bool(private["source_ref_protected"]),
        )
        deleted = rows[ids["deleted"]]
        check("deleted row is payload-free redacted", deleted["protection_state"] == "redacted" and deleted["value_protected"] is None)

        receipt = conn.execute(
            "SELECT * FROM agent_memory_protection_migrations WHERE id=?",
            (MIGRATION_ID,),
        ).fetchone()
        check("migration receipt uses exact schema", receipt["schema"] == MIGRATION_SCHEMA)
        check("migration receipt is completed", receipt["state"] == "completed" and receipt["scrub_completed"] == 1)
        receipt_json = json.dumps(dict(receipt), sort_keys=True)
        check("migration receipt stores no sensitive value", all(value not in receipt_json for value in SECRETS.values()))
        index_sql = "\n".join(
            str(row[0] or "")
            for row in conn.execute("SELECT sql FROM sqlite_master WHERE type='index'")
        )
        check("protected envelope columns are not indexed", "value_protected" not in index_sql and "source_ref_protected" not in index_sql)
    finally:
        conn.close()

    check("completed SQLite/WAL/journal bytes contain no protected plaintext", has_no_protected_plaintext(db))
    check("public value is not falsely scrubbed", PUBLIC_VALUE.encode("utf-8") in family_bytes(db))

    backup = root / "memory-backup.db"
    source = connect(db)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    check("post-migration SQLite backup has no protected plaintext", has_no_protected_plaintext(backup))
    check(
        "post-migration backup validates in the same scope",
        MemoryProtectionMigrator(
            backup,
            MemoryProtectionCodec(TestAeadProvider()),
        ).inspect().complete,
    )

    stable = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate(finalize=False)
    check("completed migration is resumably inspectable", stable.complete)

    changed_scope = root / "changed-scope.db"
    clone(db, changed_scope)
    conn = connect(changed_scope)
    try:
        conn.execute(
            "UPDATE agent_memories SET predicate='changed_after_protection' WHERE id=?",
            (ids["private"],),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "moving envelope to changed row scope fails closed",
        lambda: MemoryProtectionMigrator(
            changed_scope,
            MemoryProtectionCodec(TestAeadProvider()),
        ).inspect(),
        "inspection failed closed",
    )

    restored = root / "restored-plaintext.db"
    clone(db, restored)
    conn = connect(restored)
    try:
        conn.execute(
            "UPDATE agent_memories SET value='RESTORED-PLAINTEXT' WHERE id=?",
            (ids["private"],),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "restored plaintext in protected row fails closed",
        lambda: MemoryProtectionMigrator(
            restored,
            MemoryProtectionCodec(TestAeadProvider()),
        ).inspect(),
        "retains readable plaintext",
    )

    tampered = root / "tampered-cipher.db"
    clone(db, tampered)
    conn = connect(tampered)
    try:
        envelope = json.loads(
            conn.execute(
                "SELECT value_protected FROM agent_memories WHERE id=?",
                (ids["secret"],),
            ).fetchone()[0]
        )
        ciphertext = bytearray(base64.b64decode(envelope["ciphertext_b64"]))
        ciphertext[-1] ^= 1
        envelope["ciphertext_b64"] = base64.b64encode(ciphertext).decode("ascii")
        envelope["ciphertext_sha256"] = hashlib.sha256(ciphertext).hexdigest()
        conn.execute(
            "UPDATE agent_memories SET value_protected=? WHERE id=?",
            (json.dumps(envelope, sort_keys=True, separators=(",", ":")), ids["secret"]),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "rewritten digest cannot bypass provider authentication",
        lambda: MemoryProtectionMigrator(
            tampered,
            MemoryProtectionCodec(TestAeadProvider()),
        ).inspect(),
        "inspection failed closed",
    )

    partial_public = root / "partial-public.db"
    clone(db, partial_public)
    conn = connect(partial_public)
    try:
        conn.execute(
            "UPDATE agent_memories SET protection_schema='unexpected' WHERE id=?",
            (ids["public"],),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "partial protection metadata on public row fails closed",
        lambda: MemoryProtectionMigrator(
            partial_public,
            MemoryProtectionCodec(TestAeadProvider()),
        ).inspect(),
        "partial protection metadata",
    )

    drift_provider = TestAeadProvider()
    drift_provider.provider_id = "different-provider"
    expect_error(
        "resume under another provider fails closed",
        lambda: MemoryProtectionMigrator(
            db,
            MemoryProtectionCodec(drift_provider),
        ).inspect(),
        "provider mismatch",
    )

    unknown = root / "unknown-state.db"
    clone(db, unknown)
    conn = connect(unknown)
    try:
        conn.execute(
            "UPDATE agent_memories SET protection_state='future' WHERE id=?",
            (ids["private"],),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "unknown protection state fails closed",
        lambda: MemoryProtectionMigrator(
            unknown,
            MemoryProtectionCodec(TestAeadProvider()),
        ).inspect(),
        "unknown protection state",
    )

    expect_error(
        "zero batch limit is rejected",
        lambda: MemoryProtectionMigrator(
            db,
            MemoryProtectionCodec(TestAeadProvider()),
        ).migrate(batch_limit=0),
        "at least one",
    )

with tempfile.TemporaryDirectory(prefix="kaliv-t033-crash-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    seed(db)
    failing = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider(fail_on_protect_call=3)),
    )
    expect_error(
        "provider interruption stops the next row",
        lambda: failing.migrate(finalize=False),
        "failed closed",
    )
    interrupted = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    ).inspect()
    check("one complete row remains durable before interruption", interrupted.batch_commits == 1)
    check("interrupted migration stays incomplete", interrupted.rows_remaining_plaintext > 0 and not interrupted.complete)
    resumed = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate()
    check("interrupted migration resumes to completion", resumed.complete)
    check("resumed database has no protected plaintext", has_no_protected_plaintext(db))

with tempfile.TemporaryDirectory(prefix="kaliv-t033-path-") as tmp:
    root = Path(tmp)
    expect_error(
        "missing database is rejected",
        lambda: MemoryProtectionMigrator(
            root / "missing.db",
            MemoryProtectionCodec(TestAeadProvider()),
        ),
        "regular file",
    )
    empty = root / "empty.db"
    empty.touch()
    expect_error(
        "empty database is rejected",
        lambda: MemoryProtectionMigrator(
            empty,
            MemoryProtectionCodec(TestAeadProvider()),
        ),
        "empty",
    )

if os.name == "nt":
    with tempfile.TemporaryDirectory(prefix="kaliv-t033-dpapi-migration-") as tmp:
        root = Path(tmp)
        db = root / "memory.db"
        seed(db)
        summary = MemoryProtectionMigrator(
            db,
            MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
        ).migrate()
        check("real Windows DPAPI migrates the complete store", summary.complete)
        check("real Windows DPAPI migration scrubs raw protected values", has_no_protected_plaintext(db))
else:
    check("real DPAPI SQLite migration is reserved for windows-latest", True)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== AGENT3 MEMORY PROTECTION MIGRATION: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
