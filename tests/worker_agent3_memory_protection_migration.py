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


def file_family_bytes(path: Path) -> bytes:
    result = bytearray()
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")):
        if candidate.is_file():
            result.extend(candidate.read_bytes())
    return bytes(result)


def assert_no_sensitive_bytes(path: Path) -> bool:
    raw = file_family_bytes(path)
    return all(secret.encode("utf-8") not in raw for secret in SECRETS.values())


def clone(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
    for suffix in ("-wal", "-shm", "-journal"):
        candidate = Path(str(source) + suffix)
        if candidate.is_file():
            shutil.copy2(candidate, Path(str(destination) + suffix))


with tempfile.TemporaryDirectory(prefix="kaliv-t033-migration-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    ids = seed(db)
    codec = MemoryProtectionCodec(TestAeadProvider())
    migrator = MemoryProtectionMigrator(db, codec, clock=lambda: 1_900_000_000.0)

    partial = migrator.migrate(batch_limit=1, finalize=True)
    check("one-row batch remains explicitly incomplete", not partial.complete)
    check("partial migration keeps a resumable running state", partial.state == "running")
    check("partial migration commits exactly one row", partial.batch_commits == 1)
    check("partial migration reports remaining plaintext", partial.rows_remaining_plaintext > 0)
    check("partial migration never claims scrub completion", partial.scrub_completed is False)

    inspected_partial = migrator.inspect()
    check("partial state can be inspected and resumed", inspected_partial.rows_protected == 1)

    completed = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        clock=lambda: 1_900_000_001.0,
    ).migrate()
    check("resumed migration completes", completed.complete)
    check("all protected rows leave plaintext state", completed.rows_remaining_plaintext == 0)
    check("deleted protected row becomes a payload-free redaction", completed.rows_redacted == 1)
    check("source_ref inventory is recorded without its value", completed.source_refs_protected == 1)
    check("completion runs secure scrub", completed.scrub_completed is True)
    check("summary remains non-activating", completed.to_dict()["production_activation"] is False)

    conn = connect(db)
    try:
        rows = {
            row["id"]: row
            for row in conn.execute("SELECT * FROM agent_memories").fetchall()
        }
        check("public row remains readable and unchanged", rows[ids["public"]]["value"] == PUBLIC_VALUE)
        check("operational row remains readable and unchanged", rows[ids["operational"]]["value"] == OPERATIONAL_VALUE)
        for name in ("private", "secret", "old", "new"):
            row = rows[ids[name]]
            check(f"{name} plaintext value is empty", row["value"] == "")
            check(f"{name} row is protected", row["protection_state"] == "protected")
            check(f"{name} value envelope exists", isinstance(row["value_protected"], str) and bool(row["value_protected"]))
        private = rows[ids["private"]]
        check("private source_ref plaintext is cleared", private["source_ref"] is None)
        check("private source_ref envelope exists", isinstance(private["source_ref_protected"], str) and bool(private["source_ref_protected"]))
        deleted = rows[ids["deleted"]]
        check("deleted row has redacted state", deleted["protection_state"] == "redacted")
        check("deleted row has no protected payload", deleted["value_protected"] is None and deleted["source_ref_protected"] is None)

        migration = conn.execute(
            "SELECT * FROM agent_memory_protection_migrations WHERE id=?",
            (MIGRATION_ID,),
        ).fetchone()
        check("migration receipt uses exact schema", migration["schema"] == MIGRATION_SCHEMA)
        check("migration receipt is completed", migration["state"] == "completed" and migration["scrub_completed"] == 1)
        serialized_migration = json.dumps(dict(migration), sort_keys=True)
        check("migration receipt stores no sensitive value", all(secret not in serialized_migration for secret in SECRETS.values()))

        index_sql = "\n".join(
            str(row[0] or "")
            for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index'"
            ).fetchall()
        )
        check("no index contains protected envelope columns", "value_protected" not in index_sql and "source_ref_protected" not in index_sql)
    finally:
        conn.close()

    check("completed SQLite/WAL family contains no protected plaintext bytes", assert_no_sensitive_bytes(db))
    check("public data is not falsely scrubbed", PUBLIC_VALUE.encode("utf-8") in file_family_bytes(db))

    backup = root / "memory-backup.db"
    source = connect(db)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    check("post-migration SQLite backup contains no protected plaintext", assert_no_sensitive_bytes(backup))
    check(
        "post-migration backup validates in the same scope",
        MemoryProtectionMigrator(
            backup,
            MemoryProtectionCodec(TestAeadProvider()),
        ).inspect().complete,
    )

    completed_again = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
        clock=lambda: 1_900_000_002.0,
    ).migrate(finalize=False)
    check("completed migration is resumably inspectable", completed_again.rows_remaining_plaintext == 0)
    check("completed migration remains complete without another scrub", completed_again.complete)

    tamper_scope = root / "tamper-scope.db"
    clone(db, tamper_scope)
    conn = connect(tamper_scope)
    try:
        conn.execute(
            "UPDATE agent_memories SET predicate='changed_after_protection' WHERE id=?",
            (ids["private"],),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "moving ciphertext to changed row scope fails closed",
        lambda: MemoryProtectionMigrator(
            tamper_scope, MemoryProtectionCodec(TestAeadProvider())
        ).inspect(),
        "inspection failed closed",
    )

    tamper_plaintext = root / "tamper-plaintext.db"
    clone(db, tamper_plaintext)
    conn = connect(tamper_plaintext)
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
            tamper_plaintext, MemoryProtectionCodec(TestAeadProvider())
        ).inspect(),
        "retains readable plaintext",
    )

    tamper_cipher = root / "tamper-cipher.db"
    clone(db, tamper_cipher)
    conn = connect(tamper_cipher)
    try:
        row = conn.execute(
            "SELECT value_protected FROM agent_memories WHERE id=?", (ids["secret"],)
        ).fetchone()
        envelope = json.loads(row[0])
        cipher = bytearray(base64.b64decode(envelope["ciphertext_b64"]))
        cipher[-1] ^= 1
        envelope["ciphertext_b64"] = base64.b64encode(cipher).decode("ascii")
        envelope["ciphertext_sha256"] = hashlib.sha256(cipher).hexdigest()
        conn.execute(
            "UPDATE agent_memories SET value_protected=? WHERE id=?",
            (json.dumps(envelope, sort_keys=True, separators=(",", ":")), ids["secret"]),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "rewritten ciphertext digest cannot bypass provider authentication",
        lambda: MemoryProtectionMigrator(
            tamper_cipher, MemoryProtectionCodec(TestAeadProvider())
        ).inspect(),
        "inspection failed closed",
    )

    partial_public = root / "partial-public.db"
    clone(db, partial_public)
    conn = connect(partial_public)
    try:
        conn.execute(
            "UPDATE agent_memories SET protection_schema=? WHERE id=?",
            ("unexpected", ids["public"]),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "partial metadata on public row fails closed",
        lambda: MemoryProtectionMigrator(
            partial_public, MemoryProtectionCodec(TestAeadProvider())
        ).inspect(),
        "partial protection metadata",
    )

    provider_drift = TestAeadProvider()
    provider_drift.provider_id = "different-provider"
    expect_error(
        "resume with another provider identity fails closed",
        lambda: MemoryProtectionMigrator(
            db, MemoryProtectionCodec(provider_drift)
        ).inspect(),
        "provider mismatch",
    )

    unknown_state = root / "unknown-state.db"
    clone(db, unknown_state)
    conn = connect(unknown_state)
    try:
        conn.execute(
            "UPDATE agent_memories SET protection_state='future' WHERE id=?",
            (ids["private"],),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "unknown row state fails closed",
        lambda: MemoryProtectionMigrator(
            unknown_state, MemoryProtectionCodec(TestAeadProvider())
        ).inspect(),
        "unknown protection state",
    )

    expect_error(
        "invalid zero batch is rejected",
        lambda: MemoryProtectionMigrator(
            db, MemoryProtectionCodec(TestAeadProvider())
        ).migrate(batch_limit=0),
        "at least one",
    )

