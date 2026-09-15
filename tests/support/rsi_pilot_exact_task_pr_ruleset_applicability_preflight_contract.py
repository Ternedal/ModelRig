"""Adversarial contract for ADR-DC-084 ruleset applicability preflight."""
from __future__ import annotations

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

from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_applicability as applicability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_observation as source_boundary  # noqa: E402
import rsi_pilot_exact_task_pr_ruleset_observation_contract as parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-ruleset-applicability-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (applicability.PilotExactTaskPrRulesetApplicabilityError, ValueError, TypeError, OSError, AssertionError):
        return
    raise AssertionError("ADR-DC-084 unexpectedly accepted unsafe applicability evidence")


def _source(rows=None):
    branch, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = parent._branch_source()
    source = parent._observe(branch, parent._stable_transport(rows))
    assert source.observation_authenticated is True
    return source, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup


def run_contract() -> None:
    if os.name == "nt":
        return
    parent.run_contract()
    source, ledger_temp, tx_ledger, write_temp, parent_temp, cleanup = _source()
    try:
        result = applicability.classify_pilot_exact_task_pr_ruleset_applicability(source)
        assert result.applicability_authenticated is True
        assert result.ruleset_observation_sha256 == source.sha256
        assert result.ruleset_inventory_sha256 == source.ruleset_inventory_sha256
        assert result.active_ruleset_count == 1
        assert result.applicable_active_ruleset_count == 1
        assert result.nonapplicable_active_ruleset_count == 0
        assert result.unsupported_active_ruleset_count == 0
        assert result.applicability_result == "SUPPORTED"
        assert result.source_rulesets_verified is True
        assert result.exact_main_target_used is True
        assert result.unsupported_rulesets_fail_closed is True
        assert result.ruleset_policy_evaluation_still_required is True
        assert result.required_status_checks_evaluated is False
        assert result.branch_policy_fully_evaluated is False
        assert result.merge_readiness_authorized is False
        assert result.merge_authorized is False
        assert result.production_activation_authorized is False

        live = applicability._get_live_pr_ruleset_applicability_inputs(result)
        assert live is not None and live["ruleset_observation"] is source
        replay = applicability.PilotExactTaskPrRulesetApplicability.from_mapping(result.to_dict())
        assert replay == result and replay.applicability_authenticated is False
        loose = source_boundary.PilotExactTaskPrRulesetObservation.from_mapping(source.to_dict())
        assert loose.observation_authenticated is False
        _reject(lambda: applicability.classify_pilot_exact_task_pr_ruleset_applicability(loose))

        active = parent._list_row(8491, name="wildcard-main", source_type="Repository", source="Ternedal/ModelRig", enforcement="active")
        unsupported_detail = parent._detail(active, conditions={"ref_name": {"include": ["refs/heads/*"], "exclude": []}})
        unsupported_source, a, b, c, d, extra = _source([(active, unsupported_detail)])
        try:
            unsupported = applicability.classify_pilot_exact_task_pr_ruleset_applicability(unsupported_source)
            assert unsupported.applicability_authenticated is True
            assert unsupported.applicability_result == "UNSUPPORTED"
            assert unsupported.active_ruleset_count == 1
            assert unsupported.applicable_active_ruleset_count == 0
            assert unsupported.unsupported_active_ruleset_count == 1
            assert unsupported.ruleset_policy_evaluation_still_required is True
            assert unsupported.merge_authorized is False
        finally:
            a.cleanup(); b.cleanup(); c.cleanup(); d.cleanup()
            for item in extra:
                item.cleanup()

        excluded = parent._list_row(8492, name="excluded-main", source_type="Repository", source="Ternedal/ModelRig", enforcement="active")
        excluded_detail = parent._detail(excluded, conditions={"ref_name": {"include": ["~ALL"], "exclude": ["refs/heads/main"]}})
        excluded_source, a, b, c, d, extra = _source([(excluded, excluded_detail)])
        try:
            classified = applicability.classify_pilot_exact_task_pr_ruleset_applicability(excluded_source)
            assert classified.applicability_result == "SUPPORTED"
            assert classified.active_ruleset_count == 1
            assert classified.nonapplicable_active_ruleset_count == 1
            assert classified.applicable_active_ruleset_count == 0
        finally:
            a.cleanup(); b.cleanup(); c.cleanup(); d.cleanup()
            for item in extra:
                item.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(applicability.PilotExactTaskPrRulesetApplicability.__dataclass_fields__)
        assert len(fields) == 21
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["ruleset_policy_evaluation_still_required"]["const"] is True
        assert schema["properties"]["required_status_checks_evaluated"]["const"] is False
        assert schema["properties"]["branch_policy_fully_evaluated"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
    finally:
        ledger_temp.cleanup(); tx_ledger.cleanup(); write_temp.cleanup(); parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()
