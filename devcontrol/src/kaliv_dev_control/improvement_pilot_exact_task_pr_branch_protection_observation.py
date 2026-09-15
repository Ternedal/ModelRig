"""ADR-DC-082 account-bound legacy branch-protection observation.

Consumes one live authenticated ADR-DC-081 exact-head status-check observation
and performs two bounded authenticated reads of the exact base branch plus its
legacy branch-protection endpoint. Credentials remain inside ModelRig's existing
host token-file + pinned GitHub transport boundary.

A 404 from the legacy protection endpoint means only that no legacy branch
protection document was observed. It is never interpreted as complete branch
policy because repository/parent rulesets are a separate required boundary.

This module grants no merge or mutation authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pr_status_check_observation as status_boundary
from .improvement_pilot_exact_task_pr_status_check_observation import (
    PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_AUTHORITY,
    PilotExactTaskPrStatusCheckObservation,
)

PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-branch-protection-observation/v1"
)
PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_AUTHORITY = (
    "observed-one-dc-l16-exact-base-legacy-branch-protection-only"
)
PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_SCOPE = (
    "account-bound-read-only-stable-legacy-branch-protection-v1"
)
PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_REPOSITORY = "Ternedal/ModelRig"
PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_CREDENTIAL_ACCOUNT = "ternedal"
PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_MAX_RESPONSE_BYTES = 256 * 1024
PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_MAX_SOURCE_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CONTEXT_MAX = 512
_MAX_REQUIRED_CHECKS = 256


class PilotExactTaskPrBranchProtectionObservationError(ValueError):
    """Legacy branch-protection evidence is stale, drifted, or unsafe."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrBranchProtectionObservationError("branch-protection evidence is not canonical JSON") from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrBranchProtectionObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrBranchProtectionObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrBranchProtectionObservationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrBranchProtectionObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _context(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or len(value.encode("utf-8")) > _CONTEXT_MAX or any(marker in value for marker in ("\r", "\n", "\x00")):
        raise PilotExactTaskPrBranchProtectionObservationError(f"{name} is invalid")
    return value


def _optional_enabled(value: Any, *, name: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, Mapping) or not isinstance(value.get("enabled"), bool):
        raise PilotExactTaskPrBranchProtectionObservationError(f"{name} is invalid")
    return bool(value["enabled"])


def _etag_sha256(headers: Mapping[str, str]) -> str:
    etag = headers.get("etag", "")
    if not isinstance(etag, str) or len(etag) > 512 or any(marker in etag for marker in ("\r", "\n", "\x00")):
        raise PilotExactTaskPrBranchProtectionObservationError("GitHub ETag is invalid")
    return hashlib.sha256(etag.encode("utf-8")).hexdigest()


def _require_live_status_observation(value: Any) -> PilotExactTaskPrStatusCheckObservation:
    if type(value) is not PilotExactTaskPrStatusCheckObservation:
        raise PilotExactTaskPrBranchProtectionObservationError("exact live ADR-DC-081 status-check observation is required")
    try:
        replayed = PilotExactTaskPrStatusCheckObservation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrBranchProtectionObservationError("ADR-DC-081 status-check observation replay validation failed") from exc
    live = status_boundary._get_live_pr_status_check_observation_inputs(value)
    forced_false = ("required_status_checks_evaluated", "status_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized")
    if replayed != value or replayed.sha256 != value.sha256 or value.authority != PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_AUTHORITY or value.observation_authenticated is not True or live is None or value.status_check_policy_required is not True or value.branch_policy_preflight_required is not True or value.review_threads_preflight_required is not True or value.fresh_review_reobservation_before_merge_required is not True or value.fresh_merge_transaction_revalidation_required is not True or any(getattr(value, name) is not False for name in forced_false) or value.repository != PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_REPOSITORY or value.base_branch != "main":
        raise PilotExactTaskPrBranchProtectionObservationError("branch-protection observation requires one live inert ADR-DC-081")
    return value


def _require_source_window(value: PilotExactTaskPrStatusCheckObservation, *, at_utc: str) -> None:
    at = _utc(at_utc, name="branch-protection observation time")
    source = _utc(value.second_observed_at_utc, name="ADR-DC-081 second_observed_at_utc")
    if at < source or (at - source).total_seconds() > PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_MAX_SOURCE_AGE_SECONDS:
        raise PilotExactTaskPrBranchProtectionObservationError("ADR-DC-081 status evidence is too old for branch-protection observation")


