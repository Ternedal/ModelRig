from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import Agent3Orchestrator, AgentRunStore
from app.agent3.integration import V2ToolAdapter
from app.agent3.memory_context import ContextTarget
from app.agent3.memory_protected import (
    CountingAeadProvider,
    MemoryProtectionCodec,
    MemoryProtectionMigrator,
    ProtectedMemoryReader,
)
from app.agent3.memory_protected_context import ProtectedPlannerMemoryContextProvider
from app.agent3.planner import TypedPlanner
from app.agent3.planner_api import PlanStore, build_planner_router
from app.agent3.memory import MemoryStore

LEAK_MARKERS = {
    "private": "PRIVATE-PLANNER-VALUE",
    "blocked": "SECRET-PLANNER-VALUE",
    "provenance": "PRIVATE-PLANNER-PROVENANCE",
}
checks: list[tuple[str, bool]] = []


def check(label: str, condition: bool) -> None:
    checks.append((label, condition))


def expect_refusal(label: str, fn) -> None:
    try:
        fn()
    except Exception:
        check(label, True)
    else:
        check(label, False)


class Tool:
    risk = "write"
    sensitivity = "operational"
    egress = "local"
    idempotent = False

    @staticmethod
    def validate_args(args):
        return args

    @staticmethod
    def call(_args):
        return {"ok": True}


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
    store = MemoryStore(str(memory_path))
    try:
        private_id = store.create(
            subject="anders",
            predicate="food",
            value=LEAK_MARKERS["private"],
            sensitivity="private",
            source_ref=LEAK_MARKERS["provenance"],
        ).id
        blocked_id = store.create(
            subject="anders",
            predicate="credential",
            value=LEAK_MARKERS["blocked"],
            sensitivity="secret",
        ).id
    finally:
        store.close()

    migration = MemoryProtectionMigrator(
        memory_path,
        MemoryProtectionCodec(CountingAeadProvider()),
    ).migrate()
    check("protected planner fixture migration completes", migration.complete)

    reader_provider = CountingAeadProvider()
    reader = ProtectedMemoryReader(
        memory_path,
        MemoryProtectionCodec(reader_provider),
    )
    provider = ProtectedPlannerMemoryContextProvider(reader)

    local = provider.compile(
        subjects=["anders"],
        target=ContextTarget.LOCAL,
        allow_private_cloud=False,
        max_chars=4_000,
        max_records=10,
    )
    check(
        "provider returns only eligible local protected data",
        private_id in local.included_ids
        and blocked_id not in local.included_ids
        and LEAK_MARKERS["private"] in local.text
        and LEAK_MARKERS["blocked"] not in local.text
        and LEAK_MARKERS["provenance"] not in local.text,
    )

    decrypts_before_cloud = reader_provider.unprotect_calls
    expect_refusal(
        "provider refuses cloud target",
        lambda: provider.compile(
            subjects=["anders"],
            target=ContextTarget.CLOUD,
            allow_private_cloud=False,
            max_chars=4_000,
            max_records=10,
        ),
    )
    check(
        "provider cloud refusal happens before decrypt",
        reader_provider.unprotect_calls == decrypts_before_cloud,
    )

    run_store = AgentRunStore(str(root / "runs.db"))
    plan_store = PlanStore(str(root / "plans.db"), ttl_seconds=60)
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
    try:
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
        body = local_plan.json()
        receipt = body["memory_context"]
        prompt = seen_messages[-1][-1]["content"]
        context_text = prompt.split(
            "\n\n----- BEGIN CURRENT USER REQUEST -----",
            1,
        )[0]
        check(
            "planner injects protected context only after local routing",
            local_plan.status_code == 200
            and receipt["target"] == "local"
            and receipt["sent_to_model"] is True
            and private_id in receipt["included_ids"]
            and blocked_id not in receipt["included_ids"],
        )
        check(
            "planner receipt hashes the exact untrusted block",
            receipt["sha256"]
            == hashlib.sha256(context_text.encode("utf-8")).hexdigest()
            and receipt["character_count"] == len(context_text),
        )
        raw_plan = (root / "plans.db").read_bytes()
        check(
            "plan persistence contains receipt hash but no protected plaintext",
            LEAK_MARKERS["private"].encode("utf-8") not in raw_plan
            and LEAK_MARKERS["blocked"].encode("utf-8") not in raw_plan
            and receipt["sha256"].encode("ascii") in raw_plan,
        )

        model_calls_before_cloud = len(seen_messages)
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
            "cloud planning with protected memory fails closed",
            cloud_plan.status_code == 409,
        )
        check(
            "cloud refusal calls neither decryptor nor planner model",
            len(seen_messages) == model_calls_before_cloud
            and reader_provider.unprotect_calls == decrypts_before_cloud,
        )

        model_calls_before_flag = len(seen_messages)
        decrypts_before_flag = reader_provider.unprotect_calls
        flagged = client.post(
            "/experimental/agent3/plan",
            json={
                "message": "gem status",
                "use_memory": True,
                "allow_private_cloud": True,
            },
        )
        check(
            "private-cloud consent cannot widen protected planner memory",
            flagged.status_code == 409
            and len(seen_messages) == model_calls_before_flag
            and reader_provider.unprotect_calls == decrypts_before_flag,
        )

        ambiguous_store = MemoryStore(str(root / "ambiguous.db"))
        try:
            expect_refusal(
                "planner refuses simultaneous legacy and protected sources",
                lambda: build_planner_router(
                    adapter,
                    memory_store=ambiguous_store,
                    memory_context_provider=provider,
                ),
            )
        finally:
            ambiguous_store.close()
    finally:
        client.close()
        plan_store.close()
        reader.close()
        run_store.close()

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== AGENT3 PROTECTED PLANNER MEMORY: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
