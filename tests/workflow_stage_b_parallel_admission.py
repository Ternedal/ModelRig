"""Offline, fail-closed regression for optional parallel Stage-B admission phases.

No evidence, signature or nonce-replay validation is mocked in production:
these patches only assert routing without running slow physical contracts.
The exact-head workflow must still execute both REAL admission branches.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

SUPPORT = Path(__file__).resolve().parent / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
import rsi_pilot_exact_task_execution_admission_stage_b_driver as driver  # noqa: E402

expected = {
    "all": ["prefix", "cache:all"],
    "admission": ["prefix", "cache:admission"],
    "admission-prefix": ["prefix"],
    "admission-nonce": ["cache:admission"],
    "midchain": ["cache:midchain"],
    "downstream": ["cache:downstream"],
}
assert driver._SUPPORTED_STAGE_B_SLICES == tuple(expected)

for mode, called_expected in expected.items():
    calls = []
    with patch.dict(os.environ, {
        driver._STAGE_B_SLICE_ENV: mode,
        driver._CONTRACT_SHARD_ENV: "",
    }):
        with patch.object(driver, "_run_admission_prefix",
                          side_effect=lambda: calls.append("prefix")):
            with patch.object(driver, "_run_cached_slice",
                              side_effect=lambda phase: calls.append("cache:" + phase)):
                driver.run_contract()
    assert calls == called_expected, (mode, calls, called_expected)

# Even in a split workflow, shard labels must never be accepted for an
# admission-prefix or nonce job: this prevents silently omitting proofs.
for mode in ("all", "admission", "admission-prefix", "admission-nonce"):
    with patch.dict(os.environ, {
        driver._STAGE_B_SLICE_ENV: mode,
        driver._CONTRACT_SHARD_ENV: "1/3",
    }):
        with patch.object(driver, "_run_admission_prefix",
                          side_effect=AssertionError("must not enter prefix")):
            with patch.object(driver, "_run_cached_slice",
                              side_effect=AssertionError("must not enter nonce")):
                try:
                    driver.run_contract()
                except AssertionError as exc:
                    assert "cannot be combined" in str(exc)
                else:
                    raise AssertionError(f"{mode}: admission accepted shard input")

for invalid in ("admission-pre", "admission_none", "skip", "none"):
    with patch.dict(os.environ, {
        driver._STAGE_B_SLICE_ENV: invalid,
        driver._CONTRACT_SHARD_ENV: "",
    }):
        try:
            driver.run_contract()
        except AssertionError as exc:
            assert "unsupported Stage-B slice" in str(exc)
        else:
            raise AssertionError(f"unknown Stage-B slice accepted: {invalid}")

# Cache-root safety and exact-head manifest are NOT patched or relaxed by
# this test. The real GH Actions workflow remains the evidence authority.
print("Stage-B parallel admission offline routing and fail-closed guards PASS")