def _branch_path() -> str:
    return "/repos/Ternedal/ModelRig/branches/main"


def _protection_path() -> str:
    return "/repos/Ternedal/ModelRig/branches/main/protection"


def _parse_required_status_checks(value: Any) -> tuple[bool, bool, tuple[str, ...], tuple[tuple[str, int | None], ...]]:
    if value is None:
        return False, False, (), ()
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrBranchProtectionObservationError("required_status_checks is invalid")
    strict = value.get("strict")
    contexts = value.get("contexts", [])
    checks = value.get("checks", [])
    if not isinstance(strict, bool) or not isinstance(contexts, list) or not isinstance(checks, list) or len(contexts) > _MAX_REQUIRED_CHECKS or len(checks) > _MAX_REQUIRED_CHECKS:
        raise PilotExactTaskPrBranchProtectionObservationError("required status-check policy shape is invalid")
    normalized_contexts = tuple(sorted({_context(item, name="required status context") for item in contexts}))
    if len(normalized_contexts) != len(contexts):
        raise PilotExactTaskPrBranchProtectionObservationError("required status contexts contain duplicates")
    normalized_checks: list[tuple[str, int | None]] = []
    seen: set[tuple[str, int | None]] = set()
    for item in checks:
        if not isinstance(item, Mapping):
            raise PilotExactTaskPrBranchProtectionObservationError("required status check is not an object")
        context = _context(item.get("context"), name="required check context")
        app_id = item.get("app_id")
        if app_id is not None and (isinstance(app_id, bool) or not isinstance(app_id, int) or (app_id < 1 and app_id != -1)):
            raise PilotExactTaskPrBranchProtectionObservationError("required check app_id is invalid")
        pair = (context, app_id)
        if pair in seen:
            raise PilotExactTaskPrBranchProtectionObservationError("required checks contain duplicates")
        seen.add(pair)
        normalized_checks.append(pair)
    normalized_checks.sort(key=lambda pair: (pair[0], -2 if pair[1] is None else pair[1]))
    if normalized_contexts and normalized_checks and not {context for context, _app_id in normalized_checks}.issubset(set(normalized_contexts)):
        raise PilotExactTaskPrBranchProtectionObservationError("required check contexts drifted from context inventory")
    return True, strict, normalized_contexts, tuple(normalized_checks)


def _parse_pull_request_reviews(value: Any) -> tuple[bool, int, bool, bool, bool]:
    if value is None:
        return False, 0, False, False, False
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrBranchProtectionObservationError("required_pull_request_reviews is invalid")
    count = value.get("required_approving_review_count")
    dismiss = value.get("dismiss_stale_reviews")
    codeowners = value.get("require_code_owner_reviews")
    last_push = value.get("require_last_push_approval", False)
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 6 or not isinstance(dismiss, bool) or not isinstance(codeowners, bool) or not isinstance(last_push, bool):
        raise PilotExactTaskPrBranchProtectionObservationError("required pull-request review policy is invalid")
    return True, count, dismiss, codeowners, last_push


