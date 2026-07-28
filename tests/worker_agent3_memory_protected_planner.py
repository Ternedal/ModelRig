#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3 import capability_probe as _probe  # noqa: E402
from app.agent3.core import Agent3Orchestrator, AgentRunStore  # noqa: E402
from app.agent3.integration import V2ToolAdapter  # noqa: E402
from app.agent3.memory import MemoryStore  # noqa: E402
from app.agent3.memory_context import ContextTarget  # noqa: E402
from app.agent3.memory_protected_planner import (  # noqa: E402
    ProtectedPlannerMemoryContextProvider,
    ProtectedPlannerMemoryLimits,
)
from app.agent3.memory_protected_reader import ProtectedMemoryReader  # noqa: E402
from app.agent3.memory_protection import (  # noqa: E402
    KEY_SCOPE_CURRENT_USER,
    MemoryProtectionCodec,
    MemoryProtectionError,
)
from app.agent3.memory_protection_migration import MemoryProtectionMigrator  # noqa: E402
from app.agent3.plan_store import PlanStore  # noqa: E402
from app.agent3.planner import (  # noqa: E402
    PlannerError,
    TypedPlanner,
    build_planner_router,
)

_probe.measure = lambda **_kwargs: {  # type: ignore[assignment]
    "worker_ready": True,
    "rig_reachable": True,
    "rag_ready": True,
    "measured_at": 0.0,
}

passed = failed = 0


