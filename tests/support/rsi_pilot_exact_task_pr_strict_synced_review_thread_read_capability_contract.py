"""Adversarial contract for ADR-DC-089 strict-synced review-thread read capability."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEV = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEV):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability as capability
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync
from kaliv_dev_control import _improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability_production_boundary as production
import rsi_pilot_exact_task_pr_strict_base_sync_preflight_contract as parent

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-strict-synced-review-thread-read-capability-v1.schema.json"
BROKER_PATH = Path("/opt/modelrig/test/rsi-github-strict-synced-review-thread-read-broker-v1")
BROKER_SHA256 = "1" * 64
POLICY_SHA256 = "2" * 64


def _reject(fn):
    try:
        fn()
    except (
        capability.PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError,
        production.PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError,
        ValueError, TypeError, OSError, AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-089 accepted unsafe capability state")


def _source():
    req, items = parent._live_requirements()
    strict = parent._observe(req, parent._transport(req))
    assert strict.preflight_authenticated is True
    live = sync._get_live_pr_strict_base_sync_preflight_inputs(strict)
    assert live is not None
    return strict, req, live, items


def _descriptor(req, strict):
    return {
        "broker_policy_sha256": POLICY_SHA256,
        "broker_executable_path": os.fspath(BROKER_PATH),
        "broker_executable_path_sha256": hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(BROKER_PATH)))).hexdigest(),
        "broker_executable_sha256": BROKER_SHA256,
        "broker_version": "test-v1",
        "credential_protocol": capability.PROTOCOL,
        "graphql_operation": req.graphql_operation,
        "secret_source": capability.SECRET_SOURCE,
        "secret_transport": capability.SECRET_TRANSPORT,
        "graphql_endpoint": capability.GRAPHQL_ENDPOINT,
        "credential_account": capability.CREDENTIAL_ACCOUNT,
        "graphql_query_sha256": strict.review_thread_graphql_query_sha256,
    }


def _policy(req, strict):
    return {
        "schema": production.POLICY_SCHEMA,
        "provider": "github",
        "graphql_endpoint": capability.GRAPHQL_ENDPOINT,
        "repository": "Ternedal/ModelRig",
        "credential_account": capability.CREDENTIAL_ACCOUNT,
        "credential_protocol": capability.PROTOCOL,
        "operation": req.graphql_operation,
        "broker_version": "test-v1",
        "broker_executable_path": os.fspath(BROKER_PATH),
        "broker_executable_sha256": BROKER_SHA256,
        "secret_source": capability.SECRET_SOURCE,
        "secret_transport": capability.SECRET_TRANSPORT,
        "graphql_query_sha256": strict.review_thread_graphql_query_sha256,
        "strict_synced_preflight_required": True,
        "review_thread_requirements_required": True,
        "required_status_checks_passed_required": True,
        "strict_base_sync_passed_required": True,
        "graphql_query_only": True,
        "graphql_mutation_forbidden": True,
        "graphql_introspection_forbidden": True,
        "other_repository_reads_forbidden": True,
        "review_submission_write_forbidden": True,
        "review_dismissal_write_forbidden": True,
        "review_thread_mutation_forbidden": True,
        "reviewer_request_write_forbidden": True,
        "pull_request_write_forbidden": True,
        "label_write_forbidden": True,
        "merge_write_forbidden": True,
        "repository_contents_write_forbidden": True,
        "administration_write_forbidden": True,
        "release_write_forbidden": True,
        "deployment_write_forbidden": True,
        "redirect_following_forbidden": True,
    }


def _materialize(strict, req, *, at="2026-09-15T19:30:18Z", descriptor=None):
    return capability._materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_read_capability(
        strict_base_sync_preflight=strict,
        broker_descriptor=_descriptor(req, strict) if descriptor is None else descriptor,
        now_provider=lambda: at,
    )


def run_contract():
    if os.name == "nt":
        return
    parent.run_contract()
    strict, req, live, items = _source()
    try:
        evaluated = live["required_status_evaluation"]
        app = live["ruleset_applicability"]
        result = _materialize(strict, req)
        assert result.capability_authenticated is True
        assert result.strict_base_sync_preflight_sha256 == strict.sha256
        assert result.review_thread_read_requirements_sha256 == req.sha256
        assert result.required_status_evaluation_sha256 == evaluated.sha256
        assert result.required_status_policy_sha256 == evaluated.required_status_policy_sha256
        assert result.ruleset_applicability_sha256 == app.sha256
        assert result.ruleset_observation_sha256 == req.ruleset_observation_sha256
        assert result.status_check_observation_sha256 == evaluated.status_check_observation_sha256
        assert result.repository == strict.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == strict.pull_request_number
        assert result.predicted_commit_sha == strict.predicted_commit_sha
        assert result.strict_base_tip_sha == strict.first_base_tip_sha == strict.second_base_tip_sha
        assert result.graphql_operation == req.graphql_operation
        assert result.graphql_query_sha256 == strict.review_thread_graphql_query_sha256
        assert result.credential_account_sha256 == hashlib.sha256(b"Ternedal").hexdigest()
        assert result.materialized_at_utc == "2026-09-15T19:30:18Z"

        for field in (
            "source_strict_sync_verified", "source_review_thread_requirements_verified",
            "source_status_checks_passed", "source_strict_base_sync_passed", "fresh_source_age_verified",
            "review_thread_read_capability_materialized", "read_broker_host_pinned", "read_broker_binary_verified",
            "credential_secret_not_loaded", "credential_broker_owns_https", "graphql_query_only",
            "graphql_mutations_forbidden", "graphql_introspection_forbidden", "other_repository_reads_forbidden",
            "review_thread_state_observation_required", "fresh_required_status_reobservation_before_merge_required",
            "fresh_review_reobservation_required", "fresh_merge_transaction_revalidation_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "branch_policy_fully_evaluated", "credential_material_in_artifact",
            "credential_material_in_process_arguments", "credential_material_in_environment",
            "review_thread_mutation_authorized", "merge_readiness_authorized", "merge_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        live_capability = capability._get_live_pr_strict_synced_review_thread_read_capability_inputs(result)
        assert live_capability is not None
        assert live_capability["strict_base_sync_preflight"] is strict

        replay = capability.PilotExactTaskPrStrictSyncedReviewThreadReadCapability.from_mapping(result.to_dict())
        assert replay == result and replay.capability_authenticated is False
        loose = sync.PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(strict.to_dict())
        assert loose.preflight_authenticated is False
        _reject(lambda: _materialize(loose, req))

        _materialize(strict, req, at="2026-09-15T19:30:18Z")
        _reject(lambda: _materialize(strict, req, at="2026-09-15T19:30:19Z"))
        _reject(lambda: _materialize(strict, req, at="2026-09-15T19:30:02Z"))

        bad = _descriptor(req, strict); bad["graphql_operation"] = "query-other"
        _reject(lambda: _materialize(strict, req, descriptor=bad))
        bad = _descriptor(req, strict); bad["graphql_query_sha256"] = "3" * 64
        _reject(lambda: _materialize(strict, req, descriptor=bad))
        bad = _descriptor(req, strict); bad["credential_protocol"] = "other-v1"
        _reject(lambda: _materialize(strict, req, descriptor=bad))

        policy = _policy(req, strict)
        parsed = production._parse_policy(
            production._canonical_bytes(policy),
            broker_path=BROKER_PATH,
            implementation=capability._implementation,
            expected_operation=req.graphql_operation,
            expected_query_sha256=strict.review_thread_graphql_query_sha256,
        )
        assert parsed["strict_synced_preflight_required"] is True
        assert parsed["review_thread_requirements_required"] is True
        assert parsed["required_status_checks_passed_required"] is True
        assert parsed["strict_base_sync_passed_required"] is True
        for field in (
            "strict_synced_preflight_required", "review_thread_requirements_required",
            "required_status_checks_passed_required", "strict_base_sync_passed_required",
            "graphql_mutation_forbidden", "other_repository_reads_forbidden",
            "review_thread_mutation_forbidden", "merge_write_forbidden",
        ):
            weakened = dict(policy)
            weakened[field] = False
            _reject(lambda weakened=weakened: production._parse_policy(
                production._canonical_bytes(weakened),
                broker_path=BROKER_PATH,
                implementation=capability._implementation,
                expected_operation=req.graphql_operation,
                expected_query_sha256=strict.review_thread_graphql_query_sha256,
            ))

        original = production._canonical_broker_descriptor
        calls = []
        try:
            def forbidden_loader(_implementation, **_kwargs):
                calls.append(True)
                raise AssertionError("host state touched before live ADR-DC-088 gate")
            production._canonical_broker_descriptor = forbidden_loader
            _reject(lambda: capability.materialize_pilot_exact_task_pr_strict_synced_review_thread_read_capability(loose))
            assert calls == []
        finally:
            production._canonical_broker_descriptor = original

        tampered = result.to_dict(); tampered["merge_authorized"] = True
        _reject(lambda: capability.PilotExactTaskPrStrictSyncedReviewThreadReadCapability.from_mapping(tampered))
        tampered = result.to_dict(); tampered["broker_executable_sha256"] = "4" * 64
        inert = capability.PilotExactTaskPrStrictSyncedReviewThreadReadCapability.from_mapping(tampered)
        assert inert.capability_authenticated is False

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(capability.PilotExactTaskPrStrictSyncedReviewThreadReadCapability.__dataclass_fields__)
        assert len(fields) == 51
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["source_status_checks_passed"]["const"] is True
        assert schema["properties"]["source_strict_base_sync_passed"]["const"] is True
        assert schema["properties"]["review_thread_state_observation_required"]["const"] is True
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(capability.materialize_pilot_exact_task_pr_strict_synced_review_thread_read_capability).parameters) == ("strict_base_sync_preflight",)
        implementation_source = inspect.getsource(capability._implementation)
        for forbidden in ("run_bounded_subprocess", "subprocess.run(", "Popen(", "urllib.request", "requests."):
            assert forbidden not in implementation_source
    finally:
        parent._cleanup(items)


if __name__ == "__main__":
    run_contract()