def _normalize_protection(*, status: int, body: bytes) -> Mapping[str, Any]:
    if status == 404:
        return MappingProxyType({"legacy_branch_protection_present": False, "required_status_checks_present": False, "required_status_checks_strict": False, "required_status_contexts": (), "required_status_checks": (), "required_pull_request_reviews_present": False, "required_approving_review_count": 0, "dismiss_stale_reviews": False, "require_code_owner_reviews": False, "require_last_push_approval": False, "required_conversation_resolution_enabled": False, "enforce_admins_enabled": False, "required_linear_history_enabled": False, "allow_force_pushes_enabled": False, "allow_deletions_enabled": False, "block_creations_enabled": False, "lock_branch_enabled": False, "allow_fork_syncing_enabled": False})
    if status != 200:
        raise PilotExactTaskPrBranchProtectionObservationError("legacy branch-protection read returned unsupported status")
    try:
        document = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrBranchProtectionObservationError("legacy branch-protection response is not UTF-8 JSON") from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrBranchProtectionObservationError("legacy branch-protection response must be an object")
    status_present, strict, contexts, checks = _parse_required_status_checks(document.get("required_status_checks"))
    reviews_present, approving_count, dismiss_stale, codeowners, last_push = _parse_pull_request_reviews(document.get("required_pull_request_reviews"))
    return MappingProxyType({"legacy_branch_protection_present": True, "required_status_checks_present": status_present, "required_status_checks_strict": strict, "required_status_contexts": contexts, "required_status_checks": checks, "required_pull_request_reviews_present": reviews_present, "required_approving_review_count": approving_count, "dismiss_stale_reviews": dismiss_stale, "require_code_owner_reviews": codeowners, "require_last_push_approval": last_push, "required_conversation_resolution_enabled": _optional_enabled(document.get("required_conversation_resolution"), name="required_conversation_resolution"), "enforce_admins_enabled": _optional_enabled(document.get("enforce_admins"), name="enforce_admins"), "required_linear_history_enabled": _optional_enabled(document.get("required_linear_history"), name="required_linear_history"), "allow_force_pushes_enabled": _optional_enabled(document.get("allow_force_pushes"), name="allow_force_pushes"), "allow_deletions_enabled": _optional_enabled(document.get("allow_deletions"), name="allow_deletions"), "block_creations_enabled": _optional_enabled(document.get("block_creations"), name="block_creations"), "lock_branch_enabled": _optional_enabled(document.get("lock_branch"), name="lock_branch"), "allow_fork_syncing_enabled": _optional_enabled(document.get("allow_fork_syncing"), name="allow_fork_syncing")})


