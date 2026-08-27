#!/usr/bin/env python3
"""Version-bound loader for the retained Stage B wizard implementation.

The verified 2.0.12 implementation is retained byte-for-byte beside this file.
Only the released source and target version authority is shifted for the current
release era before the retained implementation is executed.
"""
from pathlib import Path as _Path

EXPECTED_SOURCE_VERSION = "2.0.12"
EXPECTED_TARGET_VERSION = "2.0.13"
_RETAINED = _Path(__file__).with_name("stage_b_one_click_v2.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_old_source = 'EXPECTED_SOURCE_VERSION = "2.0.11"'
_old_target = 'EXPECTED_TARGET_VERSION = "2.0.12"'
if _source.count(_old_source) != 1 or _source.count(_old_target) != 1:
    raise RuntimeError("Stage B version authority drifted; refusing ambiguous era replacement")
_source = _source.replace(
    _old_source,
    f'EXPECTED_SOURCE_VERSION = "{EXPECTED_SOURCE_VERSION}"',
)
_source = _source.replace(
    _old_target,
    f'EXPECTED_TARGET_VERSION = "{EXPECTED_TARGET_VERSION}"',
)
_name = __name__
globals()["__name__"] = "_stage_b_one_click_v2_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
EXPECTED_SOURCE_VERSION = "2.0.12"
EXPECTED_TARGET_VERSION = "2.0.13"
SOURCE_REF = f"refs/tags/v{EXPECTED_TARGET_VERSION}"

if _name == "__main__":
    raise SystemExit(main())
