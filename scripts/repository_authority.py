from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
from typing import Any, Iterable


FORMAT = "modelrig-repository-authority"
VERSION = 1
REPOSITORY = "Ternedal/ModelRig"
BRANCH = "main"
REQUIRED_STATUS_CHECK_APP_ID = 15368

# Exact check-run names observed on the current normal CI/qualification model.
# Keep this list deliberately small and stable: these are the gates that protect
# the repository trust boundary, not every diagnostic job that may exist.
REQUIRED_STATUS_CHECKS = (
    "test / test",
    "test / test-windows-appliance",
    "test / test-windows-tool-isolation",
    "browser-use-runtime-contract",
    "android-compile",
    "desktop-compile",
    "desktop-dpapi-windows",
    "agent3-memory-dpapi-windows",
    "analyze (go)",
    "analyze (python)",
    "agent3-python",
    "full-test-log",
    "exact-head-core",
    "legacy-merge-tree-equivalence",
)


def _enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return value.get("enabled") is True
    return False


def _classic_checks(protection: dict[str, Any]) -> set[str]:
    required = protection.get("required_status_checks") or {}
    checks: set[str] = set()
    for context in required.get("contexts") or []:
        if isinstance(context, str) and context:
            checks.add(context)
    for check in required.get("checks") or []:
        if isinstance(check, dict):
            context = check.get("context")
            if isinstance(context, str) and context:
                checks.add(context)
    return checks


def _classic_source_bound_checks(protection: dict[str, Any]) -> set[str]:
    required = protection.get("required_status_checks") or {}
    checks: set[str] = set()
    for check in required.get("checks") or []:
        if not isinstance(check, dict):
            continue
        context = check.get("context")
        if (
            isinstance(context, str)
            and context
            and check.get("app_id") == REQUIRED_STATUS_CHECK_APP_ID
        ):
            checks.add(context)
    return checks


def _classic_pr_bypass_categories(protection: dict[str, Any]) -> list[str]:
    reviews = protection.get("required_pull_request_reviews") or {}
    if not isinstance(reviews, dict):
        return ["<unreadable>"]
    allowances = reviews.get("bypass_pull_request_allowances") or {}
    if not isinstance(allowances, dict):
        return ["<unreadable>"] if allowances else []
    present: list[str] = []
    for category in ("users", "teams", "apps"):
        value = allowances.get(category)
        if isinstance(value, (list, tuple, set)):
            if value:
                present.append(category)
        elif value:
            present.append(category)
    return present


def evaluate_classic(protection: dict[str, Any] | None) -> dict[str, Any]:
    if not protection:
        return {
            "mode": "classic",
            "passed": False,
            "missing_checks": list(REQUIRED_STATUS_CHECKS),
            "errors": ["classic branch protection is absent or unreadable"],
            "warnings": [],
        }

    checks = _classic_checks(protection)
    source_bound_checks = _classic_source_bound_checks(protection)
    missing = [name for name in REQUIRED_STATUS_CHECKS if name not in checks]
    wrong_source = [
        name
        for name in REQUIRED_STATUS_CHECKS
        if name in checks and name not in source_bound_checks
    ]
    errors: list[str] = []
    warnings: list[str] = []

    if protection.get("required_pull_request_reviews") is None:
        errors.append("pull requests are not required before merge")
    bypass_categories = _classic_pr_bypass_categories(protection)
    if bypass_categories:
        errors.append(
            "pull request requirements have bypass allowances: "
            + ", ".join(bypass_categories)
        )
    if missing:
        errors.append("required exact-green status checks are incomplete")
    if wrong_source:
        errors.append(
            f"required status checks are not bound to GitHub Actions app {REQUIRED_STATUS_CHECK_APP_ID}"
        )
    if not _enabled(protection.get("enforce_admins")):
        errors.append("administrators can bypass branch protection")
    if _enabled(protection.get("allow_force_pushes")):
        errors.append("force pushes are allowed")
    if _enabled(protection.get("allow_deletions")):
        errors.append("branch deletion is allowed")
    if not _enabled(protection.get("required_conversation_resolution")):
        errors.append("review conversation resolution is not required")

    strict = bool((protection.get("required_status_checks") or {}).get("strict"))
    if not strict:
        warnings.append("required status checks do not require an up-to-date branch")

    return {
        "mode": "classic",
        "passed": not errors,
        "required_checks": sorted(checks),
        "source_bound_checks": sorted(source_bound_checks),
        "missing_checks": missing,
        "wrong_source_checks": wrong_source,
        "required_check_app_id": REQUIRED_STATUS_CHECK_APP_ID,
        "pull_request_bypass_categories": bypass_categories,
        "strict_required_status_checks": strict,
        "errors": errors,
        "warnings": warnings,
    }


def _ref_pattern_matches_main(pattern: str) -> bool:
    if pattern in {"~ALL", "~DEFAULT_BRANCH", "main", "refs/heads/main"}:
        return True
    return fnmatch.fnmatch("refs/heads/main", pattern)


def _ruleset_applies_to_main(ruleset: dict[str, Any]) -> bool:
    if ruleset.get("enforcement") != "active" or ruleset.get("target") != "branch":
        return False
    ref_name = ((ruleset.get("conditions") or {}).get("ref_name") or {})
    includes = [x for x in (ref_name.get("include") or []) if isinstance(x, str)]
    excludes = [x for x in (ref_name.get("exclude") or []) if isinstance(x, str)]
    if includes and not any(_ref_pattern_matches_main(pattern) for pattern in includes):
        return False
    if any(_ref_pattern_matches_main(pattern) for pattern in excludes):
        return False
    return True