def _read_exact_branch_protection(*, status_check_observation: PilotExactTaskPrStatusCheckObservation) -> Mapping[str, Any]:
    """Production read through the existing host token-file pinned transport."""
    checked = _require_live_status_observation(status_check_observation)
    try:
        from worker.app.github_connector_client import GitHubTransportRequest
        from worker.app.github_connector_transport import EnvironmentFileGitHubCredentialProvider, GitHubPinnedTransport
    except Exception as exc:
        raise PilotExactTaskPrBranchProtectionObservationError("pinned GitHub credential transport is unavailable") from exc
    try:
        credentials = EnvironmentFileGitHubCredentialProvider()
        transport = GitHubPinnedTransport(credentials=credentials)
    except Exception as exc:
        raise PilotExactTaskPrBranchProtectionObservationError("host GitHub branch-policy credential is unavailable") from exc
    if transport.account != PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_CREDENTIAL_ACCOUNT:
        raise PilotExactTaskPrBranchProtectionObservationError("GitHub credential account is not the pinned repository authority")
    headers = (("accept", "application/vnd.github+json"), ("x-github-api-version", PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_API_VERSION))
    branch_request = GitHubTransportRequest(path=_branch_path(), headers=headers, max_response_bytes=PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_MAX_RESPONSE_BYTES)
    protection_request = GitHubTransportRequest(path=_protection_path(), headers=headers, max_response_bytes=PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_MAX_RESPONSE_BYTES)
    try:
        branch_response = transport.get(branch_request)
        protection_response = transport.get(protection_request)
    except Exception as exc:
        raise PilotExactTaskPrBranchProtectionObservationError("pinned branch-protection read failed") from exc
    if branch_response.status != 200:
        raise PilotExactTaskPrBranchProtectionObservationError("base branch identity read returned non-success")
    if protection_response.status not in {200, 404}:
        raise PilotExactTaskPrBranchProtectionObservationError("legacy branch-protection endpoint is inaccessible or unsafe")
    for response in (branch_response, protection_response):
        if len(response.body) > PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_MAX_RESPONSE_BYTES:
            raise PilotExactTaskPrBranchProtectionObservationError("branch-policy response exceeded byte ceiling")
    try:
        branch = json.loads(branch_response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrBranchProtectionObservationError("base branch identity response is not UTF-8 JSON") from exc
    commit = None if not isinstance(branch, Mapping) else branch.get("commit")
    if not isinstance(branch, Mapping) or branch.get("name") != checked.base_branch or not isinstance(branch.get("protected"), bool) or not isinstance(commit, Mapping):
        raise PilotExactTaskPrBranchProtectionObservationError("base branch identity response drifted")
    branch_tip_sha = commit.get("sha")
    _hex40(branch_tip_sha, name="base branch tip SHA")
    normalized = _normalize_protection(status=protection_response.status, body=protection_response.body)
    required_status_policy = {"present": normalized["required_status_checks_present"], "strict": normalized["required_status_checks_strict"], "contexts": list(normalized["required_status_contexts"]), "checks": [{"context": context, "app_id": app_id} for context, app_id in normalized["required_status_checks"]]}
    normalized_policy = {key: (list(value) if key == "required_status_contexts" else [{"context": context, "app_id": app_id} for context, app_id in value] if key == "required_status_checks" else value) for key, value in normalized.items()}
    return MappingProxyType({"base_branch_tip_sha": branch_tip_sha, "base_branch_protected": bool(branch["protected"]), "branch_request_url_sha256": hashlib.sha256(branch_request.url.encode("utf-8")).hexdigest(), "branch_response_body_sha256": hashlib.sha256(branch_response.body).hexdigest(), "branch_response_etag_sha256": _etag_sha256(branch_response.headers), "protection_http_status": protection_response.status, "protection_request_url_sha256": hashlib.sha256(protection_request.url.encode("utf-8")).hexdigest(), "protection_response_body_sha256": hashlib.sha256(protection_response.body).hexdigest(), "protection_response_etag_sha256": _etag_sha256(protection_response.headers), "credential_account_sha256": hashlib.sha256(transport.account.encode("utf-8")).hexdigest(), "required_status_policy_sha256": hashlib.sha256(_canonical(required_status_policy).encode("utf-8")).hexdigest(), "normalized_protection_sha256": hashlib.sha256(_canonical(normalized_policy).encode("utf-8")).hexdigest(), **dict(normalized)})


def _validate_reader_evidence(value: Any, *, source: PilotExactTaskPrStatusCheckObservation) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrBranchProtectionObservationError("branch-protection reader evidence must be an object")
    expected = {"base_branch_tip_sha", "base_branch_protected", "branch_request_url_sha256", "branch_response_body_sha256", "branch_response_etag_sha256", "protection_http_status", "protection_request_url_sha256", "protection_response_body_sha256", "protection_response_etag_sha256", "credential_account_sha256", "required_status_policy_sha256", "normalized_protection_sha256", "legacy_branch_protection_present", "required_status_checks_present", "required_status_checks_strict", "required_status_contexts", "required_status_checks", "required_pull_request_reviews_present", "required_approving_review_count", "dismiss_stale_reviews", "require_code_owner_reviews", "require_last_push_approval", "required_conversation_resolution_enabled", "enforce_admins_enabled", "required_linear_history_enabled", "allow_force_pushes_enabled", "allow_deletions_enabled", "block_creations_enabled", "lock_branch_enabled", "allow_fork_syncing_enabled"}
    if set(value) != expected:
        raise PilotExactTaskPrBranchProtectionObservationError("branch-protection reader evidence fields mismatch")
    _hex40(value.get("base_branch_tip_sha"), name="base_branch_tip_sha")
    if not isinstance(value.get("base_branch_protected"), bool):
        raise PilotExactTaskPrBranchProtectionObservationError("base_branch_protected is invalid")
    for name in ("branch_request_url_sha256", "branch_response_body_sha256", "branch_response_etag_sha256", "protection_request_url_sha256", "protection_response_body_sha256", "protection_response_etag_sha256", "credential_account_sha256", "required_status_policy_sha256", "normalized_protection_sha256"):
        _hex64(value.get(name), name=name)
    expected_branch_url = "https://api.github.com" + _branch_path()
    expected_protection_url = "https://api.github.com" + _protection_path()
    if value["branch_request_url_sha256"] != hashlib.sha256(expected_branch_url.encode("utf-8")).hexdigest() or value["protection_request_url_sha256"] != hashlib.sha256(expected_protection_url.encode("utf-8")).hexdigest() or value["credential_account_sha256"] != hashlib.sha256(PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_CREDENTIAL_ACCOUNT.encode("utf-8")).hexdigest() or value["protection_http_status"] not in {200, 404}:
        raise PilotExactTaskPrBranchProtectionObservationError("branch-protection reader authority/URL evidence mismatch")
    boolean_names = ("legacy_branch_protection_present", "required_status_checks_present", "required_status_checks_strict", "required_pull_request_reviews_present", "dismiss_stale_reviews", "require_code_owner_reviews", "require_last_push_approval", "required_conversation_resolution_enabled", "enforce_admins_enabled", "required_linear_history_enabled", "allow_force_pushes_enabled", "allow_deletions_enabled", "block_creations_enabled", "lock_branch_enabled", "allow_fork_syncing_enabled")
    if any(not isinstance(value.get(name), bool) for name in boolean_names):
        raise PilotExactTaskPrBranchProtectionObservationError("branch-protection booleans are invalid")
    count = value.get("required_approving_review_count")
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 6:
        raise PilotExactTaskPrBranchProtectionObservationError("required_approving_review_count is invalid")
    contexts_raw = value.get("required_status_contexts")
    checks_raw = value.get("required_status_checks")
    if not isinstance(contexts_raw, (list, tuple)) or not isinstance(checks_raw, (list, tuple)) or len(contexts_raw) > _MAX_REQUIRED_CHECKS or len(checks_raw) > _MAX_REQUIRED_CHECKS:
        raise PilotExactTaskPrBranchProtectionObservationError("required status policy collections are invalid")
    contexts = tuple(sorted({_context(item, name="required status context") for item in contexts_raw}))
    if len(contexts) != len(contexts_raw):
        raise PilotExactTaskPrBranchProtectionObservationError("required status contexts contain duplicates")
    checks: list[tuple[str, int | None]] = []
    seen: set[tuple[str, int | None]] = set()
    for item in checks_raw:
        if isinstance(item, Mapping):
            context = _context(item.get("context"), name="required check context")
            app_id = item.get("app_id")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            context = _context(item[0], name="required check context")
            app_id = item[1]
        else:
            raise PilotExactTaskPrBranchProtectionObservationError("required check entry is invalid")
        if app_id is not None and (isinstance(app_id, bool) or not isinstance(app_id, int) or (app_id < 1 and app_id != -1)):
            raise PilotExactTaskPrBranchProtectionObservationError("required check app id is invalid")
        pair = (context, app_id)
        if pair in seen:
            raise PilotExactTaskPrBranchProtectionObservationError("required checks contain duplicates")
        seen.add(pair)
        checks.append(pair)
    checks.sort(key=lambda pair: (pair[0], -2 if pair[1] is None else pair[1]))
    if contexts and checks and not {item[0] for item in checks}.issubset(set(contexts)):
        raise PilotExactTaskPrBranchProtectionObservationError("required check contexts are inconsistent")
    normalized_policy = {"present": value["required_status_checks_present"], "strict": value["required_status_checks_strict"], "contexts": list(contexts), "checks": [{"context": context, "app_id": app_id} for context, app_id in checks]}
    if hashlib.sha256(_canonical(normalized_policy).encode("utf-8")).hexdigest() != value["required_status_policy_sha256"]:
        raise PilotExactTaskPrBranchProtectionObservationError("required status policy digest mismatch")
    if value["legacy_branch_protection_present"] is not (value["protection_http_status"] == 200):
        raise PilotExactTaskPrBranchProtectionObservationError("legacy protection presence/status mismatch")
    if value["legacy_branch_protection_present"] and value["base_branch_protected"] is not True:
        raise PilotExactTaskPrBranchProtectionObservationError("legacy branch protection cannot exist on an unprotected branch")
    if not value["required_status_checks_present"] and (value["required_status_checks_strict"] or contexts or checks):
        raise PilotExactTaskPrBranchProtectionObservationError("absent required-status-check policy contains claims")
    if not value["required_pull_request_reviews_present"] and (value["required_approving_review_count"] != 0 or value["dismiss_stale_reviews"] or value["require_code_owner_reviews"] or value["require_last_push_approval"]):
        raise PilotExactTaskPrBranchProtectionObservationError("absent pull-request review policy contains claims")
    normalized_protection = {"legacy_branch_protection_present": value["legacy_branch_protection_present"], "required_status_checks_present": value["required_status_checks_present"], "required_status_checks_strict": value["required_status_checks_strict"], "required_status_contexts": list(contexts), "required_status_checks": [{"context": context, "app_id": app_id} for context, app_id in checks], "required_pull_request_reviews_present": value["required_pull_request_reviews_present"], "required_approving_review_count": value["required_approving_review_count"], "dismiss_stale_reviews": value["dismiss_stale_reviews"], "require_code_owner_reviews": value["require_code_owner_reviews"], "require_last_push_approval": value["require_last_push_approval"], "required_conversation_resolution_enabled": value["required_conversation_resolution_enabled"], "enforce_admins_enabled": value["enforce_admins_enabled"], "required_linear_history_enabled": value["required_linear_history_enabled"], "allow_force_pushes_enabled": value["allow_force_pushes_enabled"], "allow_deletions_enabled": value["allow_deletions_enabled"], "block_creations_enabled": value["block_creations_enabled"], "lock_branch_enabled": value["lock_branch_enabled"], "allow_fork_syncing_enabled": value["allow_fork_syncing_enabled"]}
    if hashlib.sha256(_canonical(normalized_protection).encode("utf-8")).hexdigest() != value["normalized_protection_sha256"]:
        raise PilotExactTaskPrBranchProtectionObservationError("normalized branch-protection digest mismatch")
    if not value["legacy_branch_protection_present"]:
        if value["required_status_checks_present"] or value["required_pull_request_reviews_present"] or value["required_approving_review_count"] != 0 or any(value[name] for name in ("required_status_checks_strict", "dismiss_stale_reviews", "require_code_owner_reviews", "require_last_push_approval", "required_conversation_resolution_enabled", "enforce_admins_enabled", "required_linear_history_enabled", "allow_force_pushes_enabled", "allow_deletions_enabled", "block_creations_enabled", "lock_branch_enabled", "allow_fork_syncing_enabled")) or contexts or checks:
            raise PilotExactTaskPrBranchProtectionObservationError("404 legacy protection evidence contains policy claims")
    return MappingProxyType({**dict(value), "required_status_contexts": contexts, "required_status_checks": tuple(checks)})


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrStatusCheckObservation], tuple[str, ...], tuple[tuple[str, int | None], ...]]] = {}


