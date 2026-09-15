"""Adversarial contract for ADR-DC-087 strict base-sync preflight."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEVCONTROL_SRC):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_strict_base_sync_preflight_support as sync_support  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_required_status_evaluation as evaluation  # noqa: E402
from kaliv_dev_control.github_read import HttpResponse  # noqa: E402
import rsi_pilot_exact_task_pr_required_status_evaluation_contract as parent  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-strict-base-sync-preflight-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        sync.PilotExactTaskPrStrictBaseSyncPreflightError,
        evaluation.PilotExactTaskPrRequiredStatusEvaluationError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-087 unexpectedly accepted unsafe strict-sync evidence")


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


def _branch(sha: str):
    return {
        "name": "main",
        "commit": {"sha": sha},
        "protected": True,
    }


def _compare(
    base_sha: str,
    *,
    status: str = "ahead",
    ahead_by: int = 3,
    behind_by: int = 0,
    total_commits: int | None = None,
    base_commit_sha: str | None = None,
    merge_base_sha: str | None = None,
):
    if total_commits is None:
        total_commits = ahead_by
    return {
        "status": status,
        "ahead_by": ahead_by,
        "behind_by": behind_by,
        "total_commits": total_commits,
        "base_commit": {"sha": base_sha if base_commit_sha is None else base_commit_sha},
        "merge_base_commit": {
            "sha": base_sha if merge_base_sha is None else merge_base_sha
        },
        "commits": [],
        "files": [],
    }


class _Transport:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError("unexpected extra strict-sync read")
        return self.responses.pop(0)


def _live_evaluation():
    items = parent._live()
    required, status, *_ = items
    result = evaluation.evaluate_pilot_exact_task_pr_required_status(required, status)
    assert result.evaluation_authenticated is True
    assert result.evaluation_result == "PASS"
    assert result.strict_base_sync_preflight_required is True
    return result, items


def _cleanup(items) -> None:
    parent._cleanup(items)


def _transport(
    source,
    *,
    first_tip: str = "b" * 40,
    second_tip: str | None = None,
    compare_doc=None,
):
    if second_tip is None:
        second_tip = first_tip
    if compare_doc is None:
        compare_doc = _compare(first_tip)
    return _Transport(
        [
            _response(_branch(first_tip), etag='W/"main-first"'),
            _response(compare_doc, etag='W/"compare"'),
            _response(_branch(second_tip), etag='W/"main-second"'),
        ]
    )


def _observe(
    source,
    transport,
    *,
    times=("2026-09-15T19:00:00Z", "2026-09-15T19:00:03Z"),
):
    clock = iter(times)
    return sync._observe_verified_pilot_exact_task_pr_strict_base_sync_preflight(
        required_status_evaluation=source,
        transport=transport,
        now_provider=clock.__next__,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    parent.run_contract()
    source, items = _live_evaluation()
    try:
        transport = _transport(source)
        result = _observe(source, transport)

        assert result.preflight_authenticated is True
        assert result.required_status_evaluation_sha256 == source.sha256
        assert result.required_status_policy_sha256 == source.required_status_policy_sha256
        assert result.status_check_observation_sha256 == source.status_check_observation_sha256
        assert result.repository == source.repository == "Ternedal/ModelRig"
        assert result.pull_request_number == source.pull_request_number
        assert result.predicted_commit_sha == source.predicted_commit_sha
        assert result.base_branch == "main"
        assert result.first_base_tip_sha == result.second_base_tip_sha == "b" * 40
        assert result.base_commit_sha == "b" * 40
        assert result.merge_base_sha == "b" * 40
        assert result.compare_status == "ahead"
        assert result.ahead_by == 3
        assert result.behind_by == 0
        assert result.total_commits == 3

        for field in (
            "source_status_evaluation_verified",
            "source_required_status_pass_verified",
            "strict_policy_verified",
            "stable_base_tip_verified",
            "compare_exact_head_bound",
            "merge_base_equals_current_base",
            "head_contains_current_base",
            "credential_free_reads",
            "fixed_github_api_origin",
            "redirects_forbidden",
            "response_bounded",
            "observation_duration_bounded",
            "strict_base_sync_evaluated",
            "strict_base_sync_passed",
            "required_status_checks_passed",
            "review_threads_preflight_required",
            "fresh_review_reobservation_required",
            "fresh_required_status_reobservation_before_merge_required",
            "fresh_merge_transaction_revalidation_required",
        ):
            assert getattr(result, field) is True

        for field in (
            "branch_policy_fully_evaluated",
            "merge_readiness_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        assert len(transport.calls) == 3
        assert transport.calls[0][0] == (
            "https://api.github.com/repos/Ternedal/ModelRig/branches/main"
        )
        expected_compare = (
            "https://api.github.com/repos/Ternedal/ModelRig/compare/"
            + "b" * 40
            + "..."
            + source.predicted_commit_sha
            + "?per_page=1&page=1"
        )
        assert transport.calls[1][0] == expected_compare
        assert transport.calls[2][0] == transport.calls[0][0]
        for _url, headers, timeout, maximum in transport.calls:
            assert "Authorization" not in headers
            assert timeout == 20
            assert maximum in {256 * 1024, 4 * 1024 * 1024}

        replay = sync.PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(
            result.to_dict()
        )
        assert replay == result
        assert replay.sha256 == result.sha256
        assert replay.preflight_authenticated is False

        loose = evaluation.PilotExactTaskPrRequiredStatusEvaluation.from_mapping(
            source.to_dict()
        )
        assert loose.evaluation_authenticated is False
        untouched = _transport(source)
        _reject(lambda: _observe(loose, untouched))
        assert untouched.calls == []

        _reject(
            lambda: _observe(
                source,
                _transport(source, second_tip="c" * 40),
            )
        )
        _reject(
            lambda: _observe(
                source,
                _transport(
                    source,
                    compare_doc=_compare(
                        "b" * 40,
                        status="diverged",
                        ahead_by=3,
                        behind_by=1,
                        total_commits=3,
                    ),
                ),
            )
        )
        _reject(
            lambda: _observe(
                source,
                _transport(
                    source,
                    compare_doc=_compare(
                        "b" * 40,
                        merge_base_sha="c" * 40,
                    ),
                ),
            )
        )
        _reject(
            lambda: _observe(
                source,
                _transport(
                    source,
                    compare_doc=_compare(
                        "b" * 40,
                        base_commit_sha="c" * 40,
                    ),
                ),
            )
        )
        _reject(
            lambda: _observe(
                source,
                _transport(
                    source,
                    compare_doc=_compare(
                        "b" * 40,
                        total_commits=4,
                    ),
                ),
            )
        )
        _reject(
            lambda: _observe(
                source,
                _transport(source),
                times=("2026-09-15T19:00:00Z", "2026-09-15T19:00:11Z"),
            )
        )
        _reject(
            lambda: _observe(
                source,
                _transport(source),
                times=("2026-09-15T19:00:03Z", "2026-09-15T19:00:02Z"),
            )
        )

        wrong_branch = _Transport(
            [
                _response(
                    {"name": "not-main", "commit": {"sha": "b" * 40}},
                    etag='W/"wrong"',
                )
            ]
        )
        _reject(lambda: _observe(source, wrong_branch))

        identical_tip = source.predicted_commit_sha
        identical = _transport(
            source,
            first_tip=identical_tip,
            compare_doc=_compare(
                identical_tip,
                status="identical",
                ahead_by=0,
                behind_by=0,
                total_commits=0,
            ),
        )
        identical_result = _observe(source, identical)
        assert identical_result.compare_status == "identical"
        assert identical_result.strict_base_sync_passed is True

        tampered = result.to_dict()
        tampered["merge_authorized"] = True
        _reject(
            lambda: sync.PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(
                tampered
            )
        )
        tampered = result.to_dict()
        tampered["compare_request_url_sha256"] = "1" * 64
        _reject(
            lambda: sync.PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(
                tampered
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(sync.PilotExactTaskPrStrictBaseSyncPreflight.__dataclass_fields__)
        assert len(fields) == 53
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["strict_base_sync_passed"]["const"] is True
        assert (
            schema["properties"][
                "fresh_required_status_reobservation_before_merge_required"
            ]["const"]
            is True
        )
        assert (
            schema["properties"]["branch_policy_fully_evaluated"]["const"]
            is False
        )
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert (
            schema["properties"]["production_activation_authorized"]["const"]
            is False
        )

        assert tuple(
            inspect.signature(
                sync.observe_pilot_exact_task_pr_strict_base_sync_preflight
            ).parameters
        ) == ("required_status_evaluation",)

        module_source = inspect.getsource(sync)
        support_source = inspect.getsource(sync_support)
        combined_source = module_source + "\n" + support_source
        assert "UrllibReadOnlyTransport" in module_source
        assert "/branches/main" in support_source
        assert "/compare/" in support_source
        assert "?per_page=1&page=1" in support_source
        assert "Authorization" not in combined_source
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
            assert forbidden not in combined_source
    finally:
        _cleanup(items)


if __name__ == "__main__":
    run_contract()
