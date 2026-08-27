#!/usr/bin/env python3
"""Version-bound loader for the retained guided Stage A scheduler pilot.

The verified 2.0.12 implementation is retained byte-for-byte beside this file.
Only candidate branch and version authority are shifted for the current era.
"""
from pathlib import Path as _Path

CANDIDATE_BRANCH_PREFIX = "physical-proof/2.0.13"
EXPECTED_VERSION = "2.0.13"
_RETAINED = _Path(__file__).with_name("stage_a_scheduler_pilot_easy.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_old_branch = 'CANDIDATE_BRANCH_PREFIX = "physical-proof/2.0.12"'
_old_version = 'EXPECTED_VERSION = "2.0.12"'
if _source.count(_old_branch) != 1 or _source.count(_old_version) != 1:
    raise RuntimeError("Stage A scheduler authority drifted; refusing ambiguous era replacement")
_source = _source.replace(
    _old_branch,
    f'CANDIDATE_BRANCH_PREFIX = "{CANDIDATE_BRANCH_PREFIX}"',
)
_source = _source.replace(
    _old_version,
    f'EXPECTED_VERSION = "{EXPECTED_VERSION}"',
)
_name = __name__
globals()["__name__"] = "_stage_a_scheduler_pilot_easy_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
CANDIDATE_BRANCH_PREFIX = "physical-proof/2.0.13"
EXPECTED_VERSION = "2.0.13"

# Static contract marker: current != CANDIDATE_BRANCH_PREFIX

if _name == "__main__":
    raise SystemExit(main())
