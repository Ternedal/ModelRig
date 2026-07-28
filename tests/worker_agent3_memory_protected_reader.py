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

from app.agent3.memory import MemoryNotFound, MemoryStore  # noqa: E402
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
    ProtectedMemoryReadError,
    ProtectedMemoryReader,
)
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
    WindowsDpapiMemoryProtectionProvider,
)
from app.agent3.memory_protection_migration import (  # noqa: E402
    MemoryProtectionMigrator,
)


class TestAeadProvider:
    provider_id = "test-protected-reader-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"t033-reader-test-key-not-production"):
        self.key = key
        self.calls = 0

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
            raise MemoryProtectionError("reader ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key, b"tag\x00" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("reader ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


VALUES = {
    "public": "PUBLIC-READER-VALUE",
    "operational": "OPERATIONAL-READER-VALUE",
    "private": "PRIVATE-READER-VALUE-7f3a",
    "private_source": "PRIVATE-READER-SOURCE-2d8c",
    "secret": "SECRET-READER-VALUE-9e1b",
    "search_only": "VALUE-ONLY-SEARCH-TOKEN-5c4d",
}

checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def expect_error(label: str, fn, contains: str | None = None) -> None:
    try:
        fn()
    except (ProtectedMemoryReadError, MemoryNotFound) as exc:
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
            predicate="public_reader",
            value=VALUES["public"],
            sensitivity="public",
        ).id
        ids["operational"] = store.create(
            subject="rig",
            predicate="operational_reader",
            value=VALUES["operational"],
            sensitivity="operational",
        ).id
        ids["private"] = store.create(
            subject="Anders",
            predicate="favorite_reader_topic",
            value=VALUES["private"],
            sensitivity="private",
            source_ref=VALUES["private_source"],
        ).id
        ids["value_search"] = store.create(
            subject="Anders",
            predicate="opaque_fact",
            value=VALUES["search_only"],
            sensitivity="private",
        ).id
        ids["secret"] = store.create(
            subject="Anders",
            predicate="secret_reader",
            value=VALUES["secret"],
            sensitivity="secret",
        ).id
        ids["pending"] = store.create(
            subject="Anders",
            predicate="pending_reader",
            value="PENDING-PRIVATE",
            sensitivity="private",
            source_type="inferred",
        ).id
        ids["expired"] = store.create(
            subject="Anders",
            predicate="expired_reader",
            value="EXPIRED-PRIVATE",
            sensitivity="private",
            expires_at=1.0,
        ).id
        ids["deleted"] = store.create(
            subject="Anders",
            predicate="deleted_reader",
            value="DELETED-PRIVATE",
            sensitivity="private",
        ).id
        store.delete(ids["deleted"])
        old = store.create(
            subject="Anders",
            predicate="history_reader",
            value="OLD-PRIVATE",
            sensitivity="private",
        )
        ids["history_old"] = old.id
        ids["history_new"] = store.correct(old.id, value="NEW-PRIVATE").id
    finally:
        store.close()
    return ids


def migrate(path: Path, provider: TestAeadProvider | WindowsDpapiMemoryProtectionProvider):
    return MemoryProtectionMigrator(
        path,
        MemoryProtectionCodec(provider),
    ).migrate()


