from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaliv_dev_control.review import (
    IndependentPolicyReviewer,
    ReviewError,
    ReviewRequest,
    ReviewVerdict,
)
from test_campaign_review import command_receipt, patch_receipt, task


class ReviewReloadTests(unittest.TestCase):
    def test_review_request_roundtrip_rejects_task_tampering(self) -> None:
        value = task()
        request = ReviewRequest.from_evidence(
            task=value,
            developer_actor_id="developer-a",
            patch=patch_receipt(value),
            commands=(
                command_receipt(value, "test.unit", passed=True),
                command_receipt(value, "test.contract", passed=True),
            ),
        )
        restored = ReviewRequest.from_mapping(request.to_dict())
        restored.verify_task(value)

        payload = request.to_dict()
        payload["base_sha"] = "b" * 40
        tampered = ReviewRequest.from_mapping(payload)
        with self.assertRaises(ReviewError):
            tampered.verify_task(value)

    def test_verdict_roundtrip_requires_actor_separation(self) -> None:
        value = task()
        request = ReviewRequest.from_evidence(
            task=value,
            developer_actor_id="developer-a",
            patch=patch_receipt(value),
            commands=(
                command_receipt(value, "test.unit", passed=True),
                command_receipt(value, "test.contract", passed=True),
            ),
        )
        verdict = IndependentPolicyReviewer().review(
            request,
            reviewer_actor_id="reviewer-b",
        )
        self.assertEqual(
            ReviewVerdict.from_mapping(verdict.to_dict()).canonical_json(),
            verdict.canonical_json(),
        )

        payload = verdict.to_dict()
        payload["reviewer_actor_id"] = "developer-a"
        with self.assertRaises(ReviewError):
            ReviewVerdict.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
