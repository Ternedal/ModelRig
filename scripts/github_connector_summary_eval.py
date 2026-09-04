#!/usr/bin/env python3
"""Deterministic T-036 eval for grounded GitHub issue/PR/CI summaries.

The model-facing part of this eval is deliberately structured. A candidate may
name exactly one source object and make scalar claims by path. The harness
checks every identity field and claim against the already privacy-minimized
``kaliv-github-tool-result/v1`` payload. Only after that verification does the
trusted renderer produce prose.

That split makes the acceptance criterion testable without a second model as
judge: an invented issue/PR/run id, revision, state, conclusion or SHA is a
hard mismatch, not a subjective hallucination score.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EVAL_SET_SCHEMA = "kaliv-github-summary-eval-set/v1"
CANDIDATES_SCHEMA = "kaliv-github-summary-candidates/v1"
CANDIDATE_SCHEMA = "kaliv-github-summary-candidate/v1"
TOOL_RESULT_SCHEMA = "kaliv-github-tool-result/v1"
_ALLOWED_OPERATIONS = {"issue", "pull_request", "workflow_run"}
_PATH = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")


class GitHubSummaryEvalError(ValueError):
    pass


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GitHubSummaryEvalError(f"{name} must be an object")
    return value


def _text(value: Any, name: str, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise GitHubSummaryEvalError(f"{name} must be a string")
    if not value or len(value) > maximum:
        raise GitHubSummaryEvalError(f"{name} must contain 1..{maximum} characters")
    return value


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise GitHubSummaryEvalError("candidate claim must be JSON-serializable") from exc


def _exact_equal(left: Any, right: Any) -> bool:
    # Canonical JSON distinguishes booleans from integers and ignores dict key
    # order, which is exactly the comparison semantics needed for model claims.
    return _canonical(left) == _canonical(right)


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _path_value(document: dict[str, Any], path: str) -> Any:
    if not isinstance(path, str) or not _PATH.fullmatch(path):
        raise GitHubSummaryEvalError("claim path must be a dotted object-key path")
    current: Any = document
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise GitHubSummaryEvalError(f"claim path is absent from source projection: {path}")
        current = current[segment]
    if not _scalar(current):
        raise GitHubSummaryEvalError(f"claim path must resolve to a scalar source value: {path}")
    return current


def _validate_tool_result(value: Any, *, expected_operation: str | None = None) -> dict[str, Any]:
    result = _object(value, "tool_result")
    if result.get("schema") != TOOL_RESULT_SCHEMA:
        raise GitHubSummaryEvalError("tool_result schema is unsupported")
    if result.get("connector") != "github":
        raise GitHubSummaryEvalError("tool_result connector must be github")
    repository = _text(result.get("repository"), "tool_result.repository", 220)
    operation = result.get("operation")
    if operation not in _ALLOWED_OPERATIONS:
        raise GitHubSummaryEvalError("eval covers only issue, pull_request and workflow_run")
    if expected_operation is not None and operation != expected_operation:
        raise GitHubSummaryEvalError("case operation contradicts tool_result")
    object_id = _text(result.get("object_id"), "tool_result.object_id", 160)
    source = _object(result.get("source"), "tool_result.source")
    document = _object(result.get("document"), "tool_result.document")

    if source.get("connector") != "github":
        raise GitHubSummaryEvalError("source connector must be github")
    if source.get("repository") != repository:
        raise GitHubSummaryEvalError("source repository contradicts tool_result")
    if source.get("object_type") != operation:
        raise GitHubSummaryEvalError("source object_type contradicts tool_result")
    if source.get("object_id") != object_id:
        raise GitHubSummaryEvalError("source object_id contradicts tool_result")
    _text(source.get("revision"), "source.revision", 180)
    _text(source.get("retrieved_at"), "source.retrieved_at", 80)
    if source.get("production_activation") is not False:
        raise GitHubSummaryEvalError("source production_activation must remain false")

    if operation in {"issue", "pull_request"}:
        number = document.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or str(number) != object_id:
            raise GitHubSummaryEvalError("issue/PR document number contradicts requested object_id")
    else:
        run_id = document.get("id")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or str(run_id) != object_id:
            raise GitHubSummaryEvalError("workflow document id contradicts requested object_id")
    return result


def _validate_case(value: Any) -> dict[str, Any]:
    case = _object(value, "case")
    if set(case) != {"id", "operation", "tool_result", "required_claims"}:
        raise GitHubSummaryEvalError("case keys are not the frozen eval contract")
    case_id = _text(case.get("id"), "case.id", 100)
    operation = case.get("operation")
    if operation not in _ALLOWED_OPERATIONS:
        raise GitHubSummaryEvalError(f"case {case_id}: unsupported operation")
    result = _validate_tool_result(case.get("tool_result"), expected_operation=operation)
    required = case.get("required_claims")
    if not isinstance(required, list) or not required:
        raise GitHubSummaryEvalError(f"case {case_id}: required_claims must be a non-empty list")
    seen: set[str] = set()
    for path in required:
        if not isinstance(path, str) or path in seen:
            raise GitHubSummaryEvalError(f"case {case_id}: required_claims must be unique strings")
        seen.add(path)
        _path_value(result["document"], path)
    return case


def load_cases(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GitHubSummaryEvalError(f"cannot load eval set: {exc}") from exc
    root = _object(payload, "eval set")
    if root.get("schema") != EVAL_SET_SCHEMA:
        raise GitHubSummaryEvalError("eval set schema is unsupported")
    cases = root.get("cases")
    if not isinstance(cases, list) or not cases:
        raise GitHubSummaryEvalError("eval set must contain cases")
    out: dict[str, dict[str, Any]] = {}
    operations: set[str] = set()
    for raw in cases:
        case = _validate_case(raw)
        case_id = case["id"]
        if case_id in out:
            raise GitHubSummaryEvalError(f"duplicate eval case id: {case_id}")
        out[case_id] = case
        operations.add(case["operation"])
    if operations != _ALLOWED_OPERATIONS:
        raise GitHubSummaryEvalError("frozen eval set must cover issue, pull_request and workflow_run")
    return out


def source_identity(tool_result: dict[str, Any]) -> dict[str, str]:
    result = _validate_tool_result(tool_result)
    source = result["source"]
    return {
        "connector": "github",
        "repository": result["repository"],
        "operation": result["operation"],
        "object_id": result["object_id"],
        "revision": source["revision"],
    }


def evaluate_candidate(case: dict[str, Any], candidate: Any) -> dict[str, Any]:
    case = _validate_case(case)
    value = _object(candidate, "candidate")
    if set(value) != {"schema", "object", "claims"}:
        raise GitHubSummaryEvalError("candidate keys must be schema, object and claims")
    if value.get("schema") != CANDIDATE_SCHEMA:
        raise GitHubSummaryEvalError("candidate schema is unsupported")

    expected_identity = source_identity(case["tool_result"])
    identity = _object(value.get("object"), "candidate.object")
    if set(identity) != set(expected_identity):
        raise GitHubSummaryEvalError("candidate.object must contain the exact source identity fields")
    for key, expected in expected_identity.items():
        if identity.get(key) != expected:
            raise GitHubSummaryEvalError(f"invented or mismatched source identity: {key}")

    raw_claims = value.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise GitHubSummaryEvalError("candidate.claims must be a non-empty list")
    document = case["tool_result"]["document"]
    claims: dict[str, Any] = {}
    for raw in raw_claims:
        claim = _object(raw, "claim")
        if set(claim) != {"path", "value"}:
            raise GitHubSummaryEvalError("claim must contain exactly path + value")
        path = claim.get("path")
        if not isinstance(path, str) or path in claims:
            raise GitHubSummaryEvalError("claim paths must be unique strings")
        expected = _path_value(document, path)
        if not _exact_equal(claim.get("value"), expected):
            raise GitHubSummaryEvalError(f"invented or mismatched claim: {path}")
        claims[path] = claim.get("value")

    missing = [path for path in case["required_claims"] if path not in claims]
    if missing:
        raise GitHubSummaryEvalError("candidate omitted required grounded claims: " + ", ".join(missing))

    return {
        "case_id": case["id"],
        "operation": case["operation"],
        "passed": True,
        "source": expected_identity,
        "verified_claims": claims,
        "summary": render_verified_summary(case["operation"], expected_identity, claims),
    }


def render_verified_summary(
    operation: str,
    identity: dict[str, str],
    claims: dict[str, Any],
) -> str:
    """Render only values that already passed source-exact verification."""
    if operation == "issue":
        number = claims["number"]
        title = claims["title"]
        state = claims["state"]
        return f'Issue #{number} “{title}” er {state} i {identity["repository"]}.'
    if operation == "pull_request":
        number = claims["number"]
        title = claims["title"]
        state = claims["state"]
        draft = "draft" if claims["draft"] else "ikke draft"
        head = str(claims["head.sha"])
        return (
            f'PR #{number} “{title}” er {state} ({draft}) i {identity["repository"]}; '
            f'head {head}.'
        )
    if operation == "workflow_run":
        run_number = claims["run_number"]
        name = claims["name"]
        status = claims["status"]
        conclusion = claims["conclusion"]
        head = claims["head_sha"]
        return (
            f'CI-run #{run_number} “{name}” er {status} med conclusion {conclusion} '
            f'i {identity["repository"]}; head {head}.'
        )
    raise GitHubSummaryEvalError("unsupported summary operation")


def load_candidates(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GitHubSummaryEvalError(f"cannot load candidates: {exc}") from exc
    root = _object(payload, "candidates")
    if root.get("schema") != CANDIDATES_SCHEMA:
        raise GitHubSummaryEvalError("candidates schema is unsupported")
    candidates = root.get("candidates")
    if not isinstance(candidates, dict):
        raise GitHubSummaryEvalError("candidates must be an object keyed by case id")
    return candidates


def run_eval(cases: dict[str, dict[str, Any]], candidates: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(candidates) - set(cases))
    if unknown:
        raise GitHubSummaryEvalError("candidates contain unknown case ids: " + ", ".join(unknown))
    rows: list[dict[str, Any]] = []
    passed = 0
    for case_id, case in cases.items():
        if case_id not in candidates:
            rows.append({"case_id": case_id, "operation": case["operation"], "passed": False,
                         "error": "missing candidate"})
            continue
        try:
            row = evaluate_candidate(case, candidates[case_id])
        except GitHubSummaryEvalError as exc:
            rows.append({"case_id": case_id, "operation": case["operation"], "passed": False,
                         "error": str(exc)})
        else:
            rows.append(row)
            passed += 1
    return {
        "schema": "kaliv-github-summary-eval-report/v1",
        "cases": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "pass_rate": passed / len(cases),
        "results": rows,
        "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("eval/github_connector_summary_cases.json"))
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_eval(load_cases(args.cases), load_candidates(args.candidates))
    except GitHubSummaryEvalError as exc:
        print(f"github summary eval contract error: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
