"""C13-B production wiring regression tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_c13b_wiring.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.consciousness_core.production_lifecycle import (  # noqa: E402
    TrustedRuntimeClock,
    authoritative_sleep_binding,
    production_sleep_runtime_factory,
)
from app.consciousness_core.self_state import (  # noqa: E402
    SelfAffect,
    SelfBootstrapAuthority,
    SelfStateError,
    SelfStateStore,
    bootstrap_self_state,
)
from app.consciousness_core.sleep_lifecycle import SLEEP_LIFECYCLE_FLAG  # noqa: E402
from app.person_registry import PersonRegistry, REVIEW_CHECKS  # noqa: E402


passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def active_person_fixture(root: Path, *, activate: bool = True):
    person_path = root / "persons.json"
    reg = PersonRegistry(person_path)
    person = reg.create_person("Kaliv")
    body = reg.add_body_revision(person.person_id, "body:test")
    voice = reg.add_voice_revision(person.person_id, "voice:test")
    personality = reg.add_personality_revision(
        person.person_id,
        system_instructions="Be Kaliv.",
        default_language="da",
    )
    revision = reg.propose_person_revision(
        person.person_id,
        body=body.id,
        voice=voice.id,
        personality=personality.id,
        review={key: True for key in REVIEW_CHECKS},
        reviewer="test",
    )
    if activate:
        reg.activate(person.person_id, revision.id)
    reg.select(person.person_id)
    return reg, person, revision, body, voice, personality


def bootstrap_state(root: Path, person_id: str, person_revision: str):
    self_path = root / "self.json"
    os.environ["KALIV_CONSCIOUSNESS_SELF_STATE"] = str(self_path)
    authority = SelfBootstrapAuthority(
        schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
        self_id="self-" + "1" * 32,
        person_id=person_id,
        person_revision=person_revision,
        authority="operator_review",
        authority_ref="test:operator-review",
        source_refs=["test:person-registry"],
        production_activation=False,
    )
    state = bootstrap_self_state(
        authority,
        personality_state_ref="personality-state:test",
        world_state_ref="world-state:test",
        workspace_ref="workspace:test",
        active_goal_refs=["goal:test"],
        active_intention_refs=["intention:test"],
        affect=SelfAffect(
            labels=[],
            valence=0.0,
            arousal=0.0,
            confidence=1.0,
            source_refs=["test:affect"],
        ),
    )
    SelfStateStore().bootstrap(state, authority)
    return state


old_env = {
    key: os.environ.get(key)
    for key in (
        "KALIV_PERSONS_STORE",
        "KALIV_CONSCIOUSNESS_SELF_STATE",
        "KALIV_CONSCIOUSNESS_SLEEP_STATE",
        SLEEP_LIFECYCLE_FLAG,
    )
}

try:
    # --- trusted runtime clock: one process epoch, increasing sequence --------
    wall = iter([1_700_000_000_000_000_000, 1_700_000_001_000_000_000])
    mono = iter([10_000_000_000, 11_000_000_000])
    clock = TrustedRuntimeClock(
        wall_time_ns=lambda: next(wall),
        monotonic_ns=lambda: next(mono),
    )
    first = clock.sample()
    second = clock.sample()
    check(first.runtime_epoch_id == second.runtime_epoch_id == clock.runtime_epoch_id,
          "trusted clock keeps one runtime epoch per worker clock authority")
    check((first.sampled_sequence, second.sampled_sequence) == (1, 2),
          "trusted clock sequence advances monotonically")
    check(second.monotonic_ms > first.monotonic_ms,
          "trusted clock exposes same-epoch monotonic progress")

    # --- flag OFF: even malformed persistence stays untouched -----------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bad_self = root / "self.json"
        bad_self.write_text("{ definitely broken", encoding="utf-8")
        os.environ["KALIV_CONSCIOUSNESS_SELF_STATE"] = str(bad_self)
        os.environ["KALIV_CONSCIOUSNESS_SLEEP_STATE"] = str(root / "sleep.json")
        os.environ.pop(SLEEP_LIFECYCLE_FLAG, None)
        runtime = production_sleep_runtime_factory(object())
        check(not runtime.start(), "C13-B remains disabled by default")
        check(not (root / "sleep.json").exists(),
              "flag OFF opens/creates no Consciousness Core sleep state")

    # --- missing SelfState => no authoritative binding ------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        os.environ["KALIV_PERSONS_STORE"] = str(root / "persons.json")
        os.environ["KALIV_CONSCIOUSNESS_SELF_STATE"] = str(root / "missing-self.json")
        active_person_fixture(root)
        check(authoritative_sleep_binding() is None,
              "missing persistent SelfState yields no SleepBinding")

    # --- selected person without active revision => no binding ----------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        os.environ["KALIV_PERSONS_STORE"] = str(root / "persons.json")
        reg, person, revision, *_ = active_person_fixture(root, activate=False)
        bootstrap_state(root, person.person_id, revision.id)
        check(authoritative_sleep_binding() is None,
              "selected Person without active approved revision yields no SleepBinding")

    # --- exact SelfState + active Person Revision => authoritative binding -----
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        os.environ["KALIV_PERSONS_STORE"] = str(root / "persons.json")
        reg, person, revision, body, voice, personality = active_person_fixture(root)
        state = bootstrap_state(root, person.person_id, revision.id)
        binding = authoritative_sleep_binding()
        check(binding is not None and binding.self_id == state.self_id,
              "exact active Person and persisted SelfState produce SleepBinding")
        check(binding is not None and binding.person_revision == revision.id,
              "SleepBinding keeps the exact approved Person Revision")
        check(binding is not None and binding.open_goal_refs == ["goal:test"],
              "active goals are carried as references only")
        check(binding is not None and binding.open_loop_refs == ["intention:test"],
              "active intentions are carried as open-loop references only")

        # Activating a new Person Revision without explicit C14 rebind must fail.
        revision2 = reg.propose_person_revision(
            person.person_id,
            body=body.id,
            voice=voice.id,
            personality=personality.id,
            review={key: True for key in REVIEW_CHECKS},
            reviewer="test",
        )
        reg.activate(person.person_id, revision2.id)
        try:
            authoritative_sleep_binding()
            mismatch_failed = False
        except SelfStateError:
            mismatch_failed = True
        check(mismatch_failed,
              "active Person Revision mismatch fails closed instead of guessing identity")

    # --- real sleep -> restart -> wake ----------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        os.environ["KALIV_PERSONS_STORE"] = str(root / "persons.json")
        os.environ["KALIV_CONSCIOUSNESS_SLEEP_STATE"] = str(root / "sleep.json")
        os.environ[SLEEP_LIFECYCLE_FLAG] = "1"
        reg, person, revision, *_ = active_person_fixture(root)
        state = bootstrap_state(root, person.person_id, revision.id)

        before = production_sleep_runtime_factory(object())
        check(before.start(), "enabled C13-B starts with an authoritative binding")
        check(before.wake_receipt is None,
              "first boot has no fabricated wake receipt without prior sleep")
        check(before.close(), "clean shutdown persists one sleep boundary")
        check((root / "sleep.json").exists(), "clean shutdown writes the bounded sleep state")

        after = production_sleep_runtime_factory(object())
        check(after.start(), "next worker epoch consumes the prior sleep boundary")
        receipt = after.wake_receipt
        check(receipt is not None and receipt.self_id == state.self_id,
              "wake preserves the same persistent self")
        check(receipt is not None and receipt.person_revision == revision.id,
              "wake preserves the exact Person Revision")
        check(receipt is not None and receipt.cognition_during_gap is False,
              "powered-off gap never claims cognition")
        check(receipt is not None and receipt.execution_authority is False,
              "wake receipt cannot execute resumed goals")
        check(receipt is not None and receipt.resume_goal_refs == ["goal:test"],
              "wake returns goal references without executing them")
        check(receipt is not None and receipt.resume_open_loop_refs == ["intention:test"],
              "wake returns open-loop references without executing them")

    # --- production wrapper keeps the scheduler as authority owner ------------
    os.environ.pop(SLEEP_LIFECYCLE_FLAG, None)
    from app import entrypoint  # noqa: E402
    from app.schedule_runtime import scheduler_lifespan  # noqa: E402

    production_lifespan = entrypoint.fastapi_app.router.lifespan_context
    check(getattr(production_lifespan, "__wrapped__", None) is scheduler_lifespan,
          "C13-B composition preserves scheduler as the production lifespan owner")

finally:
    for key, value in old_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

print(f"\n===== CONSCIOUSNESS C13-B: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
