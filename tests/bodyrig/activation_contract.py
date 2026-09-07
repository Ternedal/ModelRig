#!/usr/bin/env python3
"""Dependency-free contract for #704 BodyRig production dormancy.

The dedicated renderer workflow deliberately installs no worker dependencies, so
this gate verifies production wiring from source plus the stdlib-only flag
implementation. Runtime FastAPI/mount/hook behavior is exercised by
``tests/worker_bodyrig_activation.py`` in the dependency-backed full suite.
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from app.bodyrig_activation import BODYRIG_FLAG, bodyrig_enabled  # noqa: E402
from source_code import code_of  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


previous = os.environ.get(BODYRIG_FLAG)
try:
    os.environ.pop(BODYRIG_FLAG, None)
    check(not bodyrig_enabled(), "BodyRig production integration is off when the flag is absent")
    false_values = ("", "0", "true", "TRUE", "yes", "2", " 1x ")
    false_results = []
    for value in false_values:
        os.environ[BODYRIG_FLAG] = value
        false_results.append(not bodyrig_enabled())
    check(all(false_results), "truthy-looking and malformed values do not activate BodyRig")
    os.environ[BODYRIG_FLAG] = " 1 "
    check(bodyrig_enabled(), "only the trimmed exact value 1 opts in")
finally:
    if previous is None:
        os.environ.pop(BODYRIG_FLAG, None)
    else:
        os.environ[BODYRIG_FLAG] = previous

entrypoint = code_of(ROOT / "worker" / "app" / "entrypoint.py")
mount = code_of(ROOT / "worker" / "app" / "bodyrig_mount.py")
session = code_of(ROOT / "worker" / "app" / "body_session.py")
worker_session_test = code_of(ROOT / "tests" / "worker_body_session.py")
worker_activation_test = code_of(ROOT / "tests" / "worker_bodyrig_activation.py")
main_impl = code_of(ROOT / "worker" / "app" / "main_impl.py")
voice_pipeline = code_of(ROOT / "worker" / "app" / "voice_pipeline.py")

check(
    "mount_bodyrig(fastapi_app)" in entrypoint
    and "include_router(build_body_router())" not in entrypoint
    and "include_router(build_body_session_router())" not in entrypoint,
    "production entrypoint delegates BodyRig mounting to one self-guarded mount",
)
check(
    mount.index("if not bodyrig_enabled()") < mount.index("from .body_assets import build_body_router")
    < mount.index("app.include_router(build_body_router())")
    and mount.index("if not bodyrig_enabled()") < mount.index("from .body_session import build_body_session_router")
    < mount.index("app.include_router(build_body_session_router())"),
    "default-off guard runs before BodyRig router imports or route registration",
)
check(
    '_STATE_ATTR = "bodyrig_mounted"' in mount
    and "getattr(app.state, _STATE_ATTR, False)" in mount
    and "setattr(app.state, _STATE_ATTR, True)" in mount,
    "BodyRig production mount is idempotent",
)
state_start = session.index("def note_state")
speech_start = session.index("def note_speech")
check(
    session.index("if not bodyrig_enabled():", state_start)
    < session.index("current_session(create=True)", state_start),
    "chat state hook checks activation before resolving or creating BodyRig runtime",
)
check(
    session.index("if not bodyrig_enabled():", speech_start)
    < session.index("current_session(create=True)", speech_start)
    < session.index("open(wav_path", speech_start),
    "VoiceRig speech hook checks activation before session resolution or WAV access",
)
check(
    "body_session.note_state(" in main_impl and "body_session.note_speech(" in voice_pipeline,
    "production chat and VoiceRig paths still go through the guarded BodyRig hooks",
)
check(
    "BODYRIG_FLAG" in worker_session_test
    and 'os.environ[BODYRIG_FLAG] = "1"' in worker_session_test,
    "existing BodyRig session implementation suite opts in explicitly",
)
check(
    "test_production_mount_is_default_off_and_exact_opt_in" in worker_activation_test
    and "test_disabled_hooks_do_not_touch_runtime_or_wav" in worker_activation_test,
    "dependency-backed full suite owns runtime proof for mount and hook dormancy",
)

print(f"\nBodyRig #704 activation contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
