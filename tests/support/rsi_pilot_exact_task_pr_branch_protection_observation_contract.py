"""Adversarial contract for ADR-DC-082 legacy branch-protection observation."""
from __future__ import annotations

import hashlib
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_branch_protection_observation as branch_observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_status_check_observation as status_boundary  # noqa: E402
import rsi_pilot_exact_task_pr_status_check_observation_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-branch-protection-observation-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (branch_observation.PilotExactTaskPrBranchProtectionObservationError, status_boundary.PilotExactTaskPrStatusCheckObservationError, ValueError, TypeError, OSError, AssertionError):
        return
    raise AssertionError("ADR-DC-082 unexpectedly accepted unsafe branch-protection evidence")


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _source():
    preflight, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = parent._live_preflight()
    checks = [parent._check(preflight, run_id=82101, name="ci"), parent._check(preflight, run_id=82102, name="agent3-diagnostics", status="in_progress", conclusion=None)]
    statuses = [parent._legacy(status_id=82201, context="legacy/security", state="success")]
    result = parent._observe(preflight, parent._stable_transport(preflight, checks, statuses))
    assert result.observation_authenticated is True
    return result, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup


def _evidence(source, *, protection_status=200, branch_protected=True, contexts=("ci", "legacy/security"), checks=(("ci", 15368),), strict=True, reviews_present=True, approving_count=1, dismiss_stale=True, codeowners=False, last_push=True, conversations=True, enforce_admins=True, linear_history=True, allow_force_pushes=False, allow_deletions=False, block_creations=False, lock_branch=False, allow_fork_syncing=False, marker="stable"):
    present = protection_status == 200
    if not present:
        contexts = ()
        checks = ()
        strict = False
        reviews_present = False
        approving_count = 0
        dismiss_stale = False
        codeowners = False
        last_push = False
        conversations = False
        enforce_admins = False
        linear_history = False
        allow_force_pushes = False
        allow_deletions = False
        block_creations = False
        lock_branch = False
        allow_fork_syncing = False
    contexts = tuple(sorted(contexts))
    checks = tuple(sorted(checks, key=lambda pair: (pair[0], -2 if pair[1] is None else pair[1])))
    status_policy = {"present": bool(present and (contexts or checks or strict)), "strict": bool(strict), "contexts": list(contexts), "checks": [{"context": context, "app_id": app_id} for context, app_id in checks]}
    normalized = {"legacy_branch_protection_present": present, "required_status_checks_present": status_policy["present"], "required_status_checks_strict": bool(strict), "required_status_contexts": list(contexts), "required_status_checks": status_policy["checks"], "required_pull_request_reviews_present": bool(reviews_present), "required_approving_review_count": approving_count, "dismiss_stale_reviews": bool(dismiss_stale), "require_code_owner_reviews": bool(codeowners), "require_last_push_approval": bool(last_push), "required_conversation_resolution_enabled": bool(conversations), "enforce_admins_enabled": bool(enforce_admins), "required_linear_history_enabled": bool(linear_history), "allow_force_pushes_enabled": bool(allow_force_pushes), "allow_deletions_enabled": bool(allow_deletions), "block_creations_enabled": bool(block_creations), "lock_branch_enabled": bool(lock_branch), "allow_fork_syncing_enabled": bool(allow_fork_syncing)}
    branch_body = _canonical({"name": "main", "commit": {"sha": "b" * 40}, "protected": branch_protected}).encode("utf-8")
    protection_body = _canonical({"message": "Branch not protected"}).encode("utf-8") if protection_status == 404 else _canonical({"required_status_checks": status_policy, "required_pull_request_reviews": {"required_approving_review_count": approving_count, "dismiss_stale_reviews": dismiss_stale, "require_code_owner_reviews": codeowners, "require_last_push_approval": last_push} if reviews_present else None}).encode("utf-8")
    branch_url = "https://api.github.com/repos/Ternedal/ModelRig/branches/main"
    protection_url = branch_url + "/protection"
    return {"base_branch_tip_sha": "b" * 40, "base_branch_protected": branch_protected, "branch_request_url_sha256": hashlib.sha256(branch_url.encode("utf-8")).hexdigest(), "branch_response_body_sha256": hashlib.sha256(branch_body).hexdigest(), "branch_response_etag_sha256": hashlib.sha256(f'W/"branch-{marker}"'.encode("utf-8")).hexdigest(), "protection_http_status": protection_status, "protection_request_url_sha256": hashlib.sha256(protection_url.encode("utf-8")).hexdigest(), "protection_response_body_sha256": hashlib.sha256(protection_body).hexdigest(), "protection_response_etag_sha256": hashlib.sha256(f'W/"protection-{marker}"'.encode("utf-8")).hexdigest(), "credential_account_sha256": hashlib.sha256(b"ternedal").hexdigest(), "required_status_policy_sha256": hashlib.sha256(_canonical(status_policy).encode("utf-8")).hexdigest(), "normalized_protection_sha256": hashlib.sha256(_canonical(normalized).encode("utf-8")).hexdigest(), **normalized}


def _reader(value):
    def read(*, status_check_observation):
        assert status_check_observation is value
        return _evidence(value)
    return read


def _run(source, reader, *, times=("2026-09-15T06:25:55Z", "2026-09-15T06:25:56Z")):
    clock = iter(times)
    return branch_observation._observe_verified_pilot_exact_task_pr_branch_protection(status_check_observation=source, reader=reader, now_provider=clock.__next__)


