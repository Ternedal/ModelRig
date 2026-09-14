from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from kaliv_dev_control import catalog
import kaliv_dev_control
import kaliv_dev_control.improvement_pilot_start_authorization as start_auth
import kaliv_dev_control.improvement_pilot_start_consumption as consumption
from rsi_pilot_start_authorization_contract import _authority, _preflight_proof

RECEIPT_SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-start-consumption-receipt-v1.schema.json"
)


class PilotStartConsumptionTests(unittest.TestCase):
    def _proof(self):
        preflight = _preflight_proof()
        authorization = start_auth.build_pilot_start_authorization(
            preflight_proof=preflight,
            authorization_id="pilot-start-025",
            start_authorizer_actor_id="anders",
            authorized_at_utc="2026-09-14T08:25:00Z",
            expires_at_utc="2026-09-14T08:35:00Z",
            start_nonce_sha256="d" * 64,
            notes=("Consume one local pilot start exactly once.",),
        )
        verifier, signature = _authority(authorization)
        proof = start_auth._verify_pilot_start_authorization(
            preflight_proof=preflight,
            authorization=authorization,
            signature=signature,
            verifier=verifier,
            now_provider=lambda: "2026-09-14T08:26:00Z",
        )
        return preflight, authorization, signature, proof

    def test_consumes_once_without_starting_product(self):
        _, authorization, _, proof = self._proof()
        with tempfile.TemporaryDirectory(
            prefix="modelrig-pilot-start-consume-"
        ) as raw:
            root = Path(raw).resolve()
            receipt = consumption._consume_verified_pilot_start_authorization_once(
                proof=proof,
                ledger_root=root,
                now_provider=lambda: "2026-09-14T08:27:00Z",
            )
            self.assertEqual(
                receipt.schema,
                consumption.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA,
            )
            self.assertEqual(
                receipt.authority,
                consumption.PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY,
            )
            self.assertEqual(
                receipt.ledger_scope,
                consumption.PILOT_START_CONSUMPTION_LEDGER_SCOPE,
            )
            self.assertEqual(receipt.authorization_proof_sha256, proof.sha256)
            self.assertEqual(
                receipt.authorization_sha256,
                proof.authorization_sha256,
            )
            self.assertEqual(
                receipt.preflight_proof_sha256,
                proof.preflight_proof_sha256,
            )
            self.assertEqual(receipt.start_nonce_sha256, proof.start_nonce_sha256)
            self.assertEqual(receipt.repository, authorization.repository)
            self.assertEqual(receipt.base_sha, authorization.base_sha)
            self.assertEqual(
                receipt.requested_main_sha,
                authorization.requested_main_sha,
            )
            self.assertEqual(receipt.trial_id, authorization.trial_id)
            self.assertEqual(
                receipt.operator_surface,
                authorization.operator_surface,
            )
            self.assertEqual(
                receipt.selected_pilot_task_id,
                authorization.selected_pilot_task_id,
            )
            self.assertEqual(
                receipt.workspace_root_path_sha256,
                authorization.workspace_root_path_sha256,
            )
            self.assertEqual(
                receipt.local_commits_allowed,
                authorization.local_commits_allowed,
            )
            self.assertTrue(receipt.host_replay_guard_committed)
            self.assertFalse(receipt.global_replay_safe)
            self.assertTrue(receipt.one_shot_start_required)
            self.assertTrue(receipt.start_consumed)
            self.assertFalse(receipt.pilot_start_authorized)
            self.assertFalse(receipt.integration_ready)
            self.assertFalse(receipt.product_pilot_started)
            self.assertFalse(receipt.local_commit_authorized)
            self.assertFalse(receipt.remote_write_authorized)
            self.assertFalse(receipt.push_authorized)
            self.assertFalse(receipt.pr_mutation_authorized)
            self.assertFalse(receipt.merge_authorized)
            self.assertFalse(receipt.release_authorized)
            self.assertFalse(receipt.deploy_authorized)
            self.assertFalse(receipt.production_activation_authorized)
            self.assertEqual(
                consumption.PilotStartConsumptionReceipt.from_mapping(
                    receipt.to_dict()
                ),
                receipt,
            )

            marker = consumption._marker_path(root, proof)
            self.assertTrue(marker.is_file())
            self.assertEqual(
                marker.read_bytes(),
                receipt.canonical_json().encode("utf-8"),
            )
            original = marker.read_bytes()
            with self.assertRaises(consumption.PilotStartConsumptionError):
                consumption._consume_verified_pilot_start_authorization_once(
                    proof=proof,
                    ledger_root=root,
                    now_provider=lambda: "2026-09-14T08:28:00Z",
                )
            self.assertEqual(marker.read_bytes(), original)

    def test_expired_authorization_is_not_consumed(self):
        _, _, _, proof = self._proof()
        with tempfile.TemporaryDirectory(
            prefix="modelrig-pilot-start-stale-"
        ) as raw:
            root = Path(raw).resolve()
            with self.assertRaises(consumption.PilotStartConsumptionError):
                consumption._consume_verified_pilot_start_authorization_once(
                    proof=proof,
                    ledger_root=root,
                    now_provider=lambda: "2026-09-14T08:36:00Z",
                )
            self.assertEqual(list(root.iterdir()), [])

    def test_existing_marker_is_never_overwritten(self):
        _, _, _, proof = self._proof()
        with tempfile.TemporaryDirectory(
            prefix="modelrig-pilot-start-replay-"
        ) as raw:
            root = Path(raw).resolve()
            marker = consumption._marker_path(root, proof)
            marker.write_bytes(b"pre-existing-replay-marker")
            with self.assertRaises(consumption.PilotStartConsumptionError):
                consumption._consume_verified_pilot_start_authorization_once(
                    proof=proof,
                    ledger_root=root,
                    now_provider=lambda: "2026-09-14T08:27:00Z",
                )
            self.assertEqual(
                marker.read_bytes(),
                b"pre-existing-replay-marker",
            )

    def test_malformed_or_broadened_proof_cannot_reach_consumption(self):
        _, _, _, proof = self._proof()
        for field in (
            "start_consumed",
            "product_pilot_started",
            "local_commit_authorized",
            "production_activation_authorized",
        ):
            with self.assertRaises(ValueError):
                start_auth.PilotStartAuthorizationProof.from_mapping(
                    {**proof.to_dict(), field: True}
                )

        with tempfile.TemporaryDirectory(
            prefix="modelrig-pilot-start-invalid-"
        ) as raw:
            with self.assertRaises(consumption.PilotStartConsumptionError):
                consumption._consume_verified_pilot_start_authorization_once(
                    proof=proof.to_dict(),
                    ledger_root=Path(raw).resolve(),
                    now_provider=lambda: "2026-09-14T08:27:00Z",
                )

    def test_schema_is_exact_and_non_authorizing(self):
        schema = json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        _, _, _, proof = self._proof()
        with tempfile.TemporaryDirectory(
            prefix="modelrig-pilot-start-schema-"
        ) as raw:
            receipt = consumption._consume_verified_pilot_start_authorization_once(
                proof=proof,
                ledger_root=Path(raw).resolve(),
                now_provider=lambda: "2026-09-14T08:27:00Z",
            )
        self.assertEqual(set(props), set(receipt.to_dict()))
        self.assertEqual(
            props["schema"]["const"],
            consumption.PILOT_START_CONSUMPTION_RECEIPT_SCHEMA,
        )
        self.assertEqual(
            props["ledger_scope"]["const"],
            consumption.PILOT_START_CONSUMPTION_LEDGER_SCOPE,
        )
        self.assertIs(props["host_replay_guard_committed"]["const"], True)
        self.assertIs(props["global_replay_safe"]["const"], False)
        self.assertIs(props["one_shot_start_required"]["const"], True)
        self.assertIs(props["start_consumed"]["const"], True)
        self.assertIs(props["pilot_start_authorized"]["const"], False)
        self.assertIs(props["product_pilot_started"]["const"], False)
        self.assertIs(props["local_commit_authorized"]["const"], False)
        self.assertIs(
            props["production_activation_authorized"]["const"],
            False,
        )
        self.assertEqual(
            props["authority"]["const"],
            consumption.PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY,
        )

    def test_public_surface_freshly_reverifies_and_uses_canonical_ledger(self):
        self.assertEqual(catalog.modelrig_command_catalog().command_ids, ())
        signature = inspect.signature(
            consumption.consume_pilot_start_authorization_once
        )
        self.assertEqual(
            tuple(signature.parameters),
            (
                "preflight_proof",
                "authorization",
                "signature",
                "preflight_signature",
            ),
        )
        source = inspect.getsource(consumption._implementation)
        self.assertIn("verify_pilot_start_authorization(", source)
        self.assertIn("_canonical_pilot_start_ledger_root()", source)
        self.assertIn("create_once_file(marker, payload)", source)
        lowered = source.lower()
        for forbidden in (
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "git push",
            "merge_pull_request",
            "product_pilot_started=true",
            "production_activation=true",
        ):
            self.assertNotIn(forbidden, lowered)

        root_source = inspect.getsource(kaliv_dev_control)
        self.assertNotIn(
            "improvement_pilot_start_consumption",
            root_source,
        )


if __name__ == "__main__":
    unittest.main()
