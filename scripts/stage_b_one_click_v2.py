#!/usr/bin/env python3
"""Version-bound loader for the retained Stage B wizard implementation.

The verified 2.0.12 implementation is retained byte-for-byte beside this file.
Only the released source and target version authority is shifted for the current
release era before the retained implementation is executed.
"""
# ruff: noqa: F821 -- main is injected by the retained implementation at runtime.
from pathlib import Path as _Path

EXPECTED_SOURCE_VERSION = "2.0.12"
EXPECTED_TARGET_VERSION = "2.0.21"
_RETAINED = _Path(__file__).with_name("stage_b_one_click_v2.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_old_source = 'EXPECTED_SOURCE_VERSION = "2.0.11"'
_old_target = 'EXPECTED_TARGET_VERSION = "2.0.12"'
_old_state_load = "    state = legacy.load_state()"
_new_state_load = '    state = legacy.load_state(str(candidate.get("git_sha") or "") or None)'
if _source.count(_old_source) != 1 or _source.count(_old_target) != 1:
    raise RuntimeError("Stage B version authority drifted; refusing ambiguous era replacement")
if _source.count(_old_state_load) != 1:
    raise RuntimeError("Stage B candidate-state binding drifted; refusing ambiguous era replacement")
_source = _source.replace(
    _old_source,
    f'EXPECTED_SOURCE_VERSION = "{EXPECTED_SOURCE_VERSION}"',
)
_source = _source.replace(
    _old_target,
    f'EXPECTED_TARGET_VERSION = "{EXPECTED_TARGET_VERSION}"',
)
_source = _source.replace(_old_state_load, _new_state_load)

# Rig night 16/11 on 2.0.20: STRICT 2/2 gave the updater 300 s from launch to
# the first swap, and the download counts against it. The worker exe grew from
# 15 MiB (2.0.12) to 1335 MiB (2.0.20); the first attempt was killed mid-download
# and left updater.lock behind. The window now covers the download, and the
# refusal says what a kill before the journal leaves on the rig.
STRICT_INTERRUPTION_DEADLINE_S = 1800.0
_old_deadline = "deadline = time.monotonic() + 300.0"
_new_deadline = "deadline = time.monotonic() + STRICT_INTERRUPTION_DEADLINE_S"
_old_refusal = (
    '"Updateren nåede ikke en ny journal i "\n'
    '                    "state=swapping med mindst ét registreret swap"'
)
_new_refusal = (
    '"Updateren nåede ikke en ny journal i "\n'
    '                    "state=swapping med mindst ét registreret swap "\n'
    '                    f"inden for {STRICT_INTERRUPTION_DEADLINE_S:.0f} s. Den blev stoppet før swap; "\n'
    '                    "flyt updater.lock i appliance-roden til updater.lock.stale-<tid> "\n'
    '                    "og slet %TEMP%\\\\kaliv-update-* før næste forsøg"'
)
if _source.count(_old_deadline) != 1 or _source.count(_old_refusal) != 1:
    raise RuntimeError("Stage B interruption window drifted; refusing ambiguous era replacement")
_source = _source.replace(_old_deadline, _new_deadline)
_source = _source.replace(_old_refusal, _new_refusal)
_name = __name__
globals()["__name__"] = "_stage_b_one_click_v2_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
EXPECTED_SOURCE_VERSION = "2.0.12"
EXPECTED_TARGET_VERSION = "2.0.21"
SOURCE_REF = f"refs/tags/v{EXPECTED_TARGET_VERSION}"

if _name == "__main__":
    raise SystemExit(main())
