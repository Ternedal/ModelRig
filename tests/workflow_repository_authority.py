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

    print(
        "===== REPOSITORY AUTHORITY: "
        f"{len(module.REQUIRED_STATUS_CHECKS)} checks; fail-closed matrix passed ====="
    )


if __name__ == "__main__":
    main()
