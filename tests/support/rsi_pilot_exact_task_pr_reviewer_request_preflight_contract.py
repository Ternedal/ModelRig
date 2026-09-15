"""Adversarial contract for ADR-DC-073 reviewer-request preflight."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_preflight as preflight  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_requestability_precondition as requestability  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_requestability_precondition_contract import (  # noqa: E402
    _live_capability,
    _observe,
    _runner,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-request-preflight-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        preflight.PilotExactTaskPrReviewerRequestPreflightError,
        requestability.PilotExactTaskPrReviewerRequestabilityPreconditionError,
        ValueError,
        TypeError,
        OSError,
    ):
        return
    raise AssertionError("ADR-DC-073 unexpectedly accepted unsafe reviewer preflight")


def _live_precondition():
    cap, identity_value, _broker_path, _broker_bytes, broker_temp, cleanup = _live_capability()
    value = _observe(
        cap,
        identity_value,
        _runner(cap=cap, identity_value=identity_value),
        times=("2026-09-15T06:25:35Z", "2026-09-15T06:25:36Z"),
    )
    assert value.observation_authenticated is True
    return value, identity_value, broker_temp, cleanup


def _pr_evidence(*, identity_value, precondition_value, author_login=None, author_id=None):
    return {
        "pr_request_url_sha256": hashlib.sha256(
            precondition_value.pull_request_api_url.encode("utf-8")
        ).hexdigest(),
        "pr_response_body_sha256": hashlib.sha256(b"reviewer-preflight-pr-073").hexdigest(),
        "pr_response_etag_sha256": hashlib.sha256(b"reviewer-preflight-etag-073").hexdigest(),
        "pull_request_author_login": (
            identity_value.pull_request_author_login
            if author_login is None
            else author_login
        ),
        "pull_request_author_user_id": (
            identity_value.pull_request_author_user_id
            if author_id is None
            else author_id
        ),
        "observed_updated_at_utc": identity_value.ready_updated_at_utc,
        "requested_reviewer_count": 0,
        "requested_team_count": 0,
    }


def _reader(identity_value, precondition_value, *, overrides=None, calls=None):
    overrides = {} if overrides is None else dict(overrides)

    def read(**kwargs):
        if calls is not None:
            calls.append(dict(kwargs))
        result = _pr_evidence(
            identity_value=identity_value,
            precondition_value=precondition_value,
        )
        result.update(overrides)
        return result

    return read


def _run(precondition_value, reader, *, times=None):
    values = iter(times or ("2026-09-15T06:25:37Z", "2026-09-15T06:25:38Z"))
    return preflight._observe_verified_pilot_exact_task_pr_reviewer_request_preflight(
        reviewer_requestability_precondition=precondition_value,
        pr_reader=reader,
        now_provider=lambda: next(values),
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    value, identity_value, broker_temp, cleanup = _live_precondition()
    try:
        calls = []
        result = _run(
            value,
            _reader(identity_value, value, calls=calls),
        )
        assert result.observation_authenticated is True
        assert result.reviewer_requestability_precondition_sha256 == value.sha256
        assert (
            result.reviewer_request_credential_capability_sha256
            == value.reviewer_request_credential_capability_sha256
        )
        assert result.reviewer_identity_observation_sha256 == identity_value.sha256
        assert result.reviewer_request_reservation_sha256 == value.reviewer_request_reservation_sha256
        assert result.reviewer_target_attestation_sha256 == value.reviewer_target_attestation_sha256
        assert result.reviewer_request_nonce_sha256 == value.reviewer_request_nonce_sha256
        assert result.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == value.pull_request_number
        assert result.predicted_commit_sha == value.predicted_commit_sha
        assert result.reviewer_login == value.reviewer_login
        assert result.reviewer_user_id == value.reviewer_user_id
        assert result.repository_permission == "read"
        assert result.requestability_observed_at_utc == "2026-09-15T06:25:36Z"
        assert result.preflight_started_at_utc == "2026-09-15T06:25:37Z"
        assert result.observed_at_utc == "2026-09-15T06:25:38Z"
        assert result.pull_request_author_login == identity_value.pull_request_author_login
        assert result.pull_request_author_user_id == identity_value.pull_request_author_user_id
        assert len(calls) == 1

        for field in (
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_reserved",
            "reviewer_identity_verified",
            "reviewer_requestability_precondition_verified",
            "fresh_exact_pr_state_revalidated",
            "no_requested_reviewers_verified",
            "reviewer_not_pr_author_verified",
            "credential_free_pr_read",
            "redirects_forbidden",
            "response_bounded",
            "reviewer_write_credential_capability_required",
            "one_shot_reviewer_request_transaction_required",
            "post_request_readback_verification_required",
            "team_reviewers_forbidden",
        ):
            assert getattr(result, field) is True
        for field in (
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = preflight.PilotExactTaskPrReviewerRequestPreflight.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        reloaded_precondition = requestability.PilotExactTaskPrReviewerRequestabilityPrecondition.from_mapping(
            value.to_dict()
        )
        assert reloaded_precondition.observation_authenticated is False
        _reject(lambda: preflight._require_live_precondition(reloaded_precondition))

        stale_calls = []
        _reject(
            lambda: _run(
                value,
                _reader(identity_value, value, calls=stale_calls),
                times=("2026-09-15T06:26:07Z", "2026-09-15T06:26:08Z"),
            )
        )
        assert stale_calls == []

        wrong_url = _pr_evidence(
            identity_value=identity_value,
            precondition_value=value,
        )
        wrong_url["pr_request_url_sha256"] = "1" * 64
        target = type(
            "Target",
            (),
            {"ready_updated_at_utc": identity_value.ready_updated_at_utc},
        )()
        _reject(
            lambda: preflight._validate_pr_evidence(
                wrong_url,
                precondition=value,
                target=target,
            )
        )

        self_review = _pr_evidence(
            identity_value=identity_value,
            precondition_value=value,
            author_login=value.reviewer_login,
            author_id=value.reviewer_user_id,
        )
        _reject(lambda: _run(value, lambda **_: self_review))

        changed_author = _pr_evidence(
            identity_value=identity_value,
            precondition_value=value,
            author_login="another-author",
            author_id=identity_value.pull_request_author_user_id + 1,
        )
        _reject(lambda: _run(value, lambda **_: changed_author))

        requested = _pr_evidence(
            identity_value=identity_value,
            precondition_value=value,
        )
        requested["requested_reviewer_count"] = 1
        _reject(lambda: _run(value, lambda **_: requested))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(
            preflight.PilotExactTaskPrReviewerRequestPreflight.__dataclass_fields__
        )
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["properties"]["fresh_exact_pr_state_revalidated"]["const"] is True
        assert schema["properties"]["reviewer_write_credential_capability_required"]["const"] is True
        assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False
        assert schema["properties"]["reviewer_request_performed"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                preflight.observe_pilot_exact_task_pr_reviewer_request_preflight
            ).parameters
        ) == ("reviewer_requestability_precondition",)
        source = inspect.getsource(preflight)
        assert "identity_boundary._read_exact_ready_pr_state" in source
        for forbidden in (
            "request_pull_request_reviewers(",
            "add_review_to_pr(",
            "merge_pull_request(",
            'method="POST"',
            "subprocess",
        ):
            assert forbidden not in source
        assert "reviewer_mutation_authorized: bool = False" in source
        assert "reviewer_request_performed: bool = False" in source
    finally:
        broker_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
