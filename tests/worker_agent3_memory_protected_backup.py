#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_protected_backup import (  # noqa: E402
    BACKUP_DATABASE_NAME,
    BACKUP_MANIFEST_NAME,
    BACKUP_SCHEMA,
    ProtectedMemoryBackupError,
    ProtectedMemoryBackupManager,
)
from app.agent3.memory_protected_reader import (  # noqa: E402
    MemoryReadAccess,
    ProtectedMemoryReader,
)
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
    WindowsDpapiMemoryProtectionProvider,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402


class TestAeadProvider:
    provider_id = "test-protected-backup-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"t033-backup-test-key-not-production"):
        self.key = key
        self.calls = 0

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < length:
            output.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + counter.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            counter += 1
        return bytes(output[:length])

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        self.calls += 1
        nonce = hashlib.sha256(
            self.key + entropy + self.calls.to_bytes(8, "big")
        ).digest()[:16]
        stream = self._stream(entropy, nonce, len(plaintext))
        encrypted = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        return nonce + tag + encrypted

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        if len(ciphertext) < 48:
            raise MemoryProtectionError("backup ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("backup ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


PRIVATE_VALUE = "PRIVATE-BACKUP-CANARY-2f68d49b"
PRIVATE_SOURCE = "PRIVATE-BACKUP-SOURCE-81d7f6a3"
SECRET_VALUE = "SECRET-BACKUP-CANARY-c8a31e75"
PUBLIC_VALUE = "PUBLIC-BACKUP-VALUE"

checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def expect_backup_error(label: str, fn, contains: str | None = None) -> None:
    try:
        fn()
    except ProtectedMemoryBackupError as exc:
        check(label, contains is None or contains in str(exc))
    except Exception:
        check(label, False)
    else:
        check(label, False)


def seed(path: Path) -> dict[str, str]:
    store = MemoryStore(str(path))
    try:
        return {
            "public": store.create(
                subject="system",
                predicate="backup_public",
                value=PUBLIC_VALUE,
                sensitivity="public",
            ).id,
            "private": store.create(
                subject="Anders",
                predicate="backup_private",
                value=PRIVATE_VALUE,
                sensitivity="private",
                source_ref=PRIVATE_SOURCE,
            ).id,
            "secret": store.create(
                subject="Anders",
                predicate="backup_secret",
                value=SECRET_VALUE,
                sensitivity="secret",
            ).id,
        }
    finally:
        store.close()


def migrated(path: Path, codec: MemoryProtectionCodec) -> dict[str, str]:
    ids = seed(path)
    summary = MemoryProtectionMigrator(path, codec).migrate()
    if not summary.complete:
        raise AssertionError("fixture migration did not complete")
    return ids


def read_manifest(bundle: Path) -> dict:
    return json.loads((bundle / BACKUP_MANIFEST_NAME).read_text(encoding="utf-8"))


def mutate_bundle(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


with tempfile.TemporaryDirectory(prefix="kaliv-t033-backup-") as tmp:
    root = Path(tmp)
    codec = MemoryProtectionCodec(TestAeadProvider())
    database = root / "memory.db"
    ids = migrated(database, codec)
    manager = ProtectedMemoryBackupManager(codec, clock=lambda: 1_900_000_000.0)
    bundle = root / "bundle"

    created = manager.create(database, bundle)
    check("backup summary schema is exact", created.schema == BACKUP_SCHEMA)
    check(
        "backup bundle contains exactly database and manifest",
        {path.name for path in bundle.iterdir()}
        == {BACKUP_DATABASE_NAME, BACKUP_MANIFEST_NAME},
    )
    manifest = read_manifest(bundle)
    check(
        "manifest remains ciphertext-only and non-activating",
        manifest["production_activation"] is False
        and manifest["restore_policy"]["physical_windows_restore_required"] is True
        and PRIVATE_VALUE not in json.dumps(manifest)
        and PRIVATE_SOURCE not in json.dumps(manifest)
        and SECRET_VALUE not in json.dumps(manifest),
    )
    bundle_bytes = b"".join(path.read_bytes() for path in bundle.iterdir())
    check(
        "private secret and source canaries are absent from backup files",
        PRIVATE_VALUE.encode() not in bundle_bytes
        and PRIVATE_SOURCE.encode() not in bundle_bytes
        and SECRET_VALUE.encode() not in bundle_bytes,
    )
    check(
        "verification ids are bounded protected rows",
        1 <= len(manifest["verification_memory_ids"]) <= 3
        and set(manifest["verification_memory_ids"]).issubset(
            {ids["private"], ids["secret"]}
        ),
    )

    verified = manager.verify(bundle)
    check(
        "backup independently verifies without opening values",
        verified.artifact_sha256 == manifest["artifact"]["sha256"]
        and verified.key_open_verified == 0,
    )

    restored = root / "restored.db"
    restored_summary = manager.restore(bundle, restored)
    check(
        "restore performs bounded key opens before atomic visibility",
        restored.is_file()
        and restored_summary.key_open_verified
        == len(manifest["verification_memory_ids"]),
    )
    with ProtectedMemoryReader(restored, codec) as reader:
        private = reader.get(ids["private"], access=MemoryReadAccess.LOCAL_MANAGEMENT)
        secret = reader.get(ids["secret"], access=MemoryReadAccess.LOCAL_MANAGEMENT)
    check(
        "restored protected values reopen under the same scope",
        private.value == PRIVATE_VALUE
        and private.source_ref == PRIVATE_SOURCE
        and secret.value == SECRET_VALUE,
    )
    check(
        "restore leaves a single SQLite file",
        not Path(str(restored) + "-wal").exists()
        and not Path(str(restored) + "-shm").exists()
        and not Path(str(restored) + "-journal").exists(),
    )

    wrong_key_manager = ProtectedMemoryBackupManager(
        MemoryProtectionCodec(TestAeadProvider(b"different-backup-key"))
    )
    wrong_destination = root / "wrong-key.db"
    expect_backup_error(
        "wrong key fails before destination becomes visible",
        lambda: wrong_key_manager.restore(bundle, wrong_destination),
        "current key scope",
    )
    check(
        "wrong-key restore leaves no destination family",
        not wrong_destination.exists()
        and not Path(str(wrong_destination) + "-wal").exists()
        and not Path(str(wrong_destination) + "-shm").exists(),
    )

    existing_destination = root / "existing.db"
    existing_destination.write_bytes(b"do-not-overwrite")
    expect_backup_error(
        "restore never overwrites an existing destination",
        lambda: manager.restore(bundle, existing_destination),
        "must not already exist",
    )
    check(
        "existing destination bytes remain unchanged",
        existing_destination.read_bytes() == b"do-not-overwrite",
    )

    existing_bundle = root / "existing-bundle"
    existing_bundle.mkdir()
    expect_backup_error(
        "backup never replaces an existing bundle",
        lambda: manager.create(database, existing_bundle),
        "must not already exist",
    )

    incomplete = root / "incomplete.db"
    seed(incomplete)
    expect_backup_error(
        "unmigrated source cannot be backed up",
        lambda: manager.create(incomplete, root / "incomplete-bundle"),
        "failed closed",
    )

    tampered = mutate_bundle(bundle, root / "tampered")
    with (tampered / BACKUP_DATABASE_NAME).open("ab") as handle:
        handle.write(b"tamper")
    expect_backup_error(
        "artifact tamper fails digest verification",
        lambda: manager.verify(tampered),
        "digest mismatch",
    )

    extra = mutate_bundle(bundle, root / "extra")
    (extra / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    expect_backup_error(
        "extra bundle files fail closed",
        lambda: manager.verify(extra),
        "file inventory mismatch",
    )

    changed_manifest = mutate_bundle(bundle, root / "changed-manifest")
    changed = read_manifest(changed_manifest)
    changed["unexpected"] = True
    (changed_manifest / BACKUP_MANIFEST_NAME).write_text(
        json.dumps(changed, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    expect_backup_error(
        "manifest key drift fails closed",
        lambda: manager.verify(changed_manifest),
        "manifest keys mismatch",
    )

    changed_ids = mutate_bundle(bundle, root / "changed-ids")
    changed = read_manifest(changed_ids)
    changed["verification_memory_ids"] = [ids["public"]]
    (changed_ids / BACKUP_MANIFEST_NAME).write_text(
        json.dumps(changed, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    expect_backup_error(
        "verification id drift fails closed",
        lambda: manager.verify(changed_ids),
        "verification ids do not match",
    )

if os.name == "nt":
    with tempfile.TemporaryDirectory(prefix="kaliv-t033-backup-dpapi-") as tmp:
        root = Path(tmp)
        codec = MemoryProtectionCodec(WindowsDpapiMemoryProtectionProvider())
        database = root / "memory.db"
        ids = migrated(database, codec)
        manager = ProtectedMemoryBackupManager(codec)
        bundle = root / "bundle"
        manager.create(database, bundle)
        restored = root / "restored.db"
        summary = manager.restore(bundle, restored)
        with ProtectedMemoryReader(restored, codec) as reader:
            private = reader.get(
                ids["private"], access=MemoryReadAccess.LOCAL_MANAGEMENT
            )
            secret = reader.get(
                ids["secret"], access=MemoryReadAccess.LOCAL_MANAGEMENT
            )
        raw = b"".join(path.read_bytes() for path in bundle.iterdir())
        check(
            "real Windows DPAPI backup restores under the same current user",
            summary.key_open_verified >= 1
            and private.value == PRIVATE_VALUE
            and secret.value == SECRET_VALUE,
        )
        check(
            "real Windows DPAPI bundle contains no protected canary plaintext",
            PRIVATE_VALUE.encode() not in raw
            and PRIVATE_SOURCE.encode() not in raw
            and SECRET_VALUE.encode() not in raw,
        )
else:
    check("real Windows DPAPI backup fixture is Windows-only", True)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== AGENT3 PROTECTED MEMORY BACKUP: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
