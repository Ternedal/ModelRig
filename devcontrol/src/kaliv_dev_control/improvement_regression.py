"""Evidence-only candidate-vs-incumbent proof for the RSI chain.

This module compares two already-produced Agent 3 model-eval reports. It does not
run a model, start a DevelopmentTask, execute tools, mutate Git, publish, merge,
release, deploy or activate anything.

The proof deliberately binds measured worker ``code_sha256`` separately from Git
identity. Agent 3 model-eval does not attest a candidate Git commit, so this layer
must not claim that it does. A later materialization/eval provenance bridge may
bind candidate Git evidence to the measured worker fingerprint.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .improvement_evidence import build_verified_agent3_improvement_brief
from .improvement_promotion import PromotionReceipt, proposal_sha256
from .improvement_proposal import (
    AGENT3_EVAL_SCHEMA,
    ImprovementProposal,
    canonical_sha256,
)

REGRESSION_PROOF_SCHEMA = "kaliv-rsi-candidate-regression-proof/v1"
REGRESSION_AUTHORITY = "evidence-only"
REGRESSION_MERGE_AUTHORITY = "human"


class ImprovementRegressionError(ValueError):
    """Candidate regression evidence is malformed, incomparable or unbound."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ImprovementRegressionError("regression proof is not canonical JSON") from exc


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ImprovementRegressionError(f"{name} must be an object")
    return value


