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

    def with_merge_queue(rs: dict, *, strict: bool, method: str = "MERGE", verdict: bool = True) -> dict:
        for rule in rs["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["strict_required_status_checks_policy"] = strict
                if verdict:
                    # D3: queue mode requires the Stage B aggregate check on top of the classic 14.
                    rule["parameters"]["required_status_checks"].append(
                        {"context": "stage-b-verdict", "integration_id": module.REQUIRED_STATUS_CHECK_APP_ID}
                    )
        rs["rules"].append({"type": "merge_queue", "parameters": {"merge_method": method, "max_entries_to_build": 1, "grouping_strategy": "ALLGREEN"}})
        return rs

    assert module.QUEUE_REQUIRED_STATUS_CHECKS == module.REQUIRED_STATUS_CHECKS + ("stage-b-verdict",), "queue mode = classic 14 + stage-b-verdict, nothing else"
    no_verdict = evaluate(r=[with_merge_queue(ruleset(), strict=False, verdict=False)])
    assert no_verdict["passed"] is False and "stage-b-verdict" in no_verdict["rulesets"]["missing_checks"], ("a merge queue without stage-b-verdict would land before Stage B (Codex P1 on #2427)", no_verdict)
    classic_with_verdict = evaluate(r=[ruleset()])
    assert classic_with_verdict["passed"] is True and "stage-b-verdict" not in classic_with_verdict["rulesets"]["missing_checks"], "without merge_queue the classic 14 still suffice (gate 10 unchanged today)"

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
    rsc_rule = next(r for r in shipped["rules"] if r["type"] == "required_status_checks")
    shipped_contexts = [c["context"] for c in rsc_rule["parameters"]["required_status_checks"]]
    assert shipped_contexts == list(module.QUEUE_REQUIRED_STATUS_CHECKS), "the shipped ruleset requires exactly the queue set (classic 14 + stage-b-verdict), in order"
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

    # ADR-SYS-003 step-3 tool: configure-repository-authority-ruleset.ps1 lives in
    # the repository ROOT beside the classic configure script and the verifier
    # (ChatGPT P1 on #2429 assumed scripts/), resolves the evaluator, the ruleset
    # and the verifier relative to $PSScriptRoot = root, and sends the REST API
    # only the ruleset fields -- never the file's "_comment".
    tool = ROOT / "configure-repository-authority-ruleset.ps1"
    assert tool.is_file(), "the ruleset configure script must live in the repository root"
    assert not (ROOT / "scripts" / "configure-repository-authority-ruleset.ps1").exists(), "no second copy under scripts/"
    assert (ROOT / "verify-repository-authority.ps1").is_file() and (ROOT / "configure-repository-authority.ps1").is_file(), "its siblings are in the root too"
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tests"))
    from support.source_code import code_of
    tool_src = code_of(tool)
    assert '$repoRoot = (Resolve-Path $PSScriptRoot).Path' in tool_src, "repo root is the script's own directory (the root)"
    assert 'Join-Path $repoRoot "scripts\\repository_authority.py"' in tool_src, "evaluator resolved from the root"
    assert 'Join-Path $repoRoot "deploy\\repository-authority\\main-ruleset.json"' in tool_src, "ruleset resolved from the root"
    assert 'Join-Path $repoRoot "verify-repository-authority.ps1"' in tool_src, "verifier resolved from the root"
    assert '$allowedTopLevel = @("name", "target", "enforcement", "bypass_actors", "conditions", "rules")' in tool_src, "request shape is the API's six fields"
    assert 'if ($property.Name -eq "_comment") { continue }' in tool_src, "_comment is stripped before POST/PUT"
    assert "$rulesetJson = $payloadObject | ConvertTo-Json -Depth 60" in tool_src, "the request body is built from the filtered object, not the raw file"
    assert "Get-Content -LiteralPath $rulesetFile -Raw -Encoding utf8\n" not in tool_src.replace("| ConvertFrom-Json", "\n"), "the raw file text is never the request body"
    # Codex P1 on #2429: -Apply must refuse while any required-check workflow lacks
    # merge_group (a queue would wait forever). The script checks the five
    # producers before sending; the producer map must name every queue context.
    assert '"exact-head-qualification.yml": ("exact-head-core", "legacy-merge-tree-equivalence", "stage-b-verdict")' in tool_src, "the producer map covers the queue-only context too"
    assert "Merge-queue prerequisite missing" in tool_src and "Nothing was sent." in tool_src, "a missing merge_group trigger refuses before any write"
    producer_contexts = set()
    import re as _re
    producers_block = tool_src.split("producers = {", 1)[1].split("}", 1)[0]
    producer_contexts = set(_re.findall(r'"([^"]+)"', producers_block)) - {"ci.yml", "codeql.yml", "agent3-diagnostics.yml", "agent3-full-diagnostics.yml", "exact-head-qualification.yml"}
    assert producer_contexts == set(module.QUEUE_REQUIRED_STATUS_CHECKS), ("the script's producer map must equal the queue-required set", producer_contexts ^ set(module.QUEUE_REQUIRED_STATUS_CHECKS))
    allowed = {"name", "target", "enforcement", "bypass_actors", "conditions", "rules"}
    extra = set(shipped) - allowed - {"_comment"}
    assert not extra, f"the shipped ruleset carries fields the API does not take: {sorted(extra)}"
    assert allowed <= set(shipped), "the shipped ruleset carries all six API fields"

    print(
        "===== REPOSITORY AUTHORITY: "
        f"{len(module.REQUIRED_STATUS_CHECKS)} checks; fail-closed matrix passed ====="
    )


if __name__ == "__main__":
    main()
