from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from app.agent3.memory import MemoryStore
from app.agent3.memory_turn_commit import commit_legacy_candidates
from app.memory import (
    MAX_COMPLETED_TURN_CHARS,
    CompletedMemoryTurn,
    DurableCandidateWrite,
    MemoryCandidate,
    MemoryCompletedTurnWriteService,
    MemoryTurnWriteError,
)


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


def canonical(value: str, source_ref: str) -> MemoryCandidate:
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


turn = CompletedMemoryTurn(
    user_text="Jeg bruger RTX 3060 til ModelRig.",
    assistant_text="Noteret.",
    source_ref="conversation:w03-h1",
)
commit_calls = 0


def forbidden_commit(_candidates: tuple[MemoryCandidate, ...]) -> DurableCandidateWrite:
    global commit_calls
    commit_calls += 1
    raise AssertionError("invalid turn-bound candidates must not reach storage")


# Structurally valid candidates cannot replay another turn's provenance.
async def extract_forged_source(_turn: CompletedMemoryTurn):
    return (
        MemoryCandidate(
            subject="modelrig",
            predicate="likely_gpu",
            value="RTX 3060",
            kind="fact",
            sensitivity="private",
            source_type="inferred",
            source_ref="conversation:other-turn",
            confidence=0.8,
            review_status="pending",
            evidence="",
        ),
    )


expect_write_error(
    "W03-H1 rejects candidate source_ref from another completed turn",
    lambda: MemoryCompletedTurnWriteService(
        extract=extract_forged_source,
        commit=forbidden_commit,
    ).commit_completed_turn(turn),
    "source_ref",
)

# A canonical-looking confirmed candidate must describe this exact user turn.
async def extract_wrong_confirmed(_turn: CompletedMemoryTurn):
    return (canonical("Jeg bruger RTX 4090.", turn.source_ref),)


expect_write_error(
    "W03-H1 rejects confirmed verbatim content manufactured for another turn",
    lambda: MemoryCompletedTurnWriteService(
        extract=extract_wrong_confirmed,
        commit=forbidden_commit,
    ).commit_completed_turn(turn),
    "verbatim turn authority",
)

# user_explicit evidence/value authority must remain grounded in the bounded turn.
async def extract_forged_evidence(_turn: CompletedMemoryTurn):
    return (
        MemoryCandidate(
            subject="modelrig",
            predicate="gpu",
            value="RTX 4090",
            kind="fact",
            sensitivity="private",
            source_type="user_explicit",
            source_ref=turn.source_ref,
            confidence=0.8,
            review_status="pending",
            evidence="Jeg bruger RTX 4090.",
        ),
    )


expect_write_error(
    "W03-H1 rejects fabricated user-explicit evidence not present in the turn",
    lambda: MemoryCompletedTurnWriteService(
        extract=extract_forged_evidence,
        commit=forbidden_commit,
    ).commit_completed_turn(turn),
    "evidence",
)

# A custom extractor cannot hide credential-like text inside a canonical private note.
credential_turn = CompletedMemoryTurn(
    user_text="mit password er hunter2-value",
    assistant_text="Okay.",
    source_ref="conversation:w03-h1-credential",
)


async def extract_disguised_credential(_turn: CompletedMemoryTurn):
    return (canonical(credential_turn.user_text, credential_turn.source_ref),)


expect_write_error(
    "W03-H1 denies confirmed authority to credential-like completed turns",
    lambda: MemoryCompletedTurnWriteService(
        extract=extract_disguised_credential,
        commit=forbidden_commit,
    ).commit_completed_turn(credential_turn),
    "credential-like",
)

# The hardening must preserve broader W03 policy: valid pending semantics may
# still reach W02 and remain pending rather than being silently promoted.
pending_path = Path(tempfile.mkdtemp(prefix="memory4-w03-h1-pending-")) / "memory.db"
pending_store = MemoryStore(str(pending_path))
pending_candidate = MemoryCandidate(
    subject="modelrig",
    predicate="gpu",
    value="RTX 3060",
    kind="fact",
    sensitivity="private",
    source_type="user_explicit",
    source_ref=turn.source_ref,
    confidence=0.8,
    review_status="pending",
    evidence=turn.user_text,
)


async def extract_valid_pending(_turn: CompletedMemoryTurn):
    return (pending_candidate,)


pending_service = MemoryCompletedTurnWriteService(
    extract=extract_valid_pending,
    commit=lambda candidates: commit_legacy_candidates(pending_store, candidates),
)
pending_receipt = asyncio.run(pending_service.commit_completed_turn(turn))
pending_record = pending_store.get(pending_receipt.created_ids[0])
check(
    pending_receipt.created_count == 1
    and pending_record.subject == "modelrig"
    and pending_record.predicate == "gpu"
    and pending_record.value == "RTX 3060"
    and pending_record.review_status == "pending",
    "W03-H1 preserves valid pending semantic persistence without authority upgrade",
)
pending_store.close()

# Exact W01 turn bounds must apply before a custom extractor can observe text.
extract_calls = 0


async def counted_extract(_turn: CompletedMemoryTurn):
    global extract_calls
    extract_calls += 1
    return ()


expect_write_error(
    "W03-H1 rejects oversized turns before the injected extractor runs",
    lambda: MemoryCompletedTurnWriteService(
        extract=counted_extract,
        commit=forbidden_commit,
    ).commit_completed_turn(
        CompletedMemoryTurn(
            user_text="x" * (MAX_COMPLETED_TURN_CHARS + 1),
            assistant_text="a",
            source_ref="conversation:w03-h1-oversized",
        )
    ),
    "W01 bounds",
)
check(
    extract_calls == 0,
    "W03-H1 oversized turn cannot leak into the injected extractor",
)
check(
    commit_calls == 0,
    "W03-H1 rejects all forged-authority cases before storage",
)

print(f"\n===== MEMORY 4 W03-H1 AUTHORITY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
