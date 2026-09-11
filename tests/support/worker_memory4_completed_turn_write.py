from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_protected_lookup import ProtectedMemoryVerbatimLookupMigrator
from app.agent3.memory_protected_reader import MemoryReadAccess, ProtectedMemoryReader
from app.agent3.memory_protected_writer import MemoryWriteAccess, ProtectedMemoryWriter
from app.agent3.memory_protection import (
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator
from app.agent3.memory_turn_commit import (
    commit_indexed_protected_candidates,
    commit_legacy_candidates,
    commit_protected_candidates,
)
from app.memory import (
    MEMORY_CANDIDATE_SCHEMA,
    TURN_WRITE_RECEIPT_SCHEMA,
    CompletedMemoryTurn,
    DurableCandidateWrite,
    MemoryCandidate,
    MemoryCandidateExtractor,
    MemoryCompletedTurnWriteService,
    MemoryExtractionError,
    MemoryTurnWriteError,
)


class TestAeadProvider:
    provider_id = "test-memory4-w03-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"memory4-w03-test-provider-key-v1"):
        self.key = key
        self.calls = 0

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        output = bytearray()
        block = 0
        while len(output) < length:
            output.extend(
                hmac.new(
                    self.key,
                    b"stream\x00" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
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
            raise MemoryProtectionError("W03 test ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("W03 test ciphertext authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_write_error(name, factory, contains: str | None = None):
    try:
        asyncio.run(factory())
    except MemoryTurnWriteError as exc:
        check(contains is None or contains in str(exc), name)
    except Exception as exc:
        print(f"    unexpected {type(exc).__name__}: {exc}")
        check(False, name)
    else:
        check(False, name)


def confirmed(value: str, source_ref: str) -> MemoryCandidate:
    return MemoryCandidate(
        subject="user",
        predicate="verbatim_user_statement",
        value=value,
        kind="note",
        sensitivity="private",
        source_type="user_explicit",
        source_ref=source_ref,
        confidence=1.0,
        review_status="confirmed",
        evidence=value,
    )


def extractor_json(
    *,
    subject: str,
    predicate: str,
    value: str,
    kind: str,
    sensitivity: str,
    source_type: str,
    confidence: float,
    evidence: str,
) -> str:
    return json.dumps(
        {
            "schema": MEMORY_CANDIDATE_SCHEMA,
            "candidates": [
                {
                    "subject": subject,
                    "predicate": predicate,
                    "value": value,
                    "kind": kind,
                    "sensitivity": sensitivity,
                    "source_type": source_type,
                    "confidence": confidence,
                    "evidence": evidence,
                }
            ],
        },
        ensure_ascii=False,
    )


def extractor_for(raw: str):
    async def extract_raw(_turn: CompletedMemoryTurn) -> str:
        return raw

    return MemoryCandidateExtractor(extract=extract_raw).extract


def row_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM agent_memories").fetchone()[0])
    finally:
        conn.close()


# Empty W01 output never crosses the store boundary.
commit_calls = 0


async def empty_extract(_turn: CompletedMemoryTurn) -> tuple[MemoryCandidate, ...]:
    return ()


def forbidden_commit(_candidates: tuple[MemoryCandidate, ...]) -> DurableCandidateWrite:
    global commit_calls
    commit_calls += 1
    raise AssertionError("empty/invalid extraction must not commit")


empty_service = MemoryCompletedTurnWriteService(
    extract=empty_extract,
    commit=forbidden_commit,
)
empty = asyncio.run(
    empty_service.commit_completed_turn(
        CompletedMemoryTurn(
            user_text="Ingen varig information her",
            assistant_text="Okay",
            source_ref="conversation:w03-empty",
        )
    )
)
check(
    commit_calls == 0
    and empty.schema == TURN_WRITE_RECEIPT_SCHEMA
    and empty.candidate_count == 0
    and empty.considered_count == 0
    and empty.created_ids == ()
    and empty.sent_to_store is False,
    "W03 empty extraction is a deterministic no-store result",
)

# Legacy: raw extractor JSON must pass W01 before W03 can reach W02.
legacy_path = Path(tempfile.mkdtemp(prefix="memory4-w03-legacy-")) / "memory.db"
legacy_store = MemoryStore(str(legacy_path))
user_text = "Jeg foretrækker sort kaffe uden sukker"
turn = CompletedMemoryTurn(
    user_text=user_text,
    assistant_text="Det husker jeg.",
    source_ref="conversation:w03-legacy",
)
legacy_service = MemoryCompletedTurnWriteService(
    extract=extractor_for(
        extractor_json(
            subject="anders",
            predicate="coffee_preference",
            value="sort kaffe",
            kind="preference",
            sensitivity="public",
            source_type="user_explicit",
            confidence=0.73,
            evidence=user_text,
        )
    ),
    commit=lambda candidates: commit_legacy_candidates(legacy_store, candidates),
)
created = asyncio.run(legacy_service.commit_completed_turn(turn))
legacy_id = created.created_ids[0]
record = legacy_store.get(legacy_id)
check(
    created.created_count == 1
    and record.subject == "user"
    and record.predicate == "verbatim_user_statement"
    and record.value == user_text
    and record.kind == "note"
    and record.sensitivity == "private"
    and record.review_status == "confirmed",
    "W03 preserves W01 server-owned confirmed verbatim authority",
)
repeat = asyncio.run(legacy_service.commit_completed_turn(turn))
check(
    repeat.created_count == 0
    and repeat.deduped_ids == (legacy_id,)
    and repeat.replayed is False,
    "W03 replans current state so repeated turns become exact dedupe",
)

# Partial evidence cannot promote model-authored structured semantics.
pending_turn = CompletedMemoryTurn(
    user_text="Min kaffe er sort",
    assistant_text="Noteret",
    source_ref="conversation:w03-pending",
)
pending_service = MemoryCompletedTurnWriteService(
    extract=extractor_for(
        extractor_json(
            subject="anders",
            predicate="favorite_coffee",
            value="sort",
            kind="preference",
            sensitivity="private",
            source_type="user_explicit",
            confidence=0.91,
            evidence="kaffe er sort",
        )
    ),
    commit=lambda candidates: commit_legacy_candidates(legacy_store, candidates),
)
pending = asyncio.run(pending_service.commit_completed_turn(pending_turn))
pending_record = legacy_store.get(pending.created_ids[0])
check(
    pending_record.subject == "anders"
    and pending_record.predicate == "favorite_coffee"
    and pending_record.review_status == "pending"
    and pending_record.id not in {row.id for row in legacy_store.context_records()},
    "W03 leaves partial structured model semantics pending",
)

# Credential-shaped/secret candidates remain pending at W01 and are skipped by W02.
secret_text = "Min API secret er sk-w03secret123456789"
secret_turn = CompletedMemoryTurn(
    user_text=secret_text,
    assistant_text="Jeg gemmer ikke hemmeligheder automatisk.",
    source_ref="conversation:w03-secret",
)
secret_service = MemoryCompletedTurnWriteService(
    extract=extractor_for(
        extractor_json(
            subject="user",
            predicate="api_secret",
            value="sk-w03secret123456789",
            kind="note",
            sensitivity="secret",
            source_type="user_explicit",
            confidence=1.0,
            evidence=secret_text,
        )
    ),
    commit=lambda candidates: commit_legacy_candidates(legacy_store, candidates),
)
before_secret = row_count(legacy_path)
secret = asyncio.run(secret_service.commit_completed_turn(secret_turn))
check(
    secret.skipped_count == 1
    and secret.created_count == 0
    and row_count(legacy_path) == before_secret,
    "W03 inherits W02 secret no-auto-persist behavior",
)

# Extraction and contract failures cannot invoke the committer.
async def extraction_failure(_turn: CompletedMemoryTurn) -> tuple[MemoryCandidate, ...]:
    raise MemoryExtractionError("injected extraction failure")


failure_service = MemoryCompletedTurnWriteService(
    extract=extraction_failure,
    commit=forbidden_commit,
)
expect_write_error(
    "W03 extraction failure fails closed before storage",
    lambda: failure_service.commit_completed_turn(turn),
    "extraction",
)


async def malformed_extract(_turn: CompletedMemoryTurn):
    return [confirmed("invalid container", "conversation:w03-invalid")]


malformed_service = MemoryCompletedTurnWriteService(
    extract=malformed_extract,
    commit=forbidden_commit,
)
expect_write_error(
    "W03 rejects non-tuple candidate batches before storage",
    lambda: malformed_service.commit_completed_turn(turn),
    "tuple",
)
check(commit_calls == 0, "W03 failed extraction paths make no commit call")

receipt_candidate = confirmed(
    "W03 receipt candidate",
    "conversation:w03-receipt",
)


async def receipt_extract(_turn: CompletedMemoryTurn) -> tuple[MemoryCandidate, ...]:
    return (receipt_candidate,)


def bad_receipt(_candidates: tuple[MemoryCandidate, ...]) -> DurableCandidateWrite:
    return DurableCandidateWrite(
        considered_count=2,
        created_ids=("fake-id",),
        superseded_ids=(),
        superseding_ids=(),
        deduped_ids=(),
        skipped_count=0,
        replayed=False,
        sent_to_store=True,
    )


mismatch_service = MemoryCompletedTurnWriteService(
    extract=receipt_extract,
    commit=bad_receipt,
)
expect_write_error(
    "W03 rejects durable receipts that do not cover the candidate batch",
    lambda: mismatch_service.commit_completed_turn(turn),
    "does not cover",
)


def write_failure(_candidates: tuple[MemoryCandidate, ...]) -> DurableCandidateWrite:
    raise RuntimeError("injected write failure")


write_failure_service = MemoryCompletedTurnWriteService(
    extract=receipt_extract,
    commit=write_failure,
)
expect_write_error(
    "W03 surfaces storage failure as a fail-closed orchestration error",
    lambda: write_failure_service.commit_completed_turn(turn),
    "write failed",
)

receipt_json = json.dumps(created.to_dict(), ensure_ascii=False)
check(
    user_text not in receipt_json
    and turn.source_ref not in receipt_json
    and "sort kaffe" not in receipt_json,
    "W03 public receipt omits value evidence and source_ref",
)
legacy_store.close()

# Protected storage reuses the landed encryption/migration boundary.
protected_path = Path(tempfile.mkdtemp(prefix="memory4-w03-protected-")) / "memory.db"
bootstrap = MemoryStore(str(protected_path))
bootstrap.close()
provider = TestAeadProvider()
codec = MemoryProtectionCodec(provider)
check(
    MemoryProtectionMigrator(protected_path, codec).migrate().complete,
    "W03 protected fixture migration completes",
)
protected_value = "W03 protected canonical statement 51d4"
protected_candidate = confirmed(
    protected_value,
    "conversation:w03-protected",
)


async def protected_extract(_turn: CompletedMemoryTurn) -> tuple[MemoryCandidate, ...]:
    return (protected_candidate,)


with ProtectedMemoryWriter(protected_path, codec) as writer:
    protected_service = MemoryCompletedTurnWriteService(
        extract=protected_extract,
        commit=lambda candidates: commit_protected_candidates(
            writer,
            candidates,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
    )
    protected = asyncio.run(
        protected_service.commit_completed_turn(
            CompletedMemoryTurn(
                user_text=protected_value,
                assistant_text="Okay",
                source_ref=protected_candidate.source_ref,
            )
        )
    )
protected_id = protected.created_ids[0]
with ProtectedMemoryReader(protected_path, codec) as reader:
    opened = reader.get(protected_id, access=MemoryReadAccess.LOCAL_MANAGEMENT)
check(
    protected.created_count == 1
    and opened.value == protected_value
    and opened.source_ref == protected_candidate.source_ref,
    "W03 protected adapter round-trips through local-management authority",
)
conn = sqlite3.connect(protected_path)
try:
    raw_row = conn.execute(
        "SELECT value,source_ref,protection_state FROM agent_memories WHERE id=?",
        (protected_id,),
    ).fetchone()
finally:
    conn.close()
check(
    raw_row is not None
    and raw_row[0] == ""
    and raw_row[1] is None
    and raw_row[2] == "protected",
    "W03 protected write keeps plaintext out of base SQLite columns",
)

# Indexed protected storage requires the explicit #1218 migration and maintains it.
check(
    ProtectedMemoryVerbatimLookupMigrator(protected_path, codec).migrate().complete,
    "W03 indexed fixture sidecar migration completes",
)
indexed_value = "W03 indexed protected statement 82ce"
indexed_candidate = confirmed(
    indexed_value,
    "conversation:w03-indexed",
)


async def indexed_extract(_turn: CompletedMemoryTurn) -> tuple[MemoryCandidate, ...]:
    return (indexed_candidate,)


with ProtectedMemoryWriter(protected_path, codec) as writer:
    indexed_service = MemoryCompletedTurnWriteService(
        extract=indexed_extract,
        commit=lambda candidates: commit_indexed_protected_candidates(
            writer,
            candidates,
            access=MemoryWriteAccess.LOCAL_MANAGEMENT,
        ),
    )
    indexed_created = asyncio.run(
        indexed_service.commit_completed_turn(
            CompletedMemoryTurn(
                user_text=indexed_value,
                assistant_text="Okay",
                source_ref=indexed_candidate.source_ref,
            )
        )
    )
    indexed_repeat = asyncio.run(
        indexed_service.commit_completed_turn(
            CompletedMemoryTurn(
                user_text=indexed_value,
                assistant_text="Okay igen",
                source_ref=indexed_candidate.source_ref,
            )
        )
    )
check(
    indexed_created.created_count == 1
    and indexed_repeat.created_count == 0
    and indexed_repeat.deduped_ids == indexed_created.created_ids,
    "W03 indexed protected path creates then exact-dedupes via blind lookup",
)
conn = sqlite3.connect(protected_path)
try:
    sidecar = conn.execute(
        "SELECT value_hmac FROM agent_memory_protected_verbatim_lookup "
        "WHERE memory_id=?",
        (indexed_created.created_ids[0],),
    ).fetchone()
finally:
    conn.close()
check(
    sidecar is not None
    and len(str(sidecar[0])) == 64
    and str(sidecar[0]) != hashlib.sha256(indexed_value.encode()).hexdigest(),
    "W03 indexed path maintains an opaque keyed selector",
)

print(f"\n===== MEMORY 4 W03 WRITE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
