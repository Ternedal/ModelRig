from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "repository_authority.py"
spec = importlib.util.spec_from_file_location("modelrig_repository_authority", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

HEAD = "a" * 40


def branch(*, protected: bool = True, sha: str = HEAD) -> dict:
    return {"name": "main", "protected": protected, "commit": {"sha": sha}}


def classic() -> dict:
    checks = [
        {"context": name, "app_id": module.REQUIRED_STATUS_CHECK_APP_ID}
        for name in module.REQUIRED_STATUS_CHECKS
    ]
    return {
        "required_status_checks": {"strict": True, "checks": checks},
        "required_pull_request_reviews": {
            "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []}
        },
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
    }


def ruleset() -> dict:
    checks = [
        {"context": name, "integration_id": module.REQUIRED_STATUS_CHECK_APP_ID}
        for name in module.REQUIRED_STATUS_CHECKS
    ]
    return {
        "id": 42,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {
                "type": "pull_request",
                "parameters": {"required_review_thread_resolution": True},
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": checks,
                },
            },
            {"type": "non_fast_forward"},
            {"type": "deletion"},
        ],
    }


def evaluate(*, b=None, c=None, r=None, expected=HEAD):
    return module.evaluate_repository_authority(
        b or branch(), classic_protection=c, rulesets=r, expected_head=expected
    )


