"""Adversarial contract for ADR-DC-081 exact-head status-check observation."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEVCONTROL_SRC):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_status_check_observation as status_observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_merge_preflight as preflight_boundary  # noqa: E402
from kaliv_dev_control.github_read import HttpResponse  # noqa: E402
import rsi_pilot_exact_task_pr_merge_preflight_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-status-check-observation-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        status_observation.PilotExactTaskPrStatusCheckObservationError,
        preflight_boundary.PilotExactTaskPrMergePreflightError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-081 unexpectedly accepted unsafe status evidence")


def _response(value, *, etag: str) -> HttpResponse:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return HttpResponse(
        status=200,
        headers={
            "content-type": "application/vnd.github+json",
            "etag": etag,
        },
        body=payload,
    )


class _Transport:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError("unexpected extra status-check read")
        return self.responses.pop(0)


def _check(
    preflight,
    *,
    run_id: int,
    name: str,
    status: str = "completed",
    conclusion="success",
    app_id: int = 15368,
    app_slug: str = "github-actions",
    head_sha=None,
):
    if status != "completed" and conclusion == "success":
        conclusion = None
    return {
        "id": run_id,
        "node_id": f"CR_081_{run_id}",
        "name": name,
        "head_sha": preflight.predicted_commit_sha if head_sha is None else head_sha,
        "status": status,
        "conclusion": conclusion,
        "started_at": "2026-09-15T06:25:40Z",
        "completed_at": "2026-09-15T06:25:49Z" if status == "completed" else None,
        "app": {"id": app_id, "slug": app_slug},
    }


def _legacy(
    *,
    status_id: int,
    context: str,
    state: str = "success",
    creator_id: int = 4242,
):
    return {
        "id": status_id,
        "node_id": f"ST_081_{status_id}",
        "state": state,
        "context": context,
        "created_at": "2026-09-15T06:25:40Z",
        "updated_at": "2026-09-15T06:25:49Z",
        "creator": {"id": creator_id},
    }


def _snapshot_responses(preflight, checks, statuses, *, marker="stable"):
    check_doc = {"total_count": len(checks), "check_runs": list(checks)}
    status_doc = list(statuses)
    return [
        _response(check_doc, etag=f'W/"checks-{marker}"'),
        _response(status_doc, etag=f'W/"statuses-{marker}"'),
    ]


def _stable_transport(preflight, checks, statuses):
    one = _snapshot_responses(preflight, checks, statuses)
    two = _snapshot_responses(preflight, checks, statuses)
    return _Transport(one + two)


def _live_preflight():
    (
        approved,
        _review_observation,
        checkpoint,
        semantic,
        ledger_temp,
        tx_ledger,
        write_temp,
        parent_temp,
        cleanup,
    ) = parent._approved_chain()
    result = parent._run(
        approved,
        semantic,
        parent._transport(checkpoint, semantic, requested=False),
    )
    assert result.preflight_authenticated is True
    return (
        result,
        ledger_temp,
        tx_ledger,
        write_temp,
        parent_temp,
        cleanup,
    )


def _observe(preflight, transport, *, times=("2026-09-15T06:25:53Z", "2026-09-15T06:25:54Z")):
    clock = iter(times)
    return status_observation._observe_verified_pilot_exact_task_pr_status_checks(
        merge_preflight=preflight,
        transport=transport,
        now_provider=clock.__next__,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    parent.run_contract()
    (
        preflight,
        ledger_temp,
        tx_ledger,
        write_temp,
        parent_temp,
        cleanup,
    ) = _live_preflight()
    try:
        checks = [
            _check(preflight, run_id=8101, name="ci"),
            _check(
                preflight,
                run_id=8102,
                name="agent3-diagnostics",
                status="in_progress",
                conclusion=None,
            ),
        ]
        statuses = [
            _legacy(status_id=8201, context="legacy/security", state="success"),
        ]
        transport = _stable_transport(preflight, checks, statuses)
        result = _observe(preflight, transport)

        assert result.observation_authenticated is True
        assert result.merge_preflight_sha256 == preflight.sha256
        assert result.review_disposition_sha256 == preflight.review_disposition_sha256
        assert result.predicted_commit_sha == preflight.predicted_commit_sha
        assert result.check_run_count == 2
        assert result.legacy_status_count == 1
        assert result.check_run_page_count == 1
        assert result.legacy_status_page_count == 1
        assert result.first_check_runs_evidence_sha256 == result.second_check_runs_evidence_sha256
        assert result.first_statuses_evidence_sha256 == result.second_statuses_evidence_sha256
        assert result.first_combined_evidence_sha256 == result.second_combined_evidence_sha256

        live = status_observation._get_live_pr_status_check_observation_inputs(result)
        assert live is not None
        assert live["merge_preflight"] is preflight
        assert {row["name"] for row in live["check_runs"]} == {"ci", "agent3-diagnostics"}
        assert {row["context"] for row in live["legacy_statuses"]} == {"legacy/security"}
        assert {row["app_id"] for row in live["check_runs"]} == {15368}

        for field in (
            "source_merge_preflight_verified",
            "exact_head_sha_bound",
            "check_runs_inventory_complete",
            "legacy_status_inventory_complete",
            "stable_double_observation_verified",
            "credential_free_reads",
            "fixed_origin_reads",
            "redirects_forbidden",
            "response_bounded",
            "pagination_bounded",
            "check_run_limit_not_exceeded",
            "legacy_status_limit_not_exceeded",
            "fresh_merge_preflight_age_verified",
            "status_check_policy_required",
            "fresh_review_reobservation_before_merge_required",
            "review_threads_preflight_required",
            "branch_policy_preflight_required",
            "fresh_merge_transaction_revalidation_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "required_status_checks_evaluated",
            "status_policy_evaluated",
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "label_mutation_authorized",
            "merge_readiness_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        assert transport.calls[0][0].endswith(
            f"/commits/{preflight.predicted_commit_sha}/check-runs?filter=all&per_page=100&page=1"
        )
        assert transport.calls[1][0].endswith(
            f"/commits/{preflight.predicted_commit_sha}/statuses?per_page=100&page=1"
        )
        assert len(transport.calls) == 4
        for url, headers, timeout, maximum in transport.calls:
            assert url.startswith("https://api.github.com/repos/Ternedal/ModelRig/commits/")
            assert "Authorization" not in headers
            assert timeout == 20
            assert maximum == 512 * 1024

        replayed = status_observation.PilotExactTaskPrStatusCheckObservation.from_mapping(
            result.to_dict()
        )
        assert replayed == result and replayed.sha256 == result.sha256
        assert replayed.observation_authenticated is False

        loose_preflight = preflight_boundary.PilotExactTaskPrMergePreflight.from_mapping(
            preflight.to_dict()
        )
        assert loose_preflight.preflight_authenticated is False
        _reject(
            lambda: _observe(
                loose_preflight,
                _stable_transport(loose_preflight, checks, statuses),
            )
        )

        _reject(
            lambda: _observe(
                preflight,
                _stable_transport(
                    preflight,
                    [_check(preflight, run_id=8301, name="ci", head_sha="1" * 40)],
                    statuses,
                ),
            )
        )

        invalid_completed = _check(preflight, run_id=8302, name="ci")
        invalid_completed["conclusion"] = None
        _reject(
            lambda: _observe(
                preflight,
                _stable_transport(preflight, [invalid_completed], statuses),
            )
        )

        invalid_pending = _check(
            preflight,
            run_id=8303,
            name="ci",
            status="in_progress",
            conclusion=None,
        )
        invalid_pending["conclusion"] = "success"
        _reject(
            lambda: _observe(
                preflight,
                _stable_transport(preflight, [invalid_pending], statuses),
            )
        )

        first_checks = [_check(preflight, run_id=8401, name="ci", conclusion="success")]
        second_checks = [_check(preflight, run_id=8401, name="ci", conclusion="failure")]
        drift = _Transport(
            _snapshot_responses(preflight, first_checks, statuses, marker="first")
            + _snapshot_responses(preflight, second_checks, statuses, marker="second")
        )
        _reject(lambda: _observe(preflight, drift))

        _reject(
            lambda: _observe(
                preflight,
                _stable_transport(preflight, checks, statuses),
                times=("2026-09-15T06:26:53Z", "2026-09-15T06:26:54Z"),
            )
        )

        with patch.object(status_observation, "_PAGE_SIZE", 1), patch.object(
            status_observation, "_MAX_PAGES", 2
        ):
            page1 = {
                "total_count": 2,
                "check_runs": [_check(preflight, run_id=8501, name="one")],
            }
            page2 = {
                "total_count": 2,
                "check_runs": [_check(preflight, run_id=8502, name="two")],
            }
            bounded = _Transport(
                [
                    _response(page1, etag='W/"page-1"'),
                    _response(page2, etag='W/"page-2"'),
                ]
            )
            _reject(
                lambda: status_observation._read_check_runs(
                    head_sha=preflight.predicted_commit_sha,
                    transport=bounded,
                )
            )

        with patch.object(status_observation, "_PAGE_SIZE", 1), patch.object(
            status_observation, "_MAX_PAGES", 2
        ):
            bounded = _Transport(
                [
                    _response([_legacy(status_id=8601, context="one")], etag='W/"s-1"'),
                    _response([_legacy(status_id=8602, context="two")], etag='W/"s-2"'),
                ]
            )
            _reject(
                lambda: status_observation._read_legacy_statuses(
                    head_sha=preflight.predicted_commit_sha,
                    transport=bounded,
                )
            )

        too_many = _Transport(
            [
                _response(
                    {"total_count": 1001, "check_runs": []},
                    etag='W/"too-many"',
                )
            ]
        )
        _reject(
            lambda: status_observation._read_check_runs(
                head_sha=preflight.predicted_commit_sha,
                transport=too_many,
            )
        )

        tampered = result.to_dict()
        tampered["second_combined_evidence_sha256"] = "1" * 64
        _reject(
            lambda: status_observation.PilotExactTaskPrStatusCheckObservation.from_mapping(
                tampered
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            status_observation.PilotExactTaskPrStatusCheckObservation.__dataclass_fields__
        )
        assert len(fields) == 59
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["status_check_policy_required"]["const"] is True
        assert schema["properties"]["required_status_checks_evaluated"]["const"] is False
        assert schema["properties"]["status_policy_evaluated"]["const"] is False
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                status_observation.observe_pilot_exact_task_pr_status_checks
            ).parameters
        ) == ("merge_preflight",)
        module_source = inspect.getsource(status_observation)
        assert "UrllibReadOnlyTransport" in module_source
        assert "check-runs?filter=all" in module_source
        assert "/statuses" in module_source
        for forbidden in (
            'method="POST"',
            'method="PATCH"',
            'method="PUT"',
            'method="DELETE"',
            "run_bounded_subprocess",
            "merge_pull_request(",
            "enable_auto_merge",
            "add_review_to_pr",
            "resolve_review_thread",
            "label_pr(",
        ):
            assert forbidden not in module_source
    finally:
        ledger_temp.cleanup()
        tx_ledger.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