def clone(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
    for suffix in ("-wal", "-shm", "-journal"):
        companion = Path(str(source) + suffix)
        if companion.is_file():
            shutil.copy2(companion, Path(str(destination) + suffix))


with tempfile.TemporaryDirectory(prefix="kaliv-t033-reader-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    ids = seed(db)
    provider = TestAeadProvider()
    check("fixture migration completes", migrate(db, provider).complete)

    reader = ProtectedMemoryReader(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    check("reader reports query-only completed migration", reader.status.query_only and reader.status.migration_state == "completed")
    check("reader status remains non-activating", reader.status.to_dict()["production_activation"] is False)
    check("reader exposes no create method", not hasattr(reader, "create"))
    check("reader exposes no correct method", not hasattr(reader, "correct"))
    check("reader exposes no delete method", not hasattr(reader, "delete"))

    metadata = reader.get(ids["private"], access=MemoryReadAccess.METADATA_ONLY)
    check("metadata-only private value is redacted", metadata.value == "[redacted]")
    check("metadata-only source provenance is absent", metadata.source_ref is None)
    public_metadata = reader.get(ids["public"], access=MemoryReadAccess.METADATA_ONLY)
    check("metadata-only also redacts public value", public_metadata.value == "[redacted]")

    private_context = reader.get(ids["private"], access=MemoryReadAccess.LOCAL_CONTEXT)
    check("local context opens private value", private_context.value == VALUES["private"])
    check("local context never reveals source_ref", private_context.source_ref is None)
    secret_context = reader.get(ids["secret"], access=MemoryReadAccess.LOCAL_CONTEXT)
    check("local context does not reveal secret value", secret_context.value == "[redacted]")

    private_management = reader.get(
        ids["private"], access=MemoryReadAccess.LOCAL_MANAGEMENT
    )
    check("local management opens private value", private_management.value == VALUES["private"])
    check("local management opens protected source_ref", private_management.source_ref == VALUES["private_source"])
    secret_management = reader.get(
        ids["secret"], access=MemoryReadAccess.LOCAL_MANAGEMENT
    )
    check("local management explicitly opens secret value", secret_management.value == VALUES["secret"])

    listed_context = reader.list(
        access=MemoryReadAccess.LOCAL_CONTEXT,
        subject="Anders",
        include_secret=False,
        limit=100,
    )
    check("local-context list excludes secret rows", all(item.sensitivity != "secret" for item in listed_context))
    check("local-context list opens private values", any(item.value == VALUES["private"] for item in listed_context))
    expect_error(
        "secret list requires local-management access",
        lambda: reader.list(
            access=MemoryReadAccess.LOCAL_CONTEXT,
            include_secret=True,
        ),
        "local_management",
    )
    listed_management = reader.list(
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
        subject="Anders",
        include_secret=True,
        limit=100,
    )
    check("local-management list can include secret rows", any(item.id == ids["secret"] and item.value == VALUES["secret"] for item in listed_management))

    metadata_match = reader.search_metadata(
        "favorite_reader",
        access=MemoryReadAccess.LOCAL_CONTEXT,
    )
    check("metadata search matches predicate", [item.id for item in metadata_match] == [ids["private"]])
    value_only_match = reader.search_metadata(
        VALUES["search_only"],
        access=MemoryReadAccess.LOCAL_CONTEXT,
    )
    check("metadata search never scans protected values", value_only_match == [])
    wildcard_literal = reader.search_metadata(
        "%_",
        access=MemoryReadAccess.METADATA_ONLY,
    )
    check("metadata search escapes SQL wildcard input", wildcard_literal == [])

    context = reader.context_records(
        access=MemoryReadAccess.LOCAL_CONTEXT,
        subjects=["Anders"],
        include_private=True,
        max_chars=50_000,
        limit=100,
    )
    context_ids = {item.id for item in context}
    check("context includes active confirmed private rows", ids["private"] in context_ids)
    check("context excludes secret rows", ids["secret"] not in context_ids)
    check("context excludes pending rows", ids["pending"] not in context_ids)
    check("context excludes expired rows", ids["expired"] not in context_ids)
    check("context excludes superseded rows", ids["history_old"] not in context_ids)
    check("context never includes source provenance", all(item.source_ref is None for item in context))
    no_private_context = reader.context_records(
        access=MemoryReadAccess.LOCAL_CONTEXT,
        include_private=False,
        max_chars=50_000,
    )
    check("context can exclude private values before decryption", all(item.sensitivity not in {"private", "secret"} for item in no_private_context))
    tiny_context = reader.context_records(
        access=MemoryReadAccess.LOCAL_CONTEXT,
        max_chars=1,
    )
    check("context budget skips oversized decrypted records", tiny_context == [])
    expect_error(
        "context refuses management access",
        lambda: reader.context_records(access=MemoryReadAccess.LOCAL_MANAGEMENT),
        "requires local_context",
    )

    history = reader.history(
        "Anders",
        "history_reader",
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
    )
    check("history opens both protected versions in order", [item.value for item in history] == ["OLD-PRIVATE", "NEW-PRIVATE"])
    deleted = reader.get(
        ids["deleted"],
        access=MemoryReadAccess.LOCAL_MANAGEMENT,
        include_deleted=True,
    )
    check("deleted row remains payload-free", deleted.value == "" and deleted.source_ref is None)
    expect_error(
        "deleted row is hidden by default",
        lambda: reader.get(ids["deleted"], access=MemoryReadAccess.LOCAL_MANAGEMENT),
        "not found",
    )

    expect_error(
        "string access value is rejected",
        lambda: reader.get(ids["private"], access="local_context"),  # type: ignore[arg-type]
        "explicit MemoryReadAccess",
    )
    expect_error(
        "duplicate context subjects are rejected",
        lambda: reader.context_records(
            access=MemoryReadAccess.LOCAL_CONTEXT,
            subjects=["Anders", "Anders"],
        ),
        "unique",
    )
    expect_error(
        "empty query is rejected",
        lambda: reader.search_metadata("", access=MemoryReadAccess.METADATA_ONLY),
        "must not be empty",
    )
    try:
        reader._conn.execute(  # noqa: SLF001 - contract probe
            "UPDATE agent_memories SET predicate='write-attempt' WHERE id=?",
            (ids["public"],),
        )
    except sqlite3.OperationalError:
        check("SQLite query_only rejects writes", True)
    else:
        check("SQLite query_only rejects writes", False)

    reader.close()
    expect_error(
        "closed reader fails closed",
        lambda: reader.get(ids["public"], access=MemoryReadAccess.METADATA_ONLY),
        "closed",
    )

    wrong_provider = TestAeadProvider()
    wrong_provider.provider_id = "wrong-provider"
    expect_error(
        "provider identity mismatch blocks opening",
        lambda: ProtectedMemoryReader(
            db,
            MemoryProtectionCodec(wrong_provider),
        ),
        "provider mismatch",
    )

    wrong_key = root / "wrong-key.db"
    clone(db, wrong_key)
    wrong_reader = ProtectedMemoryReader(
        wrong_key,
        MemoryProtectionCodec(TestAeadProvider(key=b"different-reader-key-material")),
    )
    expect_error(
        "wrong provider key fails only at explicit reveal",
        lambda: wrong_reader.get(
            ids["private"], access=MemoryReadAccess.LOCAL_CONTEXT
        ),
        "could not be opened",
    )
    metadata_wrong_key = wrong_reader.get(
        ids["private"], access=MemoryReadAccess.METADATA_ONLY
    )
    check("metadata inventory needs no decryption key", metadata_wrong_key.value == "[redacted]")
    wrong_reader.close()

    restored_plaintext = root / "restored-plaintext.db"
    clone(db, restored_plaintext)
    conn = sqlite3.connect(restored_plaintext)
    try:
        conn.execute(
            "UPDATE agent_memories SET value='RESTORED' WHERE id=?",
            (ids["private"],),
        )
        conn.commit()
    finally:
        conn.close()
    expect_error(
        "protected plaintext blocks reader startup",
        lambda: ProtectedMemoryReader(
            restored_plaintext,
            MemoryProtectionCodec(TestAeadProvider()),
        ),
        "unsafe private/secret rows",
    )

    changed_scope = root / "changed-scope.db"
    clone(db, changed_scope)
    conn = sqlite3.connect(changed_scope)
    try:
        conn.execute(
            "UPDATE agent_memories SET predicate='changed_scope' WHERE id=?",
            (ids["private"],),
        )
        conn.commit()
    finally:
        conn.close()
    changed_reader = ProtectedMemoryReader(
        changed_scope,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    expect_error(
        "changed row scope fails at explicit reveal",
        lambda: changed_reader.get(
            ids["private"], access=MemoryReadAccess.LOCAL_CONTEXT
        ),
        "could not be opened",
    )
    changed_reader.close()

    tampered = root / "tampered.db"
    clone(db, tampered)
    conn = sqlite3.connect(tampered)
    try:
        envelope = json.loads(
            conn.execute(
                "SELECT value_protected FROM agent_memories WHERE id=?",
                (ids["private"],),
            ).fetchone()[0]
        )
        ciphertext = bytearray(base64.b64decode(envelope["ciphertext_b64"]))
        ciphertext[-1] ^= 1
        envelope["ciphertext_b64"] = base64.b64encode(ciphertext).decode("ascii")
        envelope["ciphertext_sha256"] = hashlib.sha256(ciphertext).hexdigest()
        conn.execute(
            "UPDATE agent_memories SET value_protected=? WHERE id=?",
            (json.dumps(envelope, sort_keys=True, separators=(",", ":")), ids["private"]),
        )
        conn.commit()
    finally:
        conn.close()
    tampered_reader = ProtectedMemoryReader(
        tampered,
        MemoryProtectionCodec(TestAeadProvider()),
    )
    expect_error(
        "rewritten digest cannot bypass provider authentication",
        lambda: tampered_reader.get(
            ids["private"], access=MemoryReadAccess.LOCAL_CONTEXT
        ),
        "could not be opened",
    )
    tampered_reader.close()

with tempfile.TemporaryDirectory(prefix="kaliv-t033-reader-incomplete-") as tmp:
    root = Path(tmp)
    db = root / "memory.db"
    seed(db)
    MemoryProtectionMigrator(
        db,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate(batch_limit=1)
    expect_error(
        "incomplete migration blocks reader startup",
        lambda: ProtectedMemoryReader(
            db,
            MemoryProtectionCodec(TestAeadProvider()),
        ),
        "not complete",
    )

if os.name == "nt":
    with tempfile.TemporaryDirectory(prefix="kaliv-t033-reader-dpapi-") as tmp:
        root = Path(tmp)
        db = root / "memory.db"
        ids = seed(db)
        codec = MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider())
        check("real DPAPI reader fixture migrates", MemoryProtectionMigrator(db, codec).migrate().complete)
        with ProtectedMemoryReader(db, codec) as reader:
            check(
                "real Windows DPAPI reader opens private value",
                reader.get(
                    ids["private"], access=MemoryReadAccess.LOCAL_CONTEXT
                ).value
                == VALUES["private"],
            )
            check(
                "real Windows DPAPI reader opens management source_ref",
                reader.get(
                    ids["private"], access=MemoryReadAccess.LOCAL_MANAGEMENT
                ).source_ref
                == VALUES["private_source"],
            )
else:
    check("real DPAPI protected reader is reserved for windows-latest", True)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== AGENT3 PROTECTED MEMORY READER: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