def _mark_authenticated(result: Any, source: PilotExactTaskPrStatusCheckObservation, contexts: tuple[str, ...], checks: tuple[tuple[str, int | None], ...]) -> None:
    key = id(result)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)
    _live_records[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(source), contexts, checks)


def _get_live_pr_branch_protection_observation_inputs(result: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(result))
    if entry is None:
        return None
    pid, digest, result_ref, source_ref, contexts, checks = entry
    source = source_ref()
    policy = {"present": result.required_status_checks_present, "strict": result.required_status_checks_strict, "contexts": list(contexts), "checks": [{"context": context, "app_id": app_id} for context, app_id in checks]}
    if pid != os.getpid() or result_ref() is not result or source is None or source.observation_authenticated is not True or source.sha256 != result.status_check_observation_sha256 or hashlib.sha256(_canonical(policy).encode("utf-8")).hexdigest() != result.required_status_policy_sha256 or result.sha256 != digest:
        return None
    return MappingProxyType({"status_check_observation": source, "required_status_contexts": contexts, "required_status_checks": checks})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrBranchProtectionObservation:
    status_check_observation_sha256: str
    merge_preflight_sha256: str
    review_disposition_sha256: str
    review_observation_checkpoint_sha256: str
    repository: str
    pull_request_number: int
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    base_branch_tip_sha: str
    branch_request_url_sha256: str
    first_branch_response_body_sha256: str
    second_branch_response_body_sha256: str
    first_branch_response_etag_sha256: str
    second_branch_response_etag_sha256: str
    protection_http_status: int
    protection_request_url_sha256: str
    first_protection_response_body_sha256: str
    second_protection_response_body_sha256: str
    first_protection_response_etag_sha256: str
    second_protection_response_etag_sha256: str
    credential_account_sha256: str
    required_status_policy_sha256: str
    normalized_protection_sha256: str
    required_status_context_count: int
    required_status_check_count: int
    required_approving_review_count: int
    base_branch_protected: bool
    legacy_branch_protection_present: bool
    required_status_checks_present: bool
    required_status_checks_strict: bool
    required_pull_request_reviews_present: bool
    dismiss_stale_reviews: bool
    require_code_owner_reviews: bool
    require_last_push_approval: bool
    required_conversation_resolution_enabled: bool
    enforce_admins_enabled: bool
    required_linear_history_enabled: bool
    allow_force_pushes_enabled: bool
    allow_deletions_enabled: bool
    block_creations_enabled: bool
    lock_branch_enabled: bool
    allow_fork_syncing_enabled: bool
    first_observed_at_utc: str
    second_observed_at_utc: str
    source_status_check_observation_verified: bool = True
    stable_double_observation_verified: bool = True
    account_bound_authenticated_reads: bool = True
    host_token_file_credential_required: bool = True
    pinned_github_transport_required: bool = True
    administration_read_permission_required: bool = True
    fixed_github_api_origin: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    fresh_status_observation_age_verified: bool = True
    legacy_branch_protection_observed: bool = True
    rulesets_preflight_required: bool = True
    required_status_checks_evaluated: bool = False
    branch_policy_fully_evaluated: bool = False
    status_policy_evaluated: bool = False
    fresh_review_reobservation_before_merge_required: bool = True
    review_threads_preflight_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    reviewer_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_AUTHORITY or self.observation_scope != PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_SCOPE:
            raise PilotExactTaskPrBranchProtectionObservationError("branch-protection observation schema/authority/scope unsupported")
        for name in ("status_check_observation_sha256", "merge_preflight_sha256", "review_disposition_sha256", "review_observation_checkpoint_sha256", "branch_request_url_sha256", "first_branch_response_body_sha256", "second_branch_response_body_sha256", "first_branch_response_etag_sha256", "second_branch_response_etag_sha256", "protection_request_url_sha256", "first_protection_response_body_sha256", "second_protection_response_body_sha256", "first_protection_response_etag_sha256", "second_protection_response_etag_sha256", "credential_account_sha256", "required_status_policy_sha256", "normalized_protection_sha256"):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _hex40(self.base_branch_tip_sha, name="base_branch_tip_sha")
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if second < first:
            raise PilotExactTaskPrBranchProtectionObservationError("branch-protection observation clock moved backwards")
        if self.repository != PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_REPOSITORY or self.base_branch != "main" or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1 or self.protection_http_status not in {200, 404} or self.first_branch_response_body_sha256 != self.second_branch_response_body_sha256 or self.first_branch_response_etag_sha256 != self.second_branch_response_etag_sha256 or self.first_protection_response_body_sha256 != self.second_protection_response_body_sha256 or self.first_protection_response_etag_sha256 != self.second_protection_response_etag_sha256 or self.legacy_branch_protection_present is not (self.protection_http_status == 200):
            raise PilotExactTaskPrBranchProtectionObservationError("branch-protection exact target/evidence binding is invalid")
        for name in ("required_status_context_count", "required_status_check_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_REQUIRED_CHECKS:
                raise PilotExactTaskPrBranchProtectionObservationError(f"{name} is invalid")
        if isinstance(self.required_approving_review_count, bool) or not isinstance(self.required_approving_review_count, int) or not 0 <= self.required_approving_review_count <= 6:
            raise PilotExactTaskPrBranchProtectionObservationError("required_approving_review_count is invalid")
        required_true = ("source_status_check_observation_verified", "stable_double_observation_verified", "account_bound_authenticated_reads", "host_token_file_credential_required", "pinned_github_transport_required", "administration_read_permission_required", "fixed_github_api_origin", "redirects_forbidden", "response_bounded", "fresh_status_observation_age_verified", "legacy_branch_protection_observed", "rulesets_preflight_required", "fresh_review_reobservation_before_merge_required", "review_threads_preflight_required", "fresh_merge_transaction_revalidation_required")
        forced_false = ("required_status_checks_evaluated", "branch_policy_fully_evaluated", "status_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized")
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrBranchProtectionObservationError("branch-protection evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrBranchProtectionObservationError("branch-protection observation cannot grant policy/mutation authority")

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_branch_protection_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrBranchProtectionObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrBranchProtectionObservationError("branch-protection observation must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrBranchProtectionObservationError("branch-protection observation fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_branch_protection(*, status_check_observation: PilotExactTaskPrStatusCheckObservation, reader: Callable[..., Mapping[str, Any]], now_provider: Callable[[], str]) -> PilotExactTaskPrBranchProtectionObservation:
    source = _require_live_status_observation(status_check_observation)
    first_at = now_provider()
    _require_source_window(source, at_utc=first_at)
    first = _validate_reader_evidence(reader(status_check_observation=source), source=source)
    second_at = now_provider()
    _require_source_window(source, at_utc=second_at)
    if _utc(second_at, name="second_observed_at_utc") < _utc(first_at, name="first_observed_at_utc"):
        raise PilotExactTaskPrBranchProtectionObservationError("clock moved backwards during branch-protection observation")
    second = _validate_reader_evidence(reader(status_check_observation=source), source=source)
    if dict(first) != dict(second):
        raise PilotExactTaskPrBranchProtectionObservationError("branch-protection evidence changed between complete observations")
    contexts = tuple(first["required_status_contexts"])
    checks = tuple(first["required_status_checks"])
    result = PilotExactTaskPrBranchProtectionObservation(status_check_observation_sha256=source.sha256, merge_preflight_sha256=source.merge_preflight_sha256, review_disposition_sha256=source.review_disposition_sha256, review_observation_checkpoint_sha256=source.review_observation_checkpoint_sha256, repository=source.repository, pull_request_number=source.pull_request_number, base_branch=source.base_branch, head_branch=source.head_branch, predicted_commit_sha=source.predicted_commit_sha, base_branch_tip_sha=str(first["base_branch_tip_sha"]), branch_request_url_sha256=str(first["branch_request_url_sha256"]), first_branch_response_body_sha256=str(first["branch_response_body_sha256"]), second_branch_response_body_sha256=str(second["branch_response_body_sha256"]), first_branch_response_etag_sha256=str(first["branch_response_etag_sha256"]), second_branch_response_etag_sha256=str(second["branch_response_etag_sha256"]), protection_http_status=int(first["protection_http_status"]), protection_request_url_sha256=str(first["protection_request_url_sha256"]), first_protection_response_body_sha256=str(first["protection_response_body_sha256"]), second_protection_response_body_sha256=str(second["protection_response_body_sha256"]), first_protection_response_etag_sha256=str(first["protection_response_etag_sha256"]), second_protection_response_etag_sha256=str(second["protection_response_etag_sha256"]), credential_account_sha256=str(first["credential_account_sha256"]), required_status_policy_sha256=str(first["required_status_policy_sha256"]), normalized_protection_sha256=str(first["normalized_protection_sha256"]), required_status_context_count=len(contexts), required_status_check_count=len(checks), required_approving_review_count=int(first["required_approving_review_count"]), base_branch_protected=bool(first["base_branch_protected"]), legacy_branch_protection_present=bool(first["legacy_branch_protection_present"]), required_status_checks_present=bool(first["required_status_checks_present"]), required_status_checks_strict=bool(first["required_status_checks_strict"]), required_pull_request_reviews_present=bool(first["required_pull_request_reviews_present"]), dismiss_stale_reviews=bool(first["dismiss_stale_reviews"]), require_code_owner_reviews=bool(first["require_code_owner_reviews"]), require_last_push_approval=bool(first["require_last_push_approval"]), required_conversation_resolution_enabled=bool(first["required_conversation_resolution_enabled"]), enforce_admins_enabled=bool(first["enforce_admins_enabled"]), required_linear_history_enabled=bool(first["required_linear_history_enabled"]), allow_force_pushes_enabled=bool(first["allow_force_pushes_enabled"]), allow_deletions_enabled=bool(first["allow_deletions_enabled"]), block_creations_enabled=bool(first["block_creations_enabled"]), lock_branch_enabled=bool(first["lock_branch_enabled"]), allow_fork_syncing_enabled=bool(first["allow_fork_syncing_enabled"]), first_observed_at_utc=first_at, second_observed_at_utc=second_at)
    _mark_authenticated(result, source, contexts, checks)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrBranchProtectionObservationError("branch-protection observation lost live provenance")
    return result


def observe_pilot_exact_task_pr_branch_protection(status_check_observation: PilotExactTaskPrStatusCheckObservation) -> PilotExactTaskPrBranchProtectionObservation:
    """Observe legacy branch protection only; never evaluate or mutate."""
    return _observe_verified_pilot_exact_task_pr_branch_protection(status_check_observation=status_check_observation, reader=_read_exact_branch_protection, now_provider=_now_utc_seconds)


__all__ = ["PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_SCHEMA", "PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_AUTHORITY", "PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_SCOPE", "PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_MAX_SOURCE_AGE_SECONDS", "PilotExactTaskPrBranchProtectionObservationError", "PilotExactTaskPrBranchProtectionObservation", "observe_pilot_exact_task_pr_branch_protection"]