def run_contract() -> None:
    if os.name == "nt":
        return
    parent.run_contract()
    source, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = _source()
    try:
        result = _run(source, _reader(source))
        assert result.observation_authenticated is True
        assert result.status_check_observation_sha256 == source.sha256
        assert result.merge_preflight_sha256 == source.merge_preflight_sha256
        assert result.predicted_commit_sha == source.predicted_commit_sha
        assert result.base_branch_tip_sha == "b" * 40
        assert result.protection_http_status == 200
        assert result.base_branch_protected is True
        assert result.legacy_branch_protection_present is True
        assert result.required_status_checks_present is True
        assert result.required_status_checks_strict is True
        assert result.required_status_context_count == 2
        assert result.required_status_check_count == 1
        assert result.required_pull_request_reviews_present is True
        assert result.required_approving_review_count == 1
        assert result.dismiss_stale_reviews is True
        assert result.require_last_push_approval is True
        assert result.required_conversation_resolution_enabled is True
        assert result.enforce_admins_enabled is True
        assert result.required_linear_history_enabled is True
        assert result.first_branch_response_body_sha256 == result.second_branch_response_body_sha256
        assert result.first_protection_response_body_sha256 == result.second_protection_response_body_sha256
        live = branch_observation._get_live_pr_branch_protection_observation_inputs(result)
        assert live is not None
        assert live["status_check_observation"] is source
        assert live["required_status_contexts"] == ("ci", "legacy/security")
        assert live["required_status_checks"] == (("ci", 15368),)
        for field in ("source_status_check_observation_verified", "stable_double_observation_verified", "account_bound_authenticated_reads", "host_token_file_credential_required", "pinned_github_transport_required", "administration_read_permission_required", "fixed_github_api_origin", "redirects_forbidden", "response_bounded", "fresh_status_observation_age_verified", "legacy_branch_protection_observed", "rulesets_preflight_required", "fresh_review_reobservation_before_merge_required", "review_threads_preflight_required", "fresh_merge_transaction_revalidation_required"):
            assert getattr(result, field) is True
        for field in ("required_status_checks_evaluated", "branch_policy_fully_evaluated", "status_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized"):
            assert getattr(result, field) is False
        no_legacy = _evidence(source, protection_status=404, branch_protected=True)
        def no_legacy_reader(*, status_check_observation):
            assert status_check_observation is source
            return no_legacy
        absent = _run(source, no_legacy_reader)
        assert absent.observation_authenticated is True
        assert absent.protection_http_status == 404
        assert absent.legacy_branch_protection_present is False
        assert absent.base_branch_protected is True
        assert absent.required_status_checks_present is False
        assert absent.required_status_context_count == 0
        assert absent.required_status_check_count == 0
        assert absent.rulesets_preflight_required is True
        assert absent.branch_policy_fully_evaluated is False
        replayed = branch_observation.PilotExactTaskPrBranchProtectionObservation.from_mapping(result.to_dict())
        assert replayed == result and replayed.sha256 == result.sha256
        assert replayed.observation_authenticated is False
        loose_source = status_boundary.PilotExactTaskPrStatusCheckObservation.from_mapping(source.to_dict())
        assert loose_source.observation_authenticated is False
        _reject(lambda: _run(loose_source, _reader(loose_source)))
        wrong_account = _evidence(source)
        wrong_account["credential_account_sha256"] = "1" * 64
        _reject(lambda: _run(source, lambda **_kwargs: wrong_account))
        wrong_url = _evidence(source)
        wrong_url["protection_request_url_sha256"] = "2" * 64
        _reject(lambda: _run(source, lambda **_kwargs: wrong_url))
        wrong_normalized = _evidence(source)
        wrong_normalized["normalized_protection_sha256"] = "3" * 64
        _reject(lambda: _run(source, lambda **_kwargs: wrong_normalized))
        forbidden_status = _evidence(source)
        forbidden_status["protection_http_status"] = 403
        _reject(lambda: _run(source, lambda **_kwargs: forbidden_status))
        inconsistent_absent = _evidence(source, protection_status=404)
        inconsistent_absent["required_status_checks_present"] = True
        _reject(lambda: _run(source, lambda **_kwargs: inconsistent_absent))
        first = _evidence(source, marker="first")
        second = _evidence(source, marker="second")
        calls = iter((first, second))
        def drift_reader(*, status_check_observation):
            assert status_check_observation is source
            return next(calls)
        _reject(lambda: _run(source, drift_reader))
        _reject(lambda: _run(source, _reader(source), times=("2026-09-15T06:26:55Z", "2026-09-15T06:26:56Z")))
        tampered = result.to_dict()
        tampered["second_protection_response_body_sha256"] = "4" * 64
        _reject(lambda: branch_observation.PilotExactTaskPrBranchProtectionObservation.from_mapping(tampered))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(branch_observation.PilotExactTaskPrBranchProtectionObservation.__dataclass_fields__)
        assert len(fields) == 76
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["administration_read_permission_required"]["const"] is True
        assert schema["properties"]["rulesets_preflight_required"]["const"] is True
        assert schema["properties"]["required_status_checks_evaluated"]["const"] is False
        assert schema["properties"]["branch_policy_fully_evaluated"]["const"] is False
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(branch_observation.observe_pilot_exact_task_pr_branch_protection).parameters) == ("status_check_observation",)
        production_source = inspect.getsource(branch_observation._read_exact_branch_protection)
        for required in ("EnvironmentFileGitHubCredentialProvider", "GitHubPinnedTransport", "GitHubTransportRequest", "_branch_path", "_protection_path", "transport.get"):
            assert required in production_source
        assert "GITHUB_TOKEN" not in production_source
        assert "GH_TOKEN" not in production_source
        module_source = inspect.getsource(branch_observation)
        assert "/repos/Ternedal/ModelRig/branches/main" in module_source
        assert "/protection" in module_source
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