def main() -> None:
    result = evaluate(c=classic())
    assert result["passed"] is True, result
    assert result["authority_mode"] == "classic", result
    assert result["agent3_activation_authority"] is False
    assert result["physical_validation_authority"] is False
    assert result["production_activation"] is False

    missing = classic()
    missing["required_status_checks"]["checks"] = missing["required_status_checks"]["checks"][1:]
    result = evaluate(c=missing)
    assert result["passed"] is False, result
    assert result["classic"]["missing_checks"] == [module.REQUIRED_STATUS_CHECKS[0]], result

    wrong_source = classic()
    wrong_source["required_status_checks"]["checks"][0]["app_id"] = 999
    result = evaluate(c=wrong_source)
    assert result["passed"] is False, result
    assert module.REQUIRED_STATUS_CHECKS[0] in result["classic"]["wrong_source_checks"], result

    admin_bypass = classic()
    admin_bypass["enforce_admins"] = {"enabled": False}
    result = evaluate(c=admin_bypass)
    assert result["passed"] is False, result
    assert "administrators can bypass branch protection" in result["classic"]["errors"], result

    pr_bypass = classic()
    pr_bypass["required_pull_request_reviews"]["bypass_pull_request_allowances"]["users"] = [{"login": "owner"}]
    result = evaluate(c=pr_bypass)
    assert result["passed"] is False, result
    assert result["classic"]["pull_request_bypass_categories"] == ["users"], result

    force = classic()
    force["allow_force_pushes"] = {"enabled": True}
    assert evaluate(c=force)["passed"] is False

    deletion = classic()
    deletion["allow_deletions"] = {"enabled": True}
    assert evaluate(c=deletion)["passed"] is False

    unresolved = classic()
    unresolved["required_conversation_resolution"] = {"enabled": False}
    assert evaluate(c=unresolved)["passed"] is False

    result = evaluate(r=[ruleset()])
    assert result["passed"] is True, result
    assert result["authority_mode"] == "ruleset", result

    bypass_ruleset = ruleset()
    bypass_ruleset["bypass_actors"] = [{"actor_type": "RepositoryRole", "actor_id": 5}]
    assert evaluate(r=[bypass_ruleset])["passed"] is False

    assert evaluate(b=branch(protected=False), c=classic())["passed"] is False
    assert evaluate(c=classic(), expected="b" * 40)["passed"] is False

    # ADR-SYS-003 D2 (contract test 1): a merge queue replaces the up-to-date
    # requirement. strict alone: PASS (today). merge_queue alone: PASS without
    # the up-to-date warning. Neither: FAIL, not a warning. merge_queue with
    # bypass actors or a rewriting merge method: FAIL. Classic protection is
    # untouched by all of this (asserted above).
    import json

    def with_merge_queue(rs: dict, *, strict: bool, method: str = "MERGE") -> dict:
        for rule in rs["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["strict_required_status_checks_policy"] = strict
        rs["rules"].append({"type": "merge_queue", "parameters": {"merge_method": method, "max_entries_to_build": 1, "grouping_strategy": "ALLGREEN"}})
        return rs

    queue_only = evaluate(r=[with_merge_queue(ruleset(), strict=False)])
    assert queue_only["passed"] is True, queue_only
    assert queue_only["rulesets"]["merge_queue"] is True, queue_only
    assert not queue_only["warnings"], ("merge_queue must replace strict without a warning", queue_only["warnings"])

    both = evaluate(r=[with_merge_queue(ruleset(), strict=True)])
    assert both["passed"] is True and not both["warnings"], both

    strict_only = evaluate(r=[ruleset()])
    assert strict_only["passed"] is True and strict_only["rulesets"]["merge_queue"] is False, strict_only

    neither = ruleset()
    for rule in neither["rules"]:
        if rule["type"] == "required_status_checks":
            rule["parameters"]["strict_required_status_checks_policy"] = False
    neither_result = evaluate(r=[neither])
    assert neither_result["passed"] is False, ("neither strict nor merge_queue must FAIL, not warn", neither_result)
    assert any("neither" in e for e in neither_result["rulesets"]["errors"]), neither_result

    queue_bypass = with_merge_queue(ruleset(), strict=False)
    queue_bypass["bypass_actors"] = [{"actor_type": "RepositoryRole", "actor_id": 5}]
    assert evaluate(r=[queue_bypass])["passed"] is False

    squash_queue = evaluate(r=[with_merge_queue(ruleset(), strict=False, method="SQUASH")])
    assert squash_queue["passed"] is False and any("merge_method" in e for e in squash_queue["rulesets"]["errors"]), squash_queue
    lower_merge = evaluate(r=[with_merge_queue(ruleset(), strict=False, method="merge")])
    assert lower_merge["passed"] is True, ("merge_method is compared case-insensitively", lower_merge)

    # Contract test 5: the versioned ruleset the migration applies is valid
    # offline, and a mutation that drops a required rule is caught.
    shipped = json.loads((ROOT / "deploy" / "repository-authority" / "main-ruleset.json").read_text(encoding="utf-8"))
    shipped_result = evaluate(r=[shipped])
    assert shipped_result["passed"] is True and not shipped_result["warnings"], shipped_result
    assert shipped_result["rulesets"]["merge_queue"] is True
    assert shipped["bypass_actors"] == [], "the shipped ruleset must not have bypass actors"
    pr_rule = next(r for r in shipped["rules"] if r["type"] == "pull_request")
    assert pr_rule["parameters"].get("allowed_merge_methods") == ["merge"], "only merge commits may land (ADR-SYS-003 D5)"
    mq_rule = next(r for r in shipped["rules"] if r["type"] == "merge_queue")
    assert mq_rule["parameters"]["max_entries_to_build"] == 1 and mq_rule["parameters"]["grouping_strategy"] == "ALLGREEN", "one candidate at a time, all green (D5)"
    for dropped in ("deletion", "non_fast_forward", "pull_request", "required_status_checks"):
        mutant = json.loads(json.dumps(shipped))
        mutant["rules"] = [r for r in mutant["rules"] if r["type"] != dropped]
        assert evaluate(r=[mutant])["passed"] is False, f"dropping {dropped} from the shipped ruleset must fail"
    mutant = json.loads(json.dumps(shipped))
    for rule in mutant["rules"]:
        if rule["type"] == "required_status_checks":
            rule["parameters"]["required_status_checks"] = rule["parameters"]["required_status_checks"][:-1]
    assert evaluate(r=[mutant])["passed"] is False, "dropping one required check from the shipped ruleset must fail"

    print(
        "===== REPOSITORY AUTHORITY: "
        f"{len(module.REQUIRED_STATUS_CHECKS)} checks; fail-closed matrix passed ====="
    )


if __name__ == "__main__":
    main()
