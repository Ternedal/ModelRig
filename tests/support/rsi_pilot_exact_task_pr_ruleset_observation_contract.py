"""Adversarial contract for ADR-DC-083 repository/inherited ruleset observation."""
from __future__ import annotations

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

from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_observation as ruleset  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_branch_protection_observation as branch_boundary  # noqa: E402
from kaliv_dev_control.github_read import HttpResponse  # noqa: E402
import rsi_pilot_exact_task_pr_branch_protection_observation_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-ruleset-observation-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (ruleset.PilotExactTaskPrRulesetObservationError, branch_boundary.PilotExactTaskPrBranchProtectionObservationError, ValueError, TypeError, OSError, AssertionError):
        return
    raise AssertionError("ADR-DC-083 unexpectedly accepted unsafe ruleset evidence")


def _response(value, *, etag: str) -> HttpResponse:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return HttpResponse(status=200, headers={"content-type": "application/vnd.github+json", "etag": etag}, body=payload)


class _Transport:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, timeout_seconds, max_bytes):
        self.calls.append((url, dict(headers), timeout_seconds, max_bytes))
        if not self.responses:
            raise AssertionError("unexpected extra ruleset read")
        return self.responses.pop(0)


def _branch_source():
    status_source, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = parent._source()
    branch = parent._run(status_source, parent._reader(status_source))
    assert branch.observation_authenticated is True
    return branch, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup


def _list_row(ruleset_id: int, *, name: str, source_type: str, source: str, enforcement: str):
    return {"id": ruleset_id, "name": name, "source_type": source_type, "source": source, "enforcement": enforcement}