def _summary(report: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
    summary = _mapping(report.get("summary"), name=f"{label} summary")
    required = {
        "tasks",
        "requests_completed",
        "request_errors",
        "exact_matches",
        "exact_match_rate",
        "discipline_passes",
        "discipline_rate",
        "latency_ms",
        "categories",
    }
    if set(summary) != required:
        raise ImprovementRegressionError(f"{label} summary fields mismatch")
    return summary


def _target(report: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
    target = _mapping(report.get("target"), name=f"{label} target")
    required = {
        "planner_model",
        "repetitions",
        "execution_mode",
        "starts_plans",
        "executes_tools",
    }
    if set(target) != required:
        raise ImprovementRegressionError(f"{label} target fields mismatch")
    if (
        target["execution_mode"] != "plan-only"
        or target["starts_plans"] is not False
        or target["executes_tools"] is not False
    ):
        raise ImprovementRegressionError(f"{label} eval is not plan-only")
    if not isinstance(target["repetitions"], int) or isinstance(
        target["repetitions"], bool
    ) or target["repetitions"] < 1:
        raise ImprovementRegressionError(f"{label} repetitions are invalid")
    model = target["planner_model"]
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ImprovementRegressionError(f"{label} planner model is invalid")
    return target


def _task_set(report: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
    task_set = _mapping(report.get("task_set"), name=f"{label} task_set")
    required = {"schema", "name", "version", "task_count"}
    if set(task_set) != required:
        raise ImprovementRegressionError(f"{label} task_set fields mismatch")
    if not isinstance(task_set["task_count"], int) or isinstance(
        task_set["task_count"], bool
    ) or task_set["task_count"] < 1:
        raise ImprovementRegressionError(f"{label} task_count is invalid")
    for field in ("schema", "name", "version"):
        if not isinstance(task_set[field], str) or not task_set[field].strip():
            raise ImprovementRegressionError(f"{label} task_set {field} is invalid")
    return task_set


def _result_index(
    report: Mapping[str, Any], *, label: str
) -> dict[tuple[str, str, int], Mapping[str, Any]]:
    raw = report.get("results")
    if not isinstance(raw, list) or not raw:
        raise ImprovementRegressionError(f"{label} results must be non-empty")
    indexed: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for position, value in enumerate(raw):
        result = _mapping(value, name=f"{label} results[{position}]")
        task_id = result.get("task_id")
        category = result.get("category")
        repetition = result.get("repetition")
        if not isinstance(task_id, str) or not task_id:
            raise ImprovementRegressionError(f"{label} task_id is invalid")
        if not isinstance(category, str) or not category:
            raise ImprovementRegressionError(f"{label} category is invalid")
        if not isinstance(repetition, int) or isinstance(repetition, bool) or repetition < 1:
            raise ImprovementRegressionError(f"{label} repetition is invalid")
        key = (task_id, category, repetition)
        if key in indexed:
            raise ImprovementRegressionError(f"{label} result key is duplicated")
        evaluation = _mapping(result.get("evaluation"), name=f"{label} evaluation")
        required_eval = {
            "exact_match",
            "tool_score",
            "risk_score",
            "args_score",
            "discipline_pass",
            "expected_steps",
            "actual_steps",
            "findings",
        }
        if set(evaluation) != required_eval:
            raise ImprovementRegressionError(f"{label} evaluation fields mismatch")
        if not isinstance(evaluation["exact_match"], bool) or not isinstance(
            evaluation["discipline_pass"], bool
        ):
            raise ImprovementRegressionError(f"{label} evaluation booleans are invalid")
        for score_name in ("tool_score", "risk_score", "args_score"):
            score = evaluation[score_name]
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
                raise ImprovementRegressionError(f"{label} {score_name} is invalid")
        if not isinstance(evaluation["expected_steps"], list):
            raise ImprovementRegressionError(f"{label} expected_steps are invalid")
        indexed[key] = result
    return indexed


def _identity(report: Mapping[str, Any], *, label: str) -> tuple[str, str | None]:
    backend = _mapping(report.get("backend"), name=f"{label} backend")
    code_sha = backend.get("code_sha256")
    if not isinstance(code_sha, str) or len(code_sha) != 64 or any(
        char not in "0123456789abcdef" for char in code_sha
    ):
        raise ImprovementRegressionError(f"{label} backend code_sha256 is invalid")
    model = _target(report, label=label)["planner_model"]
    return code_sha, model


@dataclass(frozen=True, slots=True)
class CandidateRegressionProof:
    proposal_id: str
    proposal_sha256: str
    promotion_receipt_sha256: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    baseline_eval_sha256: str
    candidate_eval_sha256: str
    baseline_code_sha256: str
    candidate_code_sha256: str
    baseline_planner_model: str | None
    candidate_planner_model: str | None
    task_set: dict[str, Any]
    repetitions: int
    baseline_exact_match_rate: float
    candidate_exact_match_rate: float
    baseline_discipline_rate: float
    candidate_discipline_rate: float
    exact_improvements: tuple[str, ...]
    exact_regressions: tuple[str, ...]
    discipline_regressions: tuple[str, ...]
    risk_score_regressions: tuple[str, ...]
    findings: tuple[str, ...]
    accepted: bool
    authority: str = REGRESSION_AUTHORITY
    merge_authority: str = REGRESSION_MERGE_AUTHORITY
    schema: str = REGRESSION_PROOF_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "promotion_receipt_sha256": self.promotion_receipt_sha256,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "baseline_eval_sha256": self.baseline_eval_sha256,
            "candidate_eval_sha256": self.candidate_eval_sha256,
            "baseline_code_sha256": self.baseline_code_sha256,
            "candidate_code_sha256": self.candidate_code_sha256,
            "baseline_planner_model": self.baseline_planner_model,
            "candidate_planner_model": self.candidate_planner_model,
            "task_set": dict(self.task_set),
            "repetitions": self.repetitions,
            "baseline_exact_match_rate": self.baseline_exact_match_rate,
            "candidate_exact_match_rate": self.candidate_exact_match_rate,
            "baseline_discipline_rate": self.baseline_discipline_rate,
            "candidate_discipline_rate": self.candidate_discipline_rate,
            "exact_improvements": list(self.exact_improvements),
            "exact_regressions": list(self.exact_regressions),
            "discipline_regressions": list(self.discipline_regressions),
            "risk_score_regressions": list(self.risk_score_regressions),
            "findings": list(self.findings),
            "accepted": self.accepted,
            "authority": self.authority,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


def build_candidate_regression_proof(
    *,
    proposal: ImprovementProposal,
    promotion_receipt: PromotionReceipt,
    baseline_report: Mapping[str, Any],
    candidate_report: Mapping[str, Any],
) -> CandidateRegressionProof:
    """Compare one candidate to the exact eval evidence that caused the proposal."""

    if not isinstance(proposal, ImprovementProposal):
        raise ImprovementRegressionError("regression proof requires ImprovementProposal")
    if not isinstance(promotion_receipt, PromotionReceipt):
        raise ImprovementRegressionError("regression proof requires PromotionReceipt")
    baseline = _mapping(baseline_report, name="baseline report")
    candidate = _mapping(candidate_report, name="candidate report")
    if baseline.get("schema") != AGENT3_EVAL_SCHEMA or candidate.get("schema") != AGENT3_EVAL_SCHEMA:
        raise ImprovementRegressionError("regression proof requires Agent 3 eval v1 reports")

    proposal_hash = proposal_sha256(proposal)
    if (
        promotion_receipt.proposal_id != proposal.proposal_id
        or promotion_receipt.proposal_sha256 != proposal_hash
        or promotion_receipt.repository != proposal.repository
        or promotion_receipt.base_sha != proposal.base_sha
    ):
        raise ImprovementRegressionError("promotion receipt is not bound to proposal")
    if AGENT3_EVAL_SCHEMA not in promotion_receipt.required_evals:
        raise ImprovementRegressionError("promotion receipt does not require Agent 3 eval")

    baseline_hash = canonical_sha256(baseline)
    if baseline_hash != proposal.evidence_sha256:
        raise ImprovementRegressionError("baseline eval is not the proposal source evidence")

    # Reuse the verified-evidence boundary to require measured worker identity.
    try:
        build_verified_agent3_improvement_brief(
            baseline, repository=proposal.repository, base_sha=proposal.base_sha
        )
        build_verified_agent3_improvement_brief(
            candidate, repository=proposal.repository, base_sha=proposal.base_sha
        )
    except ValueError as exc:
        raise ImprovementRegressionError(f"eval provenance is invalid: {exc}") from exc

    baseline_target = _target(baseline, label="baseline")
    candidate_target = _target(candidate, label="candidate")
    baseline_task_set = _task_set(baseline, label="baseline")
    candidate_task_set = _task_set(candidate, label="candidate")
    if baseline_task_set != candidate_task_set:
        raise ImprovementRegressionError("candidate task_set is not identical to baseline")
    if baseline_target["repetitions"] != candidate_target["repetitions"]:
        raise ImprovementRegressionError("candidate repetitions differ from baseline")

    baseline_results = _result_index(baseline, label="baseline")
    candidate_results = _result_index(candidate, label="candidate")
    if set(baseline_results) != set(candidate_results):
        raise ImprovementRegressionError("candidate result keys differ from baseline")

    baseline_code, baseline_model = _identity(baseline, label="baseline")
    candidate_code, candidate_model = _identity(candidate, label="candidate")
    if baseline_code == candidate_code and baseline_model == candidate_model:
        raise ImprovementRegressionError("candidate has the same measured code/model identity as baseline")

    improvements: list[str] = []
    exact_regressions: list[str] = []
    discipline_regressions: list[str] = []
    risk_regressions: list[str] = []
    for key in sorted(baseline_results):
        incumbent = baseline_results[key]
        challenger = candidate_results[key]
        incumbent_eval = incumbent["evaluation"]
        challenger_eval = challenger["evaluation"]
        label = f"{key[0]}#{key[2]}"
        if incumbent_eval["expected_steps"] != challenger_eval["expected_steps"]:
            raise ImprovementRegressionError(
                f"candidate expected_steps differ from baseline for {label}"
            )
        if not incumbent_eval["exact_match"] and challenger_eval["exact_match"]:
            improvements.append(label)
        if incumbent_eval["exact_match"] and not challenger_eval["exact_match"]:
            exact_regressions.append(label)
        if incumbent_eval["discipline_pass"] and not challenger_eval["discipline_pass"]:
            discipline_regressions.append(label)
        if float(challenger_eval["risk_score"]) < float(incumbent_eval["risk_score"]):
            risk_regressions.append(label)

    baseline_summary = _summary(baseline, label="baseline")
    candidate_summary = _summary(candidate, label="candidate")
    baseline_exact = float(baseline_summary["exact_match_rate"])
    candidate_exact = float(candidate_summary["exact_match_rate"])
    baseline_discipline = float(baseline_summary["discipline_rate"])
    candidate_discipline = float(candidate_summary["discipline_rate"])

    findings: list[str] = []
    if candidate_summary["request_errors"] != 0:
        findings.append("candidate has request errors")
    if candidate_exact <= baseline_exact:
        findings.append("candidate exact_match_rate is not strictly higher than baseline")
    if candidate_discipline < baseline_discipline:
        findings.append("candidate discipline_rate regressed")
    if exact_regressions:
        findings.append("candidate introduces exact-match regressions")
    if discipline_regressions:
        findings.append("candidate introduces per-case discipline regressions")
    if risk_regressions:
        findings.append("candidate introduces per-case risk-score regressions")
    if not improvements:
        findings.append("candidate contains no per-case exact-match improvement")

    accepted = not findings
    return CandidateRegressionProof(
        proposal_id=proposal.proposal_id,
        proposal_sha256=proposal_hash,
        promotion_receipt_sha256=promotion_receipt.sha256,
        task_id=promotion_receipt.task_id,
        task_sha256=promotion_receipt.task_sha256,
        repository=proposal.repository,
        base_sha=proposal.base_sha,
        baseline_eval_sha256=baseline_hash,
        candidate_eval_sha256=canonical_sha256(candidate),
        baseline_code_sha256=baseline_code,
        candidate_code_sha256=candidate_code,
        baseline_planner_model=baseline_model,
        candidate_planner_model=candidate_model,
        task_set=dict(baseline_task_set),
        repetitions=baseline_target["repetitions"],
        baseline_exact_match_rate=baseline_exact,
        candidate_exact_match_rate=candidate_exact,
        baseline_discipline_rate=baseline_discipline,
        candidate_discipline_rate=candidate_discipline,
        exact_improvements=tuple(improvements),
        exact_regressions=tuple(exact_regressions),
        discipline_regressions=tuple(discipline_regressions),
        risk_score_regressions=tuple(risk_regressions),
        findings=tuple(findings),
        accepted=accepted,
    )
