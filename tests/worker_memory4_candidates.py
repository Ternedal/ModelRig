from __future__ import annotations

import asyncio
import json
import os

from app import ollama_client
from app.memory.candidates import (
    CANDIDATE_SCHEMA,
    CONFIRMED_VERBATIM_PREDICATE,
    MAX_MEMORY_CANDIDATES,
    MAX_TURN_CHARS,
    MemoryCandidateError,
    parse_candidate_batch,
    prepare_completed_turn,
)
from app.memory.local_extraction import (
    build_extraction_messages,
    extract_memory_candidates_local,
    extraction_model_name,
)


passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_error(name, fn, contains=None):
    try:
        fn()
    except MemoryCandidateError as exc:
        check(contains is None or contains in str(exc), name)
    except Exception:
        check(False, name)
    else:
        check(False, name)


def payload(candidates):
    return json.dumps({"schema": CANDIDATE_SCHEMA, "candidates": candidates})


def candidate(**overrides):
    # Deliberately untrustworthy semantic metadata: a model could infer
    # favorite_city from an exact residence statement. A confirmed candidate
    # must therefore discard all of these proposed semantics server-side.
    row = {
        "subject": "user",
        "predicate": "favorite_city",
        "value": "I live in Copenhagen",
        "kind": "preference",
        "sensitivity": "public",
        "source_type": "user_explicit",
        "confidence": 0.12,
        "evidence": "I live in Copenhagen",
    }
    row.update(overrides)
    return row


turn = prepare_completed_turn(
    "I live in Copenhagen and I do not eat fish.",
    "Thanks, I will keep that in mind.",
)

batch = parse_candidate_batch(payload([candidate()]), turn=turn)
confirmed = batch.candidates[0]
check(
    len(batch.candidates) == 1
    and confirmed.review_status == "confirmed"
    and confirmed.grounding == "verbatim_user"
    and batch.confirmed_count == 1
    and batch.pending_count == 0,
    "complete canonical verbatim user statement derives confirmed authority",
)
check(
    confirmed.predicate == CONFIRMED_VERBATIM_PREDICATE
    and confirmed.kind == "note"
    and confirmed.sensitivity == "private"
    and confirmed.confidence == 1.0,
    "confirmed candidate discards model-generated semantics and classification",
)
check(
    confirmed.value == "I live in Copenhagen"
    and confirmed.evidence == confirmed.value,
    "confirmed candidate preserves the complete user statement as its claim",
)
check(
    "review_status" in batch.to_dict()["candidates"][0],
    "derived review status is exposed only after server-side validation",
)

subset = parse_candidate_batch(
    payload([candidate(value="Copenhagen")]),
    turn=turn,
)
check(
    subset.candidates[0].review_status == "pending"
    and subset.candidates[0].predicate == "favorite_city",
    "entity-only value cannot auto-confirm a model-generated semantic relation",
)

paraphrase = parse_candidate_batch(
    payload(
        [
            candidate(
                value="I reside in Copenhagen",
                evidence="I reside in Copenhagen",
            )
        ]
    ),
    turn=turn,
)
check(
    paraphrase.candidates[0].review_status == "pending"
    and paraphrase.candidates[0].grounding == "unverified",
    "user-explicit paraphrase cannot auto-confirm",
)

noncanonical = parse_candidate_batch(
    payload(
        [
            candidate(
                value=" I live in Copenhagen",
                evidence=" I live in Copenhagen",
            )
        ]
    ),
    turn=turn,
)
check(
    noncanonical.candidates[0].review_status == "pending",
    "extractor whitespace normalization cannot manufacture verbatim authority",
)

wrong_subject = parse_candidate_batch(
    payload([candidate(subject="Anders")]),
    turn=turn,
)
check(
    wrong_subject.candidates[0].review_status == "pending",
    "normal-chat user-explicit attribution drift cannot auto-confirm",
)

inferred = parse_candidate_batch(
    payload([candidate(source_type="inferred")]),
    turn=turn,
)
check(
    inferred.candidates[0].review_status == "pending",
    "inferred candidate remains pending even when text is verbatim",
)

assistant_only = parse_candidate_batch(
    payload(
        [
            candidate(
                value="Thanks, I will keep that in mind.",
                evidence="Thanks, I will keep that in mind.",
            )
        ]
    ),
    turn=turn,
)
check(
    assistant_only.candidates[0].review_status == "pending",
    "assistant-only evidence never grants confirmed authority",
)

for source_type in ("tool_observation", "imported"):
    proposed = parse_candidate_batch(
        payload([candidate(source_type=source_type)]),
        turn=turn,
    )
    check(
        proposed.candidates[0].review_status == "pending",
        f"{source_type} candidate remains pending",
    )