def _detail(row, *, target="branch", rules=None, conditions=None):
    return {**row, "target": target, "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}} if conditions is None else conditions, "rules": [{"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": True, "required_status_checks": [{"context": "ci", "integration_id": 15368}]}}] if rules is None else rules}


def _snapshot_rows():
    inherited = _list_row(8301, name="org-main", source_type="Organization", source="Ternedal", enforcement="active")
    local = _list_row(8302, name="repo-evaluate", source_type="Repository", source="Ternedal/ModelRig", enforcement="evaluate")
    return [(inherited, _detail(inherited)), (local, _detail(local, rules=[{"type": "pull_request", "parameters": {"required_approving_review_count": 1, "dismiss_stale_reviews_on_push": True}}]))]


def _snapshot_responses(rows=None, *, marker="stable"):
    pairs = _snapshot_rows() if rows is None else rows
    return [_response([row for row, _detail_doc in pairs], etag=f'W/"list-{marker}"'), *[_response(detail_doc, etag=f'W/"detail-{row["id"]}-{marker}"') for row, detail_doc in pairs]]


def _stable_transport(rows=None):
    return _Transport(_snapshot_responses(rows, marker="stable") + _snapshot_responses(rows, marker="stable"))


def _observe(branch, transport, *, times=("2026-09-15T06:25:57Z", "2026-09-15T06:25:58Z")):
    clock = iter(times)
    return ruleset._observe_verified_pilot_exact_task_pr_rulesets(branch_protection_observation=branch, transport=transport, now_provider=clock.__next__)


def run_contract() -> None:
    if os.name == "nt":
        return
    parent.run_contract()
    branch, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = _branch_source()
    try:
        transport = _stable_transport()
        result = _observe(branch, transport)
        assert result.observation_authenticated is True
        assert result.branch_protection_observation_sha256 == branch.sha256
        assert result.status_check_observation_sha256 == branch.status_check_observation_sha256
        assert result.merge_preflight_sha256 == branch.merge_preflight_sha256
        assert result.predicted_commit_sha == branch.predicted_commit_sha
        assert result.base_branch_tip_sha == branch.base_branch_tip_sha
        assert result.ruleset_count == 2
        assert result.list_page_count == 1
        assert result.detail_read_count == 2
        assert result.active_ruleset_count == 1
        assert result.evaluate_ruleset_count == 1
        assert result.disabled_ruleset_count == 0
        assert result.other_enforcement_ruleset_count == 0
        assert result.first_list_evidence_sha256 == result.second_list_evidence_sha256
        assert result.first_detail_evidence_sha256 == result.second_detail_evidence_sha256
        assert result.first_combined_evidence_sha256 == result.second_combined_evidence_sha256
        live = ruleset._get_live_pr_ruleset_observation_inputs(result)
        assert live is not None
        assert live["branch_protection_observation"] is branch
        assert len(live["rulesets"]) == 2
        assert {item["source_type"] for item in live["rulesets"]} == {"Organization", "Repository"}
        assert live["rulesets"][0]["target"] == "branch"
        for field in ("source_branch_protection_observation_verified", "legacy_branch_protection_linked", "includes_parent_rulesets_verified", "branch_target_rulesets_only", "ruleset_list_inventory_complete", "ruleset_detail_inventory_complete", "stable_double_observation_verified", "credential_free_reads", "fixed_github_api_origin", "redirects_forbidden", "response_bounded", "pagination_bounded", "ruleset_count_bounded", "fresh_branch_protection_age_verified", "branch_policy_sources_observed", "bypass_actor_policy_not_relied_upon", "ruleset_policy_evaluation_required", "fresh_review_reobservation_before_merge_required", "review_threads_preflight_required", "fresh_merge_transaction_revalidation_required"):
            assert getattr(result, field) is True
        for field in ("required_status_checks_evaluated", "branch_policy_fully_evaluated", "status_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized"):
            assert getattr(result, field) is False
        assert transport.calls[0][0].endswith("/rulesets?includes_parents=true&targets=branch&per_page=100&page=1")
        assert transport.calls[1][0].endswith("/rulesets/8301?includes_parents=true")
        assert transport.calls[2][0].endswith("/rulesets/8302?includes_parents=true")
        assert len(transport.calls) == 6
        for url, headers, timeout, maximum in transport.calls:
            assert url.startswith("https://api.github.com/repos/Ternedal/ModelRig/rulesets")
            assert "Authorization" not in headers
            assert timeout == 20
            assert maximum == 512 * 1024
        replayed = ruleset.PilotExactTaskPrRulesetObservation.from_mapping(result.to_dict())
        assert replayed == result and replayed.sha256 == result.sha256
        assert replayed.observation_authenticated is False
        loose_branch = branch_boundary.PilotExactTaskPrBranchProtectionObservation.from_mapping(branch.to_dict())
        assert loose_branch.observation_authenticated is False
        _reject(lambda: _observe(loose_branch, _stable_transport()))
        empty = _observe(branch, _Transport([_response([], etag='W/"empty"'), _response([], etag='W/"empty"')]))
        assert empty.observation_authenticated is True
        assert empty.ruleset_count == 0
        assert empty.detail_read_count == 0
        assert empty.branch_policy_sources_observed is True
        assert empty.branch_policy_fully_evaluated is False
        row = _list_row(8310, name="bad-detail", source_type="Repository", source="Ternedal/ModelRig", enforcement="active")
        bad_identity = _detail(row)
        bad_identity["name"] = "drifted"
        _reject(lambda: _observe(branch, _Transport([_response([row], etag='W/"bad-list"'), _response(bad_identity, etag='W/"bad-detail"')])))
        wrong_target = _detail(row, target="tag")
        _reject(lambda: _observe(branch, _Transport([_response([row], etag='W/"tag-list"'), _response(wrong_target, etag='W/"tag-detail"')])))
        duplicate = [row, dict(row)]
        _reject(lambda: ruleset._read_snapshot(transport=_Transport([_response(duplicate, etag='W/"duplicate"')])))
        first = _snapshot_responses(marker="first")
        changed_pairs = _snapshot_rows()
        changed_pairs[0][1]["rules"][0]["parameters"]["strict_required_status_checks_policy"] = False
        second = _snapshot_responses(changed_pairs, marker="second")
        _reject(lambda: _observe(branch, _Transport(first + second)))
        with patch.object(ruleset, "_PAGE_SIZE", 1), patch.object(ruleset, "_MAX_PAGES", 2):
            page1_row = _list_row(8321, name="one", source_type="Repository", source="Ternedal/ModelRig", enforcement="active")
            page2_row = _list_row(8322, name="two", source_type="Repository", source="Ternedal/ModelRig", enforcement="active")
            _reject(lambda: ruleset._read_snapshot(transport=_Transport([_response([page1_row], etag='W/"p1"'), _response([page2_row], etag='W/"p2"')])))
        with patch.object(ruleset, "_MAX_RULESETS", 1):
            rows = _snapshot_rows()
            _reject(lambda: ruleset._read_snapshot(transport=_Transport([_response([row for row, _detail_doc in rows], etag='W/"too-many"')])))
        _reject(lambda: _observe(branch, _stable_transport(), times=("2026-09-15T06:26:57Z", "2026-09-15T06:26:58Z")))
        tampered = result.to_dict()
        tampered["second_combined_evidence_sha256"] = "1" * 64
        _reject(lambda: ruleset.PilotExactTaskPrRulesetObservation.from_mapping(tampered))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(ruleset.PilotExactTaskPrRulesetObservation.__dataclass_fields__)
        assert len(fields) == 63
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["includes_parent_rulesets_verified"]["const"] is True
        assert schema["properties"]["branch_policy_sources_observed"]["const"] is True
        assert schema["properties"]["ruleset_policy_evaluation_required"]["const"] is True
        assert schema["properties"]["required_status_checks_evaluated"]["const"] is False
        assert schema["properties"]["branch_policy_fully_evaluated"]["const"] is False
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(ruleset.observe_pilot_exact_task_pr_rulesets).parameters) == ("branch_protection_observation",)
        module_source = inspect.getsource(ruleset)
        assert "UrllibReadOnlyTransport" in module_source
        assert "includes_parents=true" in module_source
        assert "targets=branch" in module_source
        assert "Authorization" not in module_source
        for forbidden in ('method="POST"', 'method="PATCH"', 'method="PUT"', 'method="DELETE"', "run_bounded_subprocess", "merge_pull_request(", "enable_auto_merge", "add_review_to_pr", "resolve_review_thread", "label_pr("):
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
