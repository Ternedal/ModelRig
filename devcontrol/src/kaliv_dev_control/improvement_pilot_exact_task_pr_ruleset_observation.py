"""ADR-DC-083 credential-free repository/inherited ruleset observation.

Consumes one live authenticated ADR-DC-082 legacy branch-protection
observation. It reads the repository ruleset list with inherited parents
included, then reads every listed branch-target ruleset detail. The complete
inventory is bounded and repeated in full.

This boundary records conditions and rules exactly enough for a later explicit
policy evaluator. It does not decide applicability to main, status satisfaction,
merge readiness, or any mutation authority.
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
from typing import Any, Mapping

from .github_read import GitHubReadError, HttpResponse, ReadOnlyTransport, UrllibReadOnlyTransport
from . import improvement_pilot_exact_task_pr_branch_protection_observation as branch_boundary
from .improvement_pilot_exact_task_pr_branch_protection_observation import (
    PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_AUTHORITY,
    PilotExactTaskPrBranchProtectionObservation,
)

PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-ruleset-observation/v1"
PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_AUTHORITY = "observed-one-dc-l16-repository-and-inherited-branch-ruleset-inventory-only"
PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_SCOPE = "credential-free-stable-repository-inherited-branch-rulesets-v1"
PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_MAX_SOURCE_AGE_SECONDS = 60

_REPOSITORY = "Ternedal/ModelRig"
_TIMEOUT_SECONDS = 20
_MAX_RESPONSE_BYTES = 512 * 1024
_PAGE_SIZE = 100
_MAX_PAGES = 3
_MAX_RULESETS = 128
_MAX_RULES_PER_RULESET = 256
_MAX_JSON_DEPTH = 16
_MAX_COLLECTION_ITEMS = 1024
_MAX_MAPPING_KEYS = 512
_MAX_STRING_BYTES = 16 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPrRulesetObservationError(ValueError):
    """Ruleset evidence is stale, drifted, incomplete, or unsafe."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrRulesetObservationError("ruleset evidence is not canonical JSON") from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrRulesetObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrRulesetObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrRulesetObservationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrRulesetObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value: Any, *, name: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or len(value.encode("utf-8")) > maximum or "\x00" in value:
        raise PilotExactTaskPrRulesetObservationError(f"{name} is invalid")
    return value


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_JSON_DEPTH:
        raise PilotExactTaskPrRulesetObservationError("ruleset JSON nesting exceeds bound")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if isinstance(value, bool) or abs(value) > 2**63 - 1:
            raise PilotExactTaskPrRulesetObservationError("ruleset integer is out of bounds")
        return value
    if isinstance(value, float):
        raise PilotExactTaskPrRulesetObservationError("ruleset floating-point values are forbidden")
    if isinstance(value, str):
        if len(value.encode("utf-8")) > _MAX_STRING_BYTES or "\x00" in value:
            raise PilotExactTaskPrRulesetObservationError("ruleset string exceeds bound")
        return value
    if isinstance(value, list):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise PilotExactTaskPrRulesetObservationError("ruleset list exceeds bound")
        return [_bounded_json(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > _MAX_MAPPING_KEYS:
            raise PilotExactTaskPrRulesetObservationError("ruleset object exceeds key bound")
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key.encode("utf-8")) > 512 or "\x00" in key:
                raise PilotExactTaskPrRulesetObservationError("ruleset object key is invalid")
            clean[key] = _bounded_json(item, depth=depth + 1)
        return clean
    raise PilotExactTaskPrRulesetObservationError("ruleset JSON contains unsupported value type")


def _require_live_branch_observation(value: Any) -> PilotExactTaskPrBranchProtectionObservation:
    if type(value) is not PilotExactTaskPrBranchProtectionObservation:
        raise PilotExactTaskPrRulesetObservationError("exact live ADR-DC-082 branch-protection observation is required")
    try:
        replayed = PilotExactTaskPrBranchProtectionObservation.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrRulesetObservationError("ADR-DC-082 branch-protection replay validation failed") from exc
    live = branch_boundary._get_live_pr_branch_protection_observation_inputs(value)
    forced_false = ("required_status_checks_evaluated", "branch_policy_fully_evaluated", "status_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized")
    if replayed != value or replayed.sha256 != value.sha256 or value.authority != PILOT_EXACT_TASK_PR_BRANCH_PROTECTION_OBSERVATION_AUTHORITY or value.observation_authenticated is not True or live is None or value.legacy_branch_protection_observed is not True or value.rulesets_preflight_required is not True or value.review_threads_preflight_required is not True or value.fresh_review_reobservation_before_merge_required is not True or value.fresh_merge_transaction_revalidation_required is not True or any(getattr(value, name) is not False for name in forced_false) or value.repository != _REPOSITORY or value.base_branch != "main":
        raise PilotExactTaskPrRulesetObservationError("ruleset observation requires one live inert ADR-DC-082 observation")
    return value


def _require_source_window(value: PilotExactTaskPrBranchProtectionObservation, *, at_utc: str) -> None:
    at = _utc(at_utc, name="ruleset observation time")
    source = _utc(value.second_observed_at_utc, name="ADR-DC-082 second_observed_at_utc")
    if at < source or (at - source).total_seconds() > PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_MAX_SOURCE_AGE_SECONDS:
        raise PilotExactTaskPrRulesetObservationError("ADR-DC-082 branch-policy evidence is too old for ruleset observation")


def _headers() -> Mapping[str, str]:
    return MappingProxyType({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_API_VERSION, "User-Agent": "ModelRig-DevControl-ADR-DC-083"})


def _list_url(page: int) -> str:
    return "https://api.github.com/repos/Ternedal/ModelRig/rulesets" f"?includes_parents=true&targets=branch&per_page={_PAGE_SIZE}&page={page}"


def _detail_url(ruleset_id: int) -> str:
    return "https://api.github.com/repos/Ternedal/ModelRig/rulesets/" f"{ruleset_id}?includes_parents=true"


def _get(transport: ReadOnlyTransport, url: str) -> HttpResponse:
    try:
        response = transport.get(url, headers=_headers(), timeout_seconds=_TIMEOUT_SECONDS, max_bytes=_MAX_RESPONSE_BYTES)
    except GitHubReadError as exc:
        raise PilotExactTaskPrRulesetObservationError("credential-free fixed-origin GitHub ruleset read failed") from exc
    if type(response) is not HttpResponse or response.status != 200 or len(response.body) > _MAX_RESPONSE_BYTES:
        raise PilotExactTaskPrRulesetObservationError("GitHub ruleset response status/size is unsafe")
    return response


def _json(response: HttpResponse, *, name: str) -> Any:
    try:
        return json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrRulesetObservationError(f"{name} is not UTF-8 JSON") from exc


def _etag_sha256(headers: Mapping[str, str]) -> str:
    etag = headers.get("etag", "")
    if not isinstance(etag, str) or len(etag) > 512 or any(marker in etag for marker in ("\r", "\n", "\x00")):
        raise PilotExactTaskPrRulesetObservationError("GitHub ruleset ETag is invalid")
    return hashlib.sha256(etag.encode("utf-8")).hexdigest()


def _list_identity(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrRulesetObservationError("ruleset list row is not an object")
    ruleset_id = value.get("id")
    if isinstance(ruleset_id, bool) or not isinstance(ruleset_id, int) or ruleset_id < 1:
        raise PilotExactTaskPrRulesetObservationError("ruleset id is invalid")
    return MappingProxyType({"id": ruleset_id, "name": _text(value.get("name"), name="ruleset name"), "source_type": _text(value.get("source_type"), name="ruleset source_type", maximum=128), "source": _text(value.get("source"), name="ruleset source", maximum=512), "enforcement": _text(value.get("enforcement"), name="ruleset enforcement", maximum=128)})


def _normalize_detail(value: Any, *, identity: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrRulesetObservationError("ruleset detail is not an object")
    if value.get("id") != identity["id"] or value.get("name") != identity["name"] or value.get("source_type") != identity["source_type"] or value.get("source") != identity["source"] or value.get("enforcement") != identity["enforcement"] or value.get("target") != "branch":
        raise PilotExactTaskPrRulesetObservationError("ruleset detail identity drifted from list row")
    rules = value.get("rules")
    conditions = value.get("conditions")
    if not isinstance(rules, list) or len(rules) > _MAX_RULES_PER_RULESET or not isinstance(conditions, Mapping):
        raise PilotExactTaskPrRulesetObservationError("ruleset detail conditions/rules shape is invalid")
    return MappingProxyType({**dict(identity), "target": "branch", "conditions": _bounded_json(conditions), "rules": _bounded_json(rules)})


def _read_snapshot(*, transport: ReadOnlyTransport) -> Mapping[str, Any]:
    identities: list[Mapping[str, Any]] = []
    seen_ids: set[int] = set()
    list_evidence: list[Mapping[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        url = _list_url(page)
        response = _get(transport, url)
        document = _json(response, name="ruleset list response")
        if not isinstance(document, list) or len(document) > _PAGE_SIZE:
            raise PilotExactTaskPrRulesetObservationError("ruleset list response shape is invalid")
        page_rows = tuple(_list_identity(item) for item in document)
        for row in page_rows:
            if row["id"] in seen_ids:
                raise PilotExactTaskPrRulesetObservationError("duplicate ruleset id across pagination")
            seen_ids.add(row["id"])
            identities.append(row)
            if len(identities) > _MAX_RULESETS:
                raise PilotExactTaskPrRulesetObservationError("ruleset inventory exceeds bounded limit")
        list_evidence.append(MappingProxyType({"page": page, "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(), "body_sha256": hashlib.sha256(response.body).hexdigest(), "etag_sha256": _etag_sha256(response.headers), "row_count": len(page_rows)}))
        if len(page_rows) < _PAGE_SIZE:
            break
        if page == _MAX_PAGES:
            raise PilotExactTaskPrRulesetObservationError("ruleset list completeness cannot be proven within page bound")
    identities.sort(key=lambda item: item["id"])
    details: list[Mapping[str, Any]] = []
    detail_evidence: list[Mapping[str, Any]] = []
    for identity in identities:
        url = _detail_url(int(identity["id"]))
        response = _get(transport, url)
        detail = _normalize_detail(_json(response, name="ruleset detail response"), identity=identity)
        details.append(detail)
        detail_evidence.append(MappingProxyType({"id": identity["id"], "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(), "body_sha256": hashlib.sha256(response.body).hexdigest(), "etag_sha256": _etag_sha256(response.headers)}))
    serializable_details = [dict(item) for item in details]
    inventory_sha = hashlib.sha256(_canonical(serializable_details).encode("utf-8")).hexdigest()
    list_evidence_sha = hashlib.sha256(_canonical([dict(item) for item in list_evidence]).encode("utf-8")).hexdigest()
    detail_evidence_sha = hashlib.sha256(_canonical([dict(item) for item in detail_evidence]).encode("utf-8")).hexdigest()
    combined_sha = hashlib.sha256(_canonical({"ruleset_inventory_sha256": inventory_sha, "list_evidence_sha256": list_evidence_sha, "detail_evidence_sha256": detail_evidence_sha}).encode("utf-8")).hexdigest()
    enforcement_counts = {"active": 0, "evaluate": 0, "disabled": 0, "other": 0}
    for detail in details:
        enforcement = str(detail["enforcement"]).lower()
        if enforcement in enforcement_counts and enforcement != "other":
            enforcement_counts[enforcement] += 1
        else:
            enforcement_counts["other"] += 1
    return MappingProxyType({"rulesets": tuple(details), "ruleset_inventory_sha256": inventory_sha, "list_evidence_sha256": list_evidence_sha, "detail_evidence_sha256": detail_evidence_sha, "combined_evidence_sha256": combined_sha, "ruleset_count": len(details), "list_page_count": len(list_evidence), "detail_read_count": len(detail_evidence), "active_ruleset_count": enforcement_counts["active"], "evaluate_ruleset_count": enforcement_counts["evaluate"], "disabled_ruleset_count": enforcement_counts["disabled"], "other_enforcement_ruleset_count": enforcement_counts["other"]})


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrBranchProtectionObservation], tuple[Mapping[str, Any], ...]]] = {}


def _mark_authenticated(result: Any, source: PilotExactTaskPrBranchProtectionObservation, rulesets: tuple[Mapping[str, Any], ...]) -> None:
    key = id(result)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)
    _live_records[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(source), rulesets)


def _get_live_pr_ruleset_observation_inputs(result: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(result))
    if entry is None:
        return None
    pid, digest, result_ref, source_ref, rulesets = entry
    source = source_ref()
    inventory_sha = hashlib.sha256(_canonical([dict(item) for item in rulesets]).encode("utf-8")).hexdigest()
    if pid != os.getpid() or result_ref() is not result or source is None or source.observation_authenticated is not True or source.sha256 != result.branch_protection_observation_sha256 or inventory_sha != result.ruleset_inventory_sha256 or result.sha256 != digest:
        return None
    return MappingProxyType({"branch_protection_observation": source, "rulesets": rulesets})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrRulesetObservation:
    branch_protection_observation_sha256: str
    status_check_observation_sha256: str
    merge_preflight_sha256: str
    review_disposition_sha256: str
    repository: str
    pull_request_number: int
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    base_branch_tip_sha: str
    ruleset_list_endpoint_sha256: str
    first_list_evidence_sha256: str
    second_list_evidence_sha256: str
    first_detail_evidence_sha256: str
    second_detail_evidence_sha256: str
    ruleset_inventory_sha256: str
    first_combined_evidence_sha256: str
    second_combined_evidence_sha256: str
    ruleset_count: int
    list_page_count: int
    detail_read_count: int
    active_ruleset_count: int
    evaluate_ruleset_count: int
    disabled_ruleset_count: int
    other_enforcement_ruleset_count: int
    first_observed_at_utc: str
    second_observed_at_utc: str
    source_branch_protection_observation_verified: bool = True
    legacy_branch_protection_linked: bool = True
    includes_parent_rulesets_verified: bool = True
    branch_target_rulesets_only: bool = True
    ruleset_list_inventory_complete: bool = True
    ruleset_detail_inventory_complete: bool = True
    stable_double_observation_verified: bool = True
    credential_free_reads: bool = True
    fixed_github_api_origin: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    pagination_bounded: bool = True
    ruleset_count_bounded: bool = True
    fresh_branch_protection_age_verified: bool = True
    branch_policy_sources_observed: bool = True
    bypass_actor_policy_not_relied_upon: bool = True
    ruleset_policy_evaluation_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_AUTHORITY or self.observation_scope != PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_SCOPE:
            raise PilotExactTaskPrRulesetObservationError("ruleset observation schema/authority/scope unsupported")
        for name in ("branch_protection_observation_sha256", "status_check_observation_sha256", "merge_preflight_sha256", "review_disposition_sha256", "ruleset_list_endpoint_sha256", "first_list_evidence_sha256", "second_list_evidence_sha256", "first_detail_evidence_sha256", "second_detail_evidence_sha256", "ruleset_inventory_sha256", "first_combined_evidence_sha256", "second_combined_evidence_sha256"):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _hex40(self.base_branch_tip_sha, name="base_branch_tip_sha")
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if second < first:
            raise PilotExactTaskPrRulesetObservationError("ruleset observation clock moved backwards")
        if self.repository != _REPOSITORY or self.base_branch != "main" or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1 or self.first_list_evidence_sha256 != self.second_list_evidence_sha256 or self.first_detail_evidence_sha256 != self.second_detail_evidence_sha256 or self.first_combined_evidence_sha256 != self.second_combined_evidence_sha256 or self.detail_read_count != self.ruleset_count or self.active_ruleset_count + self.evaluate_ruleset_count + self.disabled_ruleset_count + self.other_enforcement_ruleset_count != self.ruleset_count:
            raise PilotExactTaskPrRulesetObservationError("ruleset observation exact target/evidence binding is invalid")
        for name, maximum, minimum in (("ruleset_count", _MAX_RULESETS, 0), ("detail_read_count", _MAX_RULESETS, 0), ("active_ruleset_count", _MAX_RULESETS, 0), ("evaluate_ruleset_count", _MAX_RULESETS, 0), ("disabled_ruleset_count", _MAX_RULESETS, 0), ("other_enforcement_ruleset_count", _MAX_RULESETS, 0), ("list_page_count", _MAX_PAGES, 1)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise PilotExactTaskPrRulesetObservationError(f"{name} is invalid")
        required_true = ("source_branch_protection_observation_verified", "legacy_branch_protection_linked", "includes_parent_rulesets_verified", "branch_target_rulesets_only", "ruleset_list_inventory_complete", "ruleset_detail_inventory_complete", "stable_double_observation_verified", "credential_free_reads", "fixed_github_api_origin", "redirects_forbidden", "response_bounded", "pagination_bounded", "ruleset_count_bounded", "fresh_branch_protection_age_verified", "branch_policy_sources_observed", "bypass_actor_policy_not_relied_upon", "ruleset_policy_evaluation_required", "fresh_review_reobservation_before_merge_required", "review_threads_preflight_required", "fresh_merge_transaction_revalidation_required")
        forced_false = ("required_status_checks_evaluated", "branch_policy_fully_evaluated", "status_policy_evaluated", "reviewer_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized", "ready_for_review_authorized", "label_mutation_authorized", "merge_readiness_authorized", "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized")
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrRulesetObservationError("ruleset evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrRulesetObservationError("ruleset observation cannot evaluate policy or grant mutation authority")

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_ruleset_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrRulesetObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrRulesetObservationError("ruleset observation must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrRulesetObservationError("ruleset observation fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_rulesets(*, branch_protection_observation: PilotExactTaskPrBranchProtectionObservation, transport: ReadOnlyTransport, now_provider: Any) -> PilotExactTaskPrRulesetObservation:
    source = _require_live_branch_observation(branch_protection_observation)
    first_at = now_provider()
    _require_source_window(source, at_utc=first_at)
    first = _read_snapshot(transport=transport)
    second_at = now_provider()
    _require_source_window(source, at_utc=second_at)
    if _utc(second_at, name="second_observed_at_utc") < _utc(first_at, name="first_observed_at_utc"):
        raise PilotExactTaskPrRulesetObservationError("clock moved backwards during ruleset observation")
    second = _read_snapshot(transport=transport)
    stable_keys = ("ruleset_inventory_sha256", "list_evidence_sha256", "detail_evidence_sha256", "combined_evidence_sha256", "ruleset_count", "list_page_count", "detail_read_count", "active_ruleset_count", "evaluate_ruleset_count", "disabled_ruleset_count", "other_enforcement_ruleset_count")
    if any(first[key] != second[key] for key in stable_keys):
        raise PilotExactTaskPrRulesetObservationError("ruleset inventory changed between complete observations")
    rulesets = tuple(first["rulesets"])
    result = PilotExactTaskPrRulesetObservation(branch_protection_observation_sha256=source.sha256, status_check_observation_sha256=source.status_check_observation_sha256, merge_preflight_sha256=source.merge_preflight_sha256, review_disposition_sha256=source.review_disposition_sha256, repository=source.repository, pull_request_number=source.pull_request_number, base_branch=source.base_branch, head_branch=source.head_branch, predicted_commit_sha=source.predicted_commit_sha, base_branch_tip_sha=source.base_branch_tip_sha, ruleset_list_endpoint_sha256=hashlib.sha256(_list_url(1).encode("utf-8")).hexdigest(), first_list_evidence_sha256=str(first["list_evidence_sha256"]), second_list_evidence_sha256=str(second["list_evidence_sha256"]), first_detail_evidence_sha256=str(first["detail_evidence_sha256"]), second_detail_evidence_sha256=str(second["detail_evidence_sha256"]), ruleset_inventory_sha256=str(first["ruleset_inventory_sha256"]), first_combined_evidence_sha256=str(first["combined_evidence_sha256"]), second_combined_evidence_sha256=str(second["combined_evidence_sha256"]), ruleset_count=int(first["ruleset_count"]), list_page_count=int(first["list_page_count"]), detail_read_count=int(first["detail_read_count"]), active_ruleset_count=int(first["active_ruleset_count"]), evaluate_ruleset_count=int(first["evaluate_ruleset_count"]), disabled_ruleset_count=int(first["disabled_ruleset_count"]), other_enforcement_ruleset_count=int(first["other_enforcement_ruleset_count"]), first_observed_at_utc=first_at, second_observed_at_utc=second_at)
    _mark_authenticated(result, source, rulesets)
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrRulesetObservationError("ruleset observation lost live provenance")
    return result


def observe_pilot_exact_task_pr_rulesets(branch_protection_observation: PilotExactTaskPrBranchProtectionObservation) -> PilotExactTaskPrRulesetObservation:
    """Observe repository + inherited branch rulesets only; never evaluate/mutate."""
    return _observe_verified_pilot_exact_task_pr_rulesets(branch_protection_observation=branch_protection_observation, transport=UrllibReadOnlyTransport(), now_provider=_now_utc_seconds)


__all__ = ["PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_SCHEMA", "PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_AUTHORITY", "PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_SCOPE", "PILOT_EXACT_TASK_PR_RULESET_OBSERVATION_MAX_SOURCE_AGE_SECONDS", "PilotExactTaskPrRulesetObservationError", "PilotExactTaskPrRulesetObservation", "observe_pilot_exact_task_pr_rulesets"]