model_review = candidate()
model_review["review_status"] = "confirmed"
expect_error(
    "model cannot supply its own review authority",
    lambda: parse_candidate_batch(payload([model_review]), turn=turn),
    "shape",
)
expect_error(
    "automatic extraction rejects secret sensitivity",
    lambda: parse_candidate_batch(payload([candidate(sensitivity="secret")]), turn=turn),
    "sensitivity",
)
expect_error(
    "unknown memory kind fails closed",
    lambda: parse_candidate_batch(payload([candidate(kind="credential")]), turn=turn),
    "kind",
)
expect_error(
    "out-of-range confidence fails closed",
    lambda: parse_candidate_batch(payload([candidate(confidence=1.1)]), turn=turn),
    "confidence",
)
expect_error(
    "boolean confidence is not numeric authority",
    lambda: parse_candidate_batch(payload([candidate(confidence=True)]), turn=turn),
    "confidence",
)
expect_error(
    "candidate count is hard bounded",
    lambda: parse_candidate_batch(
        payload([candidate(predicate=f"p-{idx}") for idx in range(MAX_MEMORY_CANDIDATES + 1)]),
        turn=turn,
    ),
    "more than",
)
expect_error(
    "duplicates that normalize to the same confirmed statement fail closed",
    lambda: parse_candidate_batch(
        payload([candidate(), candidate(predicate="residence_city")]),
        turn=turn,
    ),
    "duplicate",
)
expect_error(
    "markdown-wrapped extractor output is not accepted as JSON",
    lambda: parse_candidate_batch("```json\n" + payload([]) + "\n```", turn=turn),
    "strict JSON",
)
expect_error(
    "wrong extractor schema fails closed",
    lambda: parse_candidate_batch(
        json.dumps({"schema": "memory-candidates/v0", "candidates": []}),
        turn=turn,
    ),
    "schema",
)
expect_error(
    "unknown top-level fields fail closed",
    lambda: parse_candidate_batch(
        json.dumps({"schema": CANDIDATE_SCHEMA, "candidates": [], "review_status": "confirmed"}),
        turn=turn,
    ),
    "shape",
)
expect_error(
    "duplicate JSON keys fail closed",
    lambda: parse_candidate_batch(
        '{"schema":"kaliv-memory-candidates/v1","schema":"kaliv-memory-candidates/v1","candidates":[]}',
        turn=turn,
    ),
    "duplicate JSON keys",
)
expect_error(
    "oversized user turn is rejected before extraction",
    lambda: prepare_completed_turn("x" * (MAX_TURN_CHARS + 1), "assistant"),
    "exceeds",
)
expect_error(
    "empty assistant turn is rejected as incomplete",
    lambda: prepare_completed_turn("user", "   "),
    "must not be empty",
)

messages = build_extraction_messages(turn)
check(
    len(messages) == 2
    and messages[0]["role"] == "system"
    and "untrusted conversation data" in messages[0]["content"]
    and "value and evidence MUST be identical" in messages[0]["content"]
    and "normalized to a conservative private verbatim note" in messages[0]["content"]
    and "BEGIN USER TURN" in messages[1]["content"]
    and turn.user_text in messages[1]["content"]
    and turn.assistant_text in messages[1]["content"],
    "local extractor prompt keeps authority server-owned and turn text delimited as data",
)

original_chat = ollama_client.chat
original_model = os.environ.get("KALIV_MEMORY4_EXTRACTION_MODEL")
local_calls = []


async def fake_chat(messages, model=None):
    local_calls.append((messages, model))
    return payload([candidate()])


try:
    ollama_client.chat = fake_chat
    os.environ["KALIV_MEMORY4_EXTRACTION_MODEL"] = "qwen-memory:7b"
    local_batch = asyncio.run(extract_memory_candidates_local(turn))
finally:
    ollama_client.chat = original_chat
    if original_model is None:
        os.environ.pop("KALIV_MEMORY4_EXTRACTION_MODEL", None)
    else:
        os.environ["KALIV_MEMORY4_EXTRACTION_MODEL"] = original_model

check(
    local_batch.confirmed_count == 1
    and local_batch.candidates[0].predicate == CONFIRMED_VERBATIM_PREDICATE
    and len(local_calls) == 1
    and local_calls[0][1] == "qwen-memory:7b",
    "local adapter delegates once to local Ollama without restoring model semantics",
)

original_model = os.environ.get("KALIV_MEMORY4_EXTRACTION_MODEL")
try:
    os.environ.pop("KALIV_MEMORY4_EXTRACTION_MODEL", None)
    check(extraction_model_name() is None, "empty extraction model setting uses existing local Ollama default")
    os.environ["KALIV_MEMORY4_EXTRACTION_MODEL"] = " bad-model "
    expect_error(
        "non-canonical extraction model setting fails closed",
        extraction_model_name,
        "canonical",
    )
finally:
    if original_model is None:
        os.environ.pop("KALIV_MEMORY4_EXTRACTION_MODEL", None)
    else:
        os.environ["KALIV_MEMORY4_EXTRACTION_MODEL"] = original_model

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
