"""ADR-DC-084 conservative active-ruleset applicability preflight."""
from __future__ import annotations

import hashlib
import json
import os
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_pr_ruleset_observation as source_boundary
from .improvement_pilot_exact_task_pr_ruleset_observation import PilotExactTaskPrRulesetObservation

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-ruleset-applicability/v1"
AUTHORITY = "classified-one-dc-l16-active-ruleset-applicability-only"


class PilotExactTaskPrRulesetApplicabilityError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _live_source(value: Any):
    if type(value) is not PilotExactTaskPrRulesetObservation:
        raise PilotExactTaskPrRulesetApplicabilityError("live ADR-DC-083 source required")
    replay = PilotExactTaskPrRulesetObservation.from_mapping(value.to_dict())
    live = source_boundary._get_live_pr_ruleset_observation_inputs(value)
    rulesets = () if live is None else tuple(live.get("rulesets", ()))
    if replay != value or value.observation_authenticated is not True or live is None or len(rulesets) != value.ruleset_count:
        raise PilotExactTaskPrRulesetApplicabilityError("ADR-DC-083 source invalid")
    if value.ruleset_policy_evaluation_required is not True or value.branch_policy_fully_evaluated is not False or value.merge_authorized is not False:
        raise PilotExactTaskPrRulesetApplicabilityError("ADR-DC-083 authority invalid")
    return value, rulesets


def _exact_list(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    result = []
    for item in value:
        if not isinstance(item, str) or not item or any(mark in item for mark in ("*", "?", "[", "]")):
            return None
        result.append(item)
    return tuple(result)


def _applies(detail: Mapping[str, Any]) -> bool | None:
    conditions = detail.get("conditions")
    if not isinstance(conditions, Mapping) or set(conditions) - {"ref_name", "repository_name"}:
        return None
    ref = conditions.get("ref_name")
    if ref is not None:
        if not isinstance(ref, Mapping) or set(ref) - {"include", "exclude"}:
            return None
        include, exclude = _exact_list(ref.get("include", [])), _exact_list(ref.get("exclude", []))
        if include is None or exclude is None:
            return None
        target = "refs/heads/main"
        if target in exclude or "~ALL" in exclude or "~DEFAULT_BRANCH" in exclude:
            return False
        if include and target not in include and "~ALL" not in include and "~DEFAULT_BRANCH" not in include:
            return False
    repo = conditions.get("repository_name")
    if repo is not None:
        if not isinstance(repo, Mapping) or set(repo) - {"include", "exclude", "protected"}:
            return None
        include, exclude = _exact_list(repo.get("include", [])), _exact_list(repo.get("exclude", []))
        if include is None or exclude is None:
            return None
        names = {"ModelRig", "Ternedal/ModelRig"}
        if "~ALL" in exclude or names.intersection(exclude):
            return False
        if include and "~ALL" not in include and not names.intersection(include):
            return False
    return True


_live: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any]]] = {}


def _get_live_pr_ruleset_applicability_inputs(result: Any) -> Mapping[str, Any] | None:
    row = _live.get(id(result))
    if row is None:
        return None
    pid, digest, result_ref, source_ref = row
    source = source_ref()
    if pid != os.getpid() or result_ref() is not result or source is None or source.observation_authenticated is not True or source.sha256 != result.ruleset_observation_sha256 or result.sha256 != digest:
        return None
    return MappingProxyType({"ruleset_observation": source})


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrRulesetApplicability:
    ruleset_observation_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    ruleset_inventory_sha256: str
    active_ruleset_count: int
    applicable_active_ruleset_count: int
    nonapplicable_active_ruleset_count: int
    unsupported_active_ruleset_count: int
    applicability_result: str
    source_rulesets_verified: bool = True
    exact_main_target_used: bool = True
    unsupported_rulesets_fail_closed: bool = True
    ruleset_policy_evaluation_still_required: bool = True
    required_status_checks_evaluated: bool = False
    branch_policy_fully_evaluated: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = AUTHORITY
    schema: str = SCHEMA

    def __post_init__(self):
        if self.schema != SCHEMA or self.authority != AUTHORITY or self.applicability_result not in {"SUPPORTED", "UNSUPPORTED"}:
            raise PilotExactTaskPrRulesetApplicabilityError("invalid applicability receipt")
        if self.active_ruleset_count != self.applicable_active_ruleset_count + self.nonapplicable_active_ruleset_count + self.unsupported_active_ruleset_count:
            raise PilotExactTaskPrRulesetApplicabilityError("ruleset counts inconsistent")
        if self.applicability_result == "SUPPORTED" and self.unsupported_active_ruleset_count != 0:
            raise PilotExactTaskPrRulesetApplicabilityError("supported receipt contains unsupported rulesets")
        if self.ruleset_policy_evaluation_still_required is not True or self.required_status_checks_evaluated is not False or self.branch_policy_fully_evaluated is not False or self.merge_authorized is not False or self.production_activation_authorized is not False:
            raise PilotExactTaskPrRulesetApplicabilityError("applicability receipt widened authority")

    @property
    def applicability_authenticated(self) -> bool:
        return _get_live_pr_ruleset_applicability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    def canonical_json(self):
        return _canonical(self.to_dict())

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskPrRulesetApplicabilityError("fields mismatch")
        return cls(**dict(value))


def classify_pilot_exact_task_pr_ruleset_applicability(ruleset_observation: PilotExactTaskPrRulesetObservation) -> PilotExactTaskPrRulesetApplicability:
    source, rulesets = _live_source(ruleset_observation)
    active = applicable = nonapplicable = unsupported = 0
    for detail in rulesets:
        if str(detail.get("enforcement", "")).lower() != "active":
            continue
        active += 1
        result = _applies(detail)
        if result is True:
            applicable += 1
        elif result is False:
            nonapplicable += 1
        else:
            unsupported += 1
    receipt = PilotExactTaskPrRulesetApplicability(
        ruleset_observation_sha256=source.sha256,
        repository=source.repository,
        pull_request_number=source.pull_request_number,
        predicted_commit_sha=source.predicted_commit_sha,
        ruleset_inventory_sha256=source.ruleset_inventory_sha256,
        active_ruleset_count=active,
        applicable_active_ruleset_count=applicable,
        nonapplicable_active_ruleset_count=nonapplicable,
        unsupported_active_ruleset_count=unsupported,
        applicability_result="UNSUPPORTED" if unsupported else "SUPPORTED",
    )
    key = id(receipt)
    def cleanup(_):
        _live.pop(key, None)
    _live[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), weakref.ref(source))
    if receipt.applicability_authenticated is not True:
        raise PilotExactTaskPrRulesetApplicabilityError("applicability receipt lost provenance")
    return receipt


__all__ = ["PilotExactTaskPrRulesetApplicabilityError", "PilotExactTaskPrRulesetApplicability", "classify_pilot_exact_task_pr_ruleset_applicability"]
