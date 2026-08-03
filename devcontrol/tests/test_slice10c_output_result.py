from __future__ import annotations

import hashlib
import unittest

import kaliv_dev_control._tier_a_execution_core as legacy_core
from kaliv_dev_control.tier_a_execution import (
    PLAN_SCHEMA,
    run_verified_tier_a_command,
)
from kaliv_dev_control.tier_a_result import (
    TierAExecutionResult,
    TierAOutputStream,
    TierAResultError,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def complete_stream(payload: bytes) -> TierAOutputStream:
    return TierAOutputStream(
        captured=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        total_bytes=len(payload),
        truncated=False,
    )


def result_for(
    stdout: TierAOutputStream,
    stderr: TierAOutputStream,
    *,
    max_output_bytes: int = 4096,
    returncode: int = 0,
    timed_out: bool = False,
) -> TierAExecutionResult:
    return TierAExecutionResult.create(
        task_id="A10C_RESULT",
        task_sha256=HASH_A,
        base_sha="1" * 40,
        command_id="modelrig.capture.probe",
        plan_sha256=HASH_B,
        lease_sha256=HASH_C,
        signed_report_sha256=HASH_D,
        returncode=returncode,
        duration_ms=123,
        timed_out=timed_out,
        max_output_bytes=max_output_bytes,
        stdout=stdout,
        stderr=stderr,
    )


class TierAOutputResultTests(unittest.TestCase):
    def test_result_round_trips_exact_binary_prefixes(self):
        result = result_for(
            complete_stream(b"stdout\x00\xff"),
            complete_stream(b"stderr\r\n"),
        )
        reloaded = TierAExecutionResult.from_mapping(result.to_dict())

        self.assertEqual(reloaded.canonical_json(), result.canonical_json())
        self.assertEqual(reloaded.sha256, result.sha256)
        self.assertEqual(reloaded.stdout.captured, b"stdout\x00\xff")
        self.assertEqual(reloaded.stderr.captured, b"stderr\r\n")
        self.assertTrue(reloaded.passed)
        self.assertFalse(reloaded.output_truncated)

    def test_truncated_prefix_retains_full_hash_and_total_count(self):
        full = b"x" * 10_000
        stdout = TierAOutputStream(
            captured=full[:512],
            sha256=hashlib.sha256(full).hexdigest(),
            total_bytes=len(full),
            truncated=True,
        )
        result = result_for(stdout, complete_stream(b""), max_output_bytes=1024)

        self.assertEqual(result.stdout.sha256, hashlib.sha256(full).hexdigest())
        self.assertEqual(result.stdout.total_bytes, 10_000)
        self.assertEqual(result.captured_output_bytes, 512)
        self.assertEqual(result.output_bytes, 10_000)
        self.assertTrue(result.output_truncated)
        self.assertTrue(result.passed)

    def test_untruncated_stream_rejects_a_false_full_hash(self):
        with self.assertRaisesRegex(TierAResultError, "do not match"):
            TierAOutputStream(
                captured=b"real bytes",
                sha256="0" * 64,
                total_bytes=10,
                truncated=False,
            )

    def test_mapping_rejects_tampered_prefix_length(self):
        result = result_for(complete_stream(b"abc"), complete_stream(b"def"))
        payload = result.to_dict()
        payload["stdout"]["captured_bytes"] = 4

        with self.assertRaisesRegex(TierAResultError, "does not match"):
            TierAExecutionResult.from_mapping(payload)

    def test_result_rejects_captured_bytes_above_signed_budget(self):
        with self.assertRaisesRegex(TierAResultError, "exceeded"):
            result_for(
                complete_stream(b"a" * 600),
                complete_stream(b"b" * 600),
                max_output_bytes=1024,
            )

    def test_result_rejects_a_forged_passed_status(self):
        result = result_for(
            complete_stream(b""),
            complete_stream(b"failure"),
            returncode=7,
        )
        payload = result.to_dict()
        payload["passed"] = True

        with self.assertRaisesRegex(TierAResultError, "passed flag"):
            TierAExecutionResult.from_mapping(payload)

    def test_timeout_result_is_never_passing(self):
        result = result_for(
            complete_stream(b"before timeout"),
            complete_stream(b""),
            returncode=1,
            timed_out=True,
        )
        self.assertTrue(result.timed_out)
        self.assertFalse(result.passed)

    def test_only_public_runtime_path_uses_the_v2_plan(self):
        self.assertEqual(PLAN_SCHEMA, "kaliv-development-tier-a-launch-plan/v2")
        self.assertTrue(callable(run_verified_tier_a_command))
        self.assertFalse(hasattr(legacy_core, "run_verified_tier_a_command"))
        self.assertFalse(hasattr(legacy_core, "_run_tier_a_launch_plan"))


if __name__ == "__main__":
    unittest.main()