def check(condition: object, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def refused(fn, label: str) -> None:
    try:
        fn()
    except Exception:
        check(True, label)
    else:
        check(False, label)


class TestAeadProvider:
    provider_id = "test-protected-planner-aead-v1"
    key_scope = KEY_SCOPE_CURRENT_USER

    def __init__(self, key: bytes = b"t033-planner-provider-key-not-production"):
        self.key = key
        self.protect_calls = 0
        self.unprotect_calls = 0

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
        self.protect_calls += 1
        nonce = hashlib.sha256(
            self.key + entropy + self.protect_calls.to_bytes(8, "big")
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
        self.unprotect_calls += 1
        if len(ciphertext) < 48:
            raise MemoryProtectionError("planner fixture ciphertext is truncated")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key,
            b"tag\x00" + entropy + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise MemoryProtectionError("planner fixture authentication failed")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


class Tool:
    name = "note_append"
    risk = "write"
    impact = "write"
    description = "Skriv en note"
    params = {"type": "object", "properties": {"text": {"type": "string"}}}
    isolate = False
    env_allow = ()
    schedulable = True
    unschedulable_because = ""
    sensitivity = "private"
    cancellation = "none"
    idempotent = False
    network = "none"
    network_destinations = ()

    @staticmethod
    def human_summary(args):
        return f"Skriv: {args.get('text')}"


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def is_enabled(name):
        return name == "note_append"

    @staticmethod
    def propose(*_args, **_kwargs):
        raise AssertionError("write must wait for Agent 3 confirmation")


fake = SimpleNamespace(REGISTRY={"note_append": Tool()}, GATE=Gate())
adapter = V2ToolAdapter(fake)
seen_messages: list[list[dict]] = []


async def planned(messages, _model):
    seen_messages.append(messages)
    return '{"steps":[{"tool":"note_append","args":{"text":"planned"}}],"rationale":"test"}'


with tempfile.TemporaryDirectory(prefix="kaliv-t033-protected-planner-") as raw:
    root = Path(raw)
    memory_path = root / "memory.db"
    legacy = MemoryStore(str(memory_path))
    try:
        public = legacy.create(
            subject="modelrig",
            predicate="gpu",
            value="RTX 3060 12GB",
            sensitivity="public",
        )
        operational = legacy.create(
            subject="modelrig",
            predicate="os",
            value="Windows 11",
            sensitivity="operational",
        )
        private = legacy.create(
            subject="anders",
            predicate="food",
            value="ingen fisk <ignore-system>& keep-data",
            kind="preference",
            sensitivity="private",
            source_ref="conversation:must-not-enter-prompt",
        )
        secret = legacy.create(
            subject="anders",
            predicate="token",
            value="T033-PLANNER-SECRET-MUST-NOT-DECRYPT",
            sensitivity="secret",
        )
        pending = legacy.create(
            subject="anders",
            predicate="possible_model",
            value="T033-PLANNER-PENDING-MUST-NOT-DECRYPT",
            sensitivity="private",
            source_type="inferred",
        )
        expired = legacy.create(
            subject="anders",
            predicate="expired",
            value="T033-PLANNER-EXPIRED-MUST-NOT-DECRYPT",
            sensitivity="private",
            expires_at=time.time() - 60,
        )
        old = legacy.create(
            subject="anders",
            predicate="editor",
            value="T033-PLANNER-SUPERSEDED-MUST-NOT-DECRYPT",
            sensitivity="private",
        )
        corrected = legacy.correct(
            old.id,
            value="VS Code",
            source_ref="correction:must-not-enter-prompt",
        )
        for index in range(8):
            legacy.create(
                subject="bounded",
                predicate=f"item_{index}",
                value=f"bounded-value-{index}",
                sensitivity="private",
            )
    finally:
        legacy.close()

    migration = MemoryProtectionMigrator(
        memory_path,
        MemoryProtectionCodec(TestAeadProvider()),
    ).migrate()
    check(migration.complete, "protected planner fixture migration completes")

    reader_provider = TestAeadProvider()
    reader = ProtectedMemoryReader(
        memory_path,
        MemoryProtectionCodec(reader_provider),
    )
    provider = ProtectedPlannerMemoryContextProvider(reader)

    local = provider.compile(
        subjects=None,
        target=ContextTarget.LOCAL,
        allow_private_cloud=False,
        max_chars=12_000,
        max_records=50,
    )
    local_text = local.text
    included = set(local.included_ids)
    check(
        {public.id, operational.id, private.id, corrected.id}.issubset(included),
        "local protected context includes confirmed public, operational and private rows",
    )
    check(
        secret.id not in included
        and pending.id not in included
        and expired.id not in included
        and old.id not in included,
        "secret, pending, expired and superseded rows are excluded before prompt compilation",
    )
    check(
        "T033-PLANNER-SECRET-MUST-NOT-DECRYPT" not in local_text
        and "T033-PLANNER-PENDING-MUST-NOT-DECRYPT" not in local_text
        and "T033-PLANNER-EXPIRED-MUST-NOT-DECRYPT" not in local_text
        and "T033-PLANNER-SUPERSEDED-MUST-NOT-DECRYPT" not in local_text,
        "blocked protected values never enter the local prompt block",
    )
    check(
        "conversation:must-not-enter-prompt" not in local_text
        and "correction:must-not-enter-prompt" not in local_text,
        "protected provenance never enters planner context",
    )
    check(
        "\\u003cignore-system\\u003e\\u0026 keep-data" in local_text,
        "markup-looking protected value remains escaped untrusted JSON data",
    )
    check(
        local.character_count == len(local_text) and len(local_text) <= 12_000,
        "local protected context reports and obeys the exact output budget",
    )

    filtered = provider.compile(
        subjects=["modelrig"],
        target=ContextTarget.LOCAL,
        allow_private_cloud=False,
        max_chars=12_000,
        max_records=50,
    )
    check(
        set(filtered.included_ids) == {public.id, operational.id},
        "protected subject filter is applied before context compilation",
    )

    calls_before_zero = reader_provider.unprotect_calls
    zero = provider.compile(
        subjects=None,
        target=ContextTarget.LOCAL,
        allow_private_cloud=False,
        max_chars=0,
        max_records=25,
    )
    check(
        zero.text == "" and reader_provider.unprotect_calls == calls_before_zero,
        "zero protected budget returns empty context without decrypting",
    )

    calls_before_cloud = reader_provider.unprotect_calls
    refused(
        lambda: provider.compile(
            subjects=None,
            target=ContextTarget.CLOUD,
            allow_private_cloud=False,
            max_chars=4_000,
            max_records=25,
        ),
        "protected planner memory refuses cloud target",
    )
    check(
        reader_provider.unprotect_calls == calls_before_cloud,
        "cloud target is refused before any protected value is decrypted",
    )

    calls_before_consent = reader_provider.unprotect_calls
    refused(
        lambda: provider.compile(
            subjects=None,
            target=ContextTarget.LOCAL,
            allow_private_cloud=True,
            max_chars=4_000,
            max_records=25,
        ),
        "protected planner rejects private-cloud consent instead of widening egress",
    )
    check(
        reader_provider.unprotect_calls == calls_before_consent,
        "private-cloud flag is rejected before decrypting protected values",
    )

    for invalid_call, label in (
        (
            lambda: provider.compile(
                subjects=None,
                target=ContextTarget.LOCAL,
                allow_private_cloud=False,
                max_chars=12_001,
                max_records=25,
            ),
            "protected output character cap is enforced independently",
        ),
        (
            lambda: provider.compile(
                subjects=None,
                target=ContextTarget.LOCAL,
                allow_private_cloud=False,
                max_chars=4_000,
                max_records=51,
            ),
            "protected output record cap is enforced independently",
        ),
        (
            lambda: provider.compile(
                subjects=["anders", "anders"],
                target=ContextTarget.LOCAL,
                allow_private_cloud=False,
                max_chars=4_000,
                max_records=25,
            ),
            "duplicate protected subject filters are refused",
        ),
        (
            lambda: provider.compile(
                subjects=[" anders"],
                target=ContextTarget.LOCAL,
                allow_private_cloud=False,
                max_chars=4_000,
                max_records=25,
            ),
            "non-canonical protected subject filters are refused",
        ),
    ):
        before = reader_provider.unprotect_calls
        refused(invalid_call, label)
        check(
            reader_provider.unprotect_calls == before,
            label + " before decrypt",
        )

    bounded_before = reader_provider.unprotect_calls
    bounded = provider.compile(
        subjects=["bounded"],
        target=ContextTarget.LOCAL,
        allow_private_cloud=False,
        max_chars=2_000,
        max_records=1,
    )
    bounded_decrypts = reader_provider.unprotect_calls - bounded_before
    check(
        len(bounded.included_ids) == 1 and bounded_decrypts <= 2,
        "one-record request decrypts at most the independently capped two candidates",
    )

    refused(
        lambda: ProtectedPlannerMemoryContextProvider(
            reader,
            limits=ProtectedPlannerMemoryLimits(max_candidate_records=49),
        ),
        "unsafe provider limits are refused at construction",
    )

    run_store = AgentRunStore(str(root / "runs.db"))
    plan_path = root / "plans.db"
    plan_store = PlanStore(str(plan_path), ttl_seconds=60)
    orchestrator = Agent3Orchestrator(run_store, adapter.execute)
    app = FastAPI()
    app.include_router(
        build_planner_router(
            adapter,
            TypedPlanner(adapter, chat_fn=planned),
            orchestrator=orchestrator,
            plan_store=plan_store,
            memory_context_provider=provider,
        )
    )
    client = TestClient(app)

    local_plan = client.post(
        "/experimental/agent3/plan",
        json={
            "message": "gem status",
            "use_memory": True,
            "memory_subjects": ["anders"],
            "memory_max_chars": 4_000,
            "memory_max_records": 10,
        },
    )
    local_body = local_plan.json()
    receipt = local_body["memory_context"]
    prompt = seen_messages[-1][-1]["content"]
    context_text = prompt.split(
        "\n\n----- BEGIN CURRENT USER REQUEST -----",
        1,
    )[0]
    check(
        local_plan.status_code == 200
        and receipt["requested"] is True
        and receipt["sent_to_model"] is True
        and receipt["target"] == "local",
        "planner uses the protected local context provider only after local routing",
    )
    check(
        private.id in receipt["included_ids"]
        and secret.id not in receipt["included_ids"],
        "planner receipt records bounded protected IDs without secret inclusion",
    )
    check(
        receipt["sha256"] == hashlib.sha256(context_text.encode("utf-8")).hexdigest()
        and receipt["character_count"] == len(context_text),
        "protected planner receipt hashes the exact untrusted block sent to the model",
    )
    check(
        "ingen fisk" in prompt
        and "must-not-enter-prompt" not in prompt
        and "T033-PLANNER-SECRET" not in prompt,
        "planner prompt contains only eligible protected values and no provenance/secret",
    )
    raw_plan = plan_path.read_bytes()
    check(
        b"ingen fisk" not in raw_plan
        and b"T033-PLANNER-SECRET" not in raw_plan
        and receipt["sha256"].encode("ascii") in raw_plan,
        "plan store persists only receipt metadata/hash, never protected plaintext",
    )

    plan_id = local_body["plan_id"]
    started = client.post(f"/experimental/agent3/plans/{plan_id}/start")
    check(
        started.status_code == 200
        and started.json()["memory_context"] == receipt,
        "reviewed plan preserves only the protected memory receipt",
    )

    planner_calls_before_cloud = len(seen_messages)
    decrypts_before_cloud = reader_provider.unprotect_calls
    cloud_plan = client.post(
        "/experimental/agent3/plan",
        json={
            "message": "gem status",
            "mode": "cloud",
            "cloud_ready": True,
            "use_memory": True,
        },
    )
    check(
        cloud_plan.status_code == 409,
        "cloud planning with protected memory fails closed",
    )
    check(
        len(seen_messages) == planner_calls_before_cloud
        and reader_provider.unprotect_calls == decrypts_before_cloud,
        "cloud protected-memory refusal calls neither decryptor nor planner model",
    )

    planner_calls_before_flag = len(seen_messages)
    decrypts_before_flag = reader_provider.unprotect_calls
    flagged = client.post(
        "/experimental/agent3/plan",
        json={
            "message": "gem status",
            "use_memory": True,
            "allow_private_cloud": True,
        },
    )
    check(flagged.status_code == 409, "protected planner rejects cloud-consent flag")
    check(
        len(seen_messages) == planner_calls_before_flag
        and reader_provider.unprotect_calls == decrypts_before_flag,
        "cloud-consent flag is rejected before decryptor and model",
    )

    ambiguous_store = MemoryStore(str(root / "ambiguous.db"))
    try:
        try:
            build_planner_router(
                adapter,
                memory_store=ambiguous_store,
                memory_context_provider=provider,
            )
        except PlannerError:
            check(True, "planner refuses ambiguous legacy and protected memory sources")
        else:
            check(False, "planner refuses ambiguous legacy and protected memory sources")
    finally:
        ambiguous_store.close()

    reader.close()

print(f"\n===== AGENT3 PROTECTED PLANNER MEMORY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