with tempfile.TemporaryDirectory(prefix="kaliv-t033-crash-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    seed(db)
    failing = MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider(fail_on_protect_call=2)),
    )
    expect_error(
        "injected provider interruption stops the batch",
        lambda: failing.migrate(finalize=False),
        "failed closed",
    )
    interrupted = MemoryProtectionMigrator(
        db, MemoryProtectionCodec(TestAeadProvider())
    ).inspect()
    check("row commits before interruption remain durable", interrupted.batch_commits == 1)
    check("interrupted migration remains explicitly incomplete", interrupted.rows_remaining_plaintext > 0 and not interrupted.complete)
    resumed = MemoryProtectionMigrator(
        db, MemoryProtectionCodec(TestAeadProvider())
    ).migrate()
    check("interrupted migration resumes to completion", resumed.complete)
    check("resumed final database contains no protected plaintext", assert_no_sensitive_bytes(db))

with tempfile.TemporaryDirectory(prefix="kaliv-t033-paths-") as tmp:
    root = Path(tmp)
    missing = root / "missing.db"
    expect_error(
        "missing database is rejected",
        lambda: MemoryProtectionMigrator(
            missing, MemoryProtectionCodec(TestAeadProvider())
        ),
        "regular file",
    )
    empty = root / "empty.db"
    empty.touch()
    expect_error(
        "empty database is rejected",
        lambda: MemoryProtectionMigrator(
            empty, MemoryProtectionCodec(TestAeadProvider())
        ),
        "empty",
    )

if os.name == "nt":
    with tempfile.TemporaryDirectory(prefix="kaliv-t033-dpapi-migration-") as tmp:
        root = Path(tmp)
        db = root / "memory.db"
        seed(db)
        dpapi_summary = MemoryProtectionMigrator(
            db,
            MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider()),
        ).migrate()
        check("real Windows DPAPI migrates the complete SQLite store", dpapi_summary.complete)
        check("real Windows DPAPI migration scrubs raw protected values", assert_no_sensitive_bytes(db))
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