def _iter_rules(rulesets: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for ruleset in rulesets:
        if not _ruleset_applies_to_main(ruleset):
            continue
        for rule in ruleset.get("rules") or []:
            if isinstance(rule, dict):
                yield rule


def evaluate_rulesets(rulesets: list[dict[str, Any]] | None) -> dict[str, Any]:
    applicable = [
        r
        for r in (rulesets or [])
        if isinstance(r, dict) and _ruleset_applies_to_main(r)
    ]
    if not applicable:
        return {
            "mode": "ruleset",
            "passed": False,
            "missing_checks": list(REQUIRED_STATUS_CHECKS),
            "errors": ["no active branch ruleset applies to main"],
            "warnings": [],
        }

    errors: list[str] = []
    warnings: list[str] = []
    rule_types: set[str] = set()
    required_checks: set[str] = set()
    source_bound_checks: set[str] = set()
    strict = False
    review_resolution = False

    for ruleset in applicable:
        if ruleset.get("bypass_actors"):
            errors.append(f"ruleset {ruleset.get('id', '<unknown>')} has bypass actors")

    for rule in _iter_rules(applicable):
        rule_type = rule.get("type")
        if isinstance(rule_type, str):
            rule_types.add(rule_type)
        parameters = rule.get("parameters") or {}
        if rule_type == "required_status_checks":
            strict = strict or parameters.get("strict_required_status_checks_policy") is True
            for check in parameters.get("required_status_checks") or []:
                if not isinstance(check, dict):
                    continue
                context = check.get("context")
                if isinstance(context, str) and context:
                    required_checks.add(context)
                    if check.get("integration_id") == REQUIRED_STATUS_CHECK_APP_ID:
                        source_bound_checks.add(context)
        elif rule_type == "pull_request":
            review_resolution = review_resolution or parameters.get("required_review_thread_resolution") is True

    missing = [name for name in REQUIRED_STATUS_CHECKS if name not in required_checks]
    wrong_source = [
        name
        for name in REQUIRED_STATUS_CHECKS
        if name in required_checks and name not in source_bound_checks
    ]
    for required_rule in ("pull_request", "required_status_checks", "non_fast_forward", "deletion"):
        if required_rule not in rule_types:
            errors.append(f"required ruleset rule is missing: {required_rule}")
    if missing:
        errors.append("required exact-green status checks are incomplete")
    if wrong_source:
        errors.append(
            f"required status checks are not bound to GitHub Actions app {REQUIRED_STATUS_CHECK_APP_ID}"
        )
    if not review_resolution:
        errors.append("review conversation resolution is not required")
    if not strict:
        warnings.append("required status checks do not require an up-to-date branch")

    return {
        "mode": "ruleset",
        "passed": not errors,
        "applicable_ruleset_ids": [r.get("id") for r in applicable],
        "required_checks": sorted(required_checks),
        "source_bound_checks": sorted(source_bound_checks),
        "missing_checks": missing,
        "wrong_source_checks": wrong_source,
        "required_check_app_id": REQUIRED_STATUS_CHECK_APP_ID,
        "strict_required_status_checks": strict,
        "errors": errors,
        "warnings": warnings,
    }


def evaluate_repository_authority(
    branch: dict[str, Any],
    *,
    classic_protection: dict[str, Any] | None = None,
    rulesets: list[dict[str, Any]] | None = None,
    expected_head: str | None = None,
) -> dict[str, Any]:
    head = (((branch or {}).get("commit") or {}).get("sha"))
    errors: list[str] = []
    if branch.get("name") != BRANCH:
        errors.append("branch payload is not main")
    if not isinstance(head, str) or len(head) != 40:
        errors.append("main head is not a canonical Git revision")
    if expected_head and head != expected_head.lower():
        errors.append("GitHub main head does not match the expected checkout revision")
    if branch.get("protected") is not True:
        errors.append("GitHub reports main as unprotected")

    classic = evaluate_classic(classic_protection)
    ruleset = evaluate_rulesets(rulesets)
    passing_modes = [item for item in (classic, ruleset) if item["passed"]]
    if not passing_modes:
        errors.append(
            "neither classic branch protection nor an equivalent active ruleset satisfies ModelRig repository authority"
        )

    selected = passing_modes[0] if passing_modes else None
    return {
        "format": FORMAT,
        "version": VERSION,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "head_revision": head,
        "protected": branch.get("protected") is True,
        "authority_mode": selected["mode"] if selected else None,
        "required_status_checks": list(REQUIRED_STATUS_CHECKS),
        "required_status_check_app_id": REQUIRED_STATUS_CHECK_APP_ID,
        "passed": not errors,
        "errors": errors,
        "warnings": list(selected.get("warnings", [])) if selected else [],
        "classic": classic,
        "rulesets": ruleset,
        "physical_validation_authority": False,
        "agent3_activation_authority": False,
        "production_activation": False,
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate ModelRig GitHub main repository authority.")
    parser.add_argument("--branch-json", type=Path, required=True)
    parser.add_argument("--classic-json", type=Path)
    parser.add_argument("--rulesets-json", type=Path)
    parser.add_argument("--expected-head")
    args = parser.parse_args(argv)

    result = evaluate_repository_authority(
        _read_json(args.branch_json),
        classic_protection=_read_json(args.classic_json) if args.classic_json else None,
        rulesets=_read_json(args.rulesets_json) if args.rulesets_json else None,
        expected_head=args.expected_head,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
