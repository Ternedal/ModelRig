"""Pure, non-authorizing RSI improvement proposal primitives.

This module deliberately stops before DevelopmentTask.  It may normalize eval
failures and validate a model-authored improvement hypothesis, but it cannot
assign paths, commands, budgets or any other DevControl execution authority.

Importing the module performs no I/O, starts no threads and touches no network.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .contract import normalize_repo_path

BRIEF_SCHEMA = "kaliv-rsi-improvement-brief/v1"
PROPOSAL_SCHEMA = "kaliv-rsi-improvement-proposal/v1"
AGENT3_EVAL_SCHEMA = "kaliv-agent3-model-eval/v1"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROPOSAL_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_ALLOWED_PROPOSAL_FIELDS = {
    "schema",
    "proposal_id",
    "repository",
    "base_sha",
    "source_schema",
    "evidence_sha256",
    "finding_ids",
    "title",
    "problem",
    "hypothesis",
    "expected_gain",
    "implementation_strategy",
    "suggested_paths",
    "suggested_tests",
    "acceptance_criteria",
    "required_evals",
    "risk",
    "authority",
    "merge_authority",
}
_FORBIDDEN_AUTHORITY_FIELDS = {
    "allowed_paths",
    "protected_paths",
    "allowed_command_ids",
    "budget",
    "publisher_intent",
    "authorization",
    "activation",
}


class ImprovementProposalError(ValueError):
    """Improvement evidence or proposal is malformed or grants authority."""


class ProposalRisk(StrEnum):
    TRIVIAL = "trivial"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ImprovementProposalError(f"{name} must be an object")
    return value


def _string(value: Any, *, name: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise ImprovementProposalError(f"{name} must be a string")
    if not value or value.strip() != value or "\x00" in value:
        raise ImprovementProposalError(f"{name} is empty or not canonical")
    if len(value.encode("utf-8")) > maximum:
        raise ImprovementProposalError(f"{name} exceeds {maximum} UTF-8 bytes")
    return value


def _strings(
    value: Any,
    *,
    name: str,
    minimum: int = 1,
    maximum_items: int = 64,
    maximum_bytes: int = 1024,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ImprovementProposalError(f"{name} must be an array")
    if not minimum <= len(value) <= maximum_items:
        raise ImprovementProposalError(
            f"{name} must contain {minimum}..{maximum_items} items"
        )
    result = tuple(
        _string(item, name=f"{name}[{index}]", maximum=maximum_bytes)
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise ImprovementProposalError(f"{name} must not contain duplicates")
    return result


def _repository(value: Any) -> str:
    repository = _string(value, name="repository", maximum=200)
    parts = repository.split("/")
    if len(parts) != 2 or not all(part and part.strip() == part for part in parts):
        raise ImprovementProposalError("repository must be owner/name")
    return repository


def _base_sha(value: Any) -> str:
    sha = _string(value, name="base_sha", maximum=40)
    if _SHA40.fullmatch(sha) is None:
        raise ImprovementProposalError("base_sha must be a lowercase 40-hex SHA")
    return sha


def _digest(value: Any, *, name: str = "evidence_sha256") -> str:
    digest = _string(value, name=name, maximum=64)
    if _SHA256.fullmatch(digest) is None:
        raise ImprovementProposalError(f"{name} must be a lowercase SHA-256")
    return digest


def canonical_json(value: Any) -> str:
    """Canonical JSON used for evidence binding and deterministic artifacts."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ImprovementProposalError("value is not canonical JSON data") from exc


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _number(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImprovementProposalError(f"{name} must be numeric")
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise ImprovementProposalError(f"{name} must be finite")
    return number


def _optional_number(value: Any, *, name: str) -> float | None:
    if value is None:
        return None
    return _number(value, name=name)


def build_agent3_improvement_brief(
    report: Mapping[str, Any],
    *,
    repository: str,
    base_sha: str,
) -> dict[str, Any]:
    """Normalize only observed Agent 3 model-eval failures into an RSI brief.

    A clean report produces a valid brief with an empty ``findings`` array.  It
    does not invent work merely because the planner was asked to look.
    """

    data = _mapping(report, name="report")
    if data.get("schema") != AGENT3_EVAL_SCHEMA:
        raise ImprovementProposalError(
            f"report schema must be {AGENT3_EVAL_SCHEMA}"
        )
    repo = _repository(repository)
    sha = _base_sha(base_sha)
    evidence_sha256 = canonical_sha256(data)

    summary = _mapping(data.get("summary"), name="report.summary")
    results = data.get("results")
    if not isinstance(results, list):
        raise ImprovementProposalError("report.results must be an array")

    normalized_summary = {
        "tasks": int(_number(summary.get("tasks"), name="summary.tasks")),
        "requests_completed": int(
            _number(summary.get("requests_completed"), name="summary.requests_completed")
        ),
        "request_errors": int(
            _number(summary.get("request_errors"), name="summary.request_errors")
        ),
        "exact_matches": int(
            _number(summary.get("exact_matches"), name="summary.exact_matches")
        ),
        "exact_match_rate": _number(
            summary.get("exact_match_rate"), name="summary.exact_match_rate"
        ),
        "discipline_rate": _number(
            summary.get("discipline_rate"), name="summary.discipline_rate"
        ),
    }

    findings: list[dict[str, Any]] = []
    for index, raw in enumerate(results):
        item = _mapping(raw, name=f"report.results[{index}]")
        task_id = _string(item.get("task_id"), name=f"results[{index}].task_id", maximum=128)
        category = _string(item.get("category"), name=f"results[{index}].category", maximum=128)
        repetition_raw = item.get("repetition")
        if isinstance(repetition_raw, bool) or not isinstance(repetition_raw, int) or repetition_raw < 1:
            raise ImprovementProposalError(
                f"results[{index}].repetition must be a positive integer"
            )
        request_error = item.get("request_error")
        if request_error is not None:
            request_error = _string(
                request_error,
                name=f"results[{index}].request_error",
                maximum=2048,
            )

        evaluation = _mapping(
            item.get("evaluation"), name=f"results[{index}].evaluation"
        )
        exact_match = evaluation.get("exact_match")
        discipline_pass = evaluation.get("discipline_pass")
        if not isinstance(exact_match, bool) or not isinstance(discipline_pass, bool):
            raise ImprovementProposalError(
                f"results[{index}].evaluation booleans are missing"
            )

        observed_gap = request_error is not None or not exact_match or not discipline_pass
        if not observed_gap:
            continue

        finding_text = evaluation.get("findings", [])
        if not isinstance(finding_text, list) or not all(
            isinstance(value, str) and value and value.strip() == value
            for value in finding_text
        ):
            raise ImprovementProposalError(
                f"results[{index}].evaluation.findings must be a canonical string array"
            )

        normalized = {
            "task_id": task_id,
            "category": category,
            "repetition": repetition_raw,
            "request_error": request_error,
            "exact_match": exact_match,
            "discipline_pass": discipline_pass,
            "tool_score": _optional_number(
                evaluation.get("tool_score"), name=f"results[{index}].evaluation.tool_score"
            ),
            "risk_score": _optional_number(
                evaluation.get("risk_score"), name=f"results[{index}].evaluation.risk_score"
            ),
            "args_score": _optional_number(
                evaluation.get("args_score"), name=f"results[{index}].evaluation.args_score"
            ),
            "findings": list(finding_text),
        }
        finding_id = "A3-" + canonical_sha256(normalized)[:16].upper()
        findings.append({"finding_id": finding_id, **normalized})

    findings.sort(key=lambda item: (item["task_id"], item["repetition"], item["finding_id"]))
    return {
        "schema": BRIEF_SCHEMA,
        "source_schema": AGENT3_EVAL_SCHEMA,
        "repository": repo,
        "base_sha": sha,
        "evidence_sha256": evidence_sha256,
        "summary": normalized_summary,
        "findings": findings,
        "proposal_required": bool(findings),
        "authority": "evidence-only",
    }


def render_improvement_prompt(brief: Mapping[str, Any]) -> str:
    """Render a deterministic prompt for a model that may propose, never authorize."""

    data = _mapping(brief, name="brief")
    if data.get("schema") != BRIEF_SCHEMA:
        raise ImprovementProposalError(f"brief schema must be {BRIEF_SCHEMA}")
    _repository(data.get("repository"))
    _base_sha(data.get("base_sha"))
    _digest(data.get("evidence_sha256"))
    findings = data.get("findings")
    if not isinstance(findings, list):
        raise ImprovementProposalError("brief.findings must be an array")
    if not findings:
        raise ImprovementProposalError("clean evidence does not require a proposal")

    contract = {
        "schema": PROPOSAL_SCHEMA,
        "proposal_id": "RSI_EXAMPLE_001",
        "repository": data["repository"],
        "base_sha": data["base_sha"],
        "source_schema": data["source_schema"],
        "evidence_sha256": data["evidence_sha256"],
        "finding_ids": [item.get("finding_id") for item in findings],
        "title": "kort konkret titel",
        "problem": "observeret problem bundet til findings",
        "hypothesis": "falsificerbar årsagshypotese",
        "expected_gain": "målbar forventet forbedring",
        "implementation_strategy": "kort forslag, ikke execution authority",
        "suggested_paths": ["worker/app/agent3/example.py"],
        "suggested_tests": ["python tests/example.py"],
        "acceptance_criteria": ["konkret målbar acceptkriterie"],
        "required_evals": ["kaliv-agent3-model-eval/v1"],
        "risk": "medium",
        "authority": "proposal-only",
        "merge_authority": "human",
    }
    return (
        "Du er ModelRigs RSI Improvement Planner. Analyser kun den vedlagte, "
        "SHA-bundne eval-evidens og foreslå én afgrænset forbedringshypotese.\n\n"
        "REGLER:\n"
        "- Returner kun ét JSON-objekt.\n"
        "- Output skal følge kaliv-rsi-improvement-proposal/v1.\n"
        "- Du må foreslå suggested_paths/tests, men du må aldrig udstede "
        "allowed_paths, allowed_command_ids, budget, authorization, publisher "
        "intent, merge, release, deploy eller activation authority.\n"
        "- Hypotesen skal kunne falsificeres af required_evals.\n"
        "- Problem og acceptance criteria skal kunne spores til finding_ids.\n"
        "- Hvis evidensen ikke understøtter en konkret forbedring, må du ikke "
        "opfinde en.\n\n"
        "OUTPUT-SKELET:\n"
        + json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n\nEVIDENS-BRIEF:\n"
        + json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    )


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    proposal_id: str
    repository: str
    base_sha: str
    source_schema: str
    evidence_sha256: str
    finding_ids: tuple[str, ...]
    title: str
    problem: str
    hypothesis: str
    expected_gain: str
    implementation_strategy: str
    suggested_paths: tuple[str, ...]
    suggested_tests: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    required_evals: tuple[str, ...]
    risk: ProposalRisk
    authority: str = "proposal-only"
    merge_authority: str = "human"
    schema: str = PROPOSAL_SCHEMA

    @classmethod
    def from_mapping(cls, value: Any) -> "ImprovementProposal":
        data = _mapping(value, name="proposal")
        forbidden = sorted(set(data).intersection(_FORBIDDEN_AUTHORITY_FIELDS))
        if forbidden:
            raise ImprovementProposalError(
                "proposal contains authority fields: " + ", ".join(forbidden)
            )
        unknown = sorted(set(data) - _ALLOWED_PROPOSAL_FIELDS)
        missing = sorted(_ALLOWED_PROPOSAL_FIELDS - set(data))
        if unknown or missing:
            raise ImprovementProposalError(
                "proposal fields mismatch"
                + (f"; unknown={unknown}" if unknown else "")
                + (f"; missing={missing}" if missing else "")
            )
        if data["schema"] != PROPOSAL_SCHEMA:
            raise ImprovementProposalError(f"schema must be {PROPOSAL_SCHEMA}")
        proposal_id = _string(data["proposal_id"], name="proposal_id", maximum=64)
        if _PROPOSAL_ID.fullmatch(proposal_id) is None:
            raise ImprovementProposalError("proposal_id has invalid syntax")
        source_schema = _string(data["source_schema"], name="source_schema", maximum=128)
        finding_ids = _strings(data["finding_ids"], name="finding_ids", maximum_items=128, maximum_bytes=128)
        if data["authority"] != "proposal-only":
            raise ImprovementProposalError("authority must remain proposal-only")
        if data["merge_authority"] != "human":
            raise ImprovementProposalError("merge_authority must remain human")
        try:
            risk = ProposalRisk(data["risk"])
        except (TypeError, ValueError) as exc:
            raise ImprovementProposalError("risk is unsupported") from exc

        suggested_paths = tuple(
            normalize_repo_path(path, name=f"suggested_paths[{index}]")
            for index, path in enumerate(
                _strings(data["suggested_paths"], name="suggested_paths")
            )
        )
        return cls(
            proposal_id=proposal_id,
            repository=_repository(data["repository"]),
            base_sha=_base_sha(data["base_sha"]),
            source_schema=source_schema,
            evidence_sha256=_digest(data["evidence_sha256"]),
            finding_ids=finding_ids,
            title=_string(data["title"], name="title", maximum=256),
            problem=_string(data["problem"], name="problem"),
            hypothesis=_string(data["hypothesis"], name="hypothesis"),
            expected_gain=_string(data["expected_gain"], name="expected_gain"),
            implementation_strategy=_string(
                data["implementation_strategy"], name="implementation_strategy"
            ),
            suggested_paths=suggested_paths,
            suggested_tests=_strings(data["suggested_tests"], name="suggested_tests"),
            acceptance_criteria=_strings(
                data["acceptance_criteria"], name="acceptance_criteria"
            ),
            required_evals=_strings(data["required_evals"], name="required_evals"),
            risk=risk,
        )

    @classmethod
    def from_json(cls, text: str) -> "ImprovementProposal":
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ImprovementProposalError("proposal JSON is invalid") from exc
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "proposal_id": self.proposal_id,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "source_schema": self.source_schema,
            "evidence_sha256": self.evidence_sha256,
            "finding_ids": list(self.finding_ids),
            "title": self.title,
            "problem": self.problem,
            "hypothesis": self.hypothesis,
            "expected_gain": self.expected_gain,
            "implementation_strategy": self.implementation_strategy,
            "suggested_paths": list(self.suggested_paths),
            "suggested_tests": list(self.suggested_tests),
            "acceptance_criteria": list(self.acceptance_criteria),
            "required_evals": list(self.required_evals),
            "risk": self.risk.value,
            "authority": self.authority,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())
