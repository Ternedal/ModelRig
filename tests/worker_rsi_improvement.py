"""RSI proposal/promotion/regression tests outside the landed DC-L01–L14 set.

The RSI ADRs are still proposed, so these tests run through the repository's
ordinary worker_*.py CI surface rather than silently extending the fixed
DC-L01–L14 DevControl test-module inventory.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))

from kaliv_dev_control.asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
    authority_signing_message,
)
from kaliv_dev_control.improvement_binding import proposal_from_model_json
from kaliv_dev_control.improvement_evidence import (
    build_verified_agent3_improvement_brief,
)
from kaliv_dev_control.improvement_model import generate_bound_improvement_proposal
from kaliv_dev_control.improvement_promotion import (
    PROMOTION_AUTHORITY,
    PROMOTION_AUTHORIZATION_SCHEMA,
    PROMOTION_ISSUER_SYSTEM_ID,
    ImprovementPromotionError,
    PromotionAuthorization,
    promote_improvement_proposal,
    proposal_sha256,
)
from kaliv_dev_control.improvement_proposal import (
    AGENT3_EVAL_SCHEMA,
    ImprovementProposal,
    ImprovementProposalError,
    build_agent3_improvement_brief,
    canonical_sha256,
    render_improvement_prompt,
)
from kaliv_dev_control.improvement_regression import (
    REGRESSION_AUTHORITY,
    ImprovementRegressionError,
    build_candidate_regression_proof,
)

BASE_SHA = "a" * 40
CODE_SHA = "1" * 64
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_error(fragment: str, fn, message: str) -> None:
    try:
        fn()
    except (ImprovementProposalError, ImprovementPromotionError) as exc:
        check(fragment in str(exc), message)
    else:
        check(False, message)


def expect_regression_error(fragment: str, fn, message: str) -> None:
    try:
        fn()
    except ImprovementRegressionError as exc:
        check(fragment in str(exc), message)
    else:
        check(False, message)


def eval_report(*, exact: bool = False, discipline: bool = True, verified: bool = False) -> dict:
    findings = [] if exact else ["step 0: expected tool 'rig_status', got 'model_list'"]
    value = {
        "schema": AGENT3_EVAL_SCHEMA,
        "started_at": "2026-09-12T18:00:00+00:00",
        "finished_at": "2026-09-12T18:00:01+00:00",
        "summary": {
            "tasks": 1,
            "requests_completed": 1,
            "request_errors": 0,
            "exact_matches": 1 if exact else 0,
            "exact_match_rate": 1.0 if exact else 0.0,
            "discipline_passes": 1 if discipline else 0,
            "discipline_rate": 1.0 if discipline else 0.0,
            "latency_ms": {"min": 10.0, "mean": 10.0, "p50": 10.0, "p95": 10.0, "max": 10.0},
            "categories": {"read": {"total": 1, "exact": 1 if exact else 0}},
        },
        "results": [
            {
                "task_id": "read-rig-status",
                "category": "read",
                "repetition": 1,
                "latency_ms": 10.0,
                "plan_id_present": True,
                "request_error": None,
                "evaluation": {
                    "exact_match": exact,
                    "tool_score": 1.0 if exact else 0.0,
                    "risk_score": 1.0,
                    "args_score": 1.0,
                    "discipline_pass": discipline,
                    "expected_steps": [{"tool": "rig_status", "risk": "read", "args": {}}],
                    "actual_steps": [{"tool": "rig_status" if exact else "model_list", "risk": "read", "args": {}}],
                    "findings": findings,
                },
            }
        ],
    }
    if verified:
        value["backend"] = {
            "enabled": True,
            "experimental": True,
            "code_sha256": CODE_SHA,
            "version": "2.0.13",
        }
    return value


def regression_report(
    *,
    exact: bool,
    code_sha: str,
    model: str = "qwen3:14b",
    discipline: bool = True,
    risk_score: float = 1.0,
    request_errors: int = 0,
) -> dict:
    value = eval_report(exact=exact, discipline=discipline, verified=True)
    value["backend"]["code_sha256"] = code_sha
    value["target"] = {
        "planner_model": model,
        "repetitions": 1,
        "execution_mode": "plan-only",
        "starts_plans": False,
        "executes_tools": False,
    }
    value["task_set"] = {
        "schema": "kaliv-agent3-model-eval-task-set/v1",
        "name": "rsi-test",
        "version": "1",
        "task_count": 1,
    }
    value["summary"]["request_errors"] = request_errors
    value["results"][0]["evaluation"]["risk_score"] = risk_score
    return value


def brief(*, clean: bool = False) -> dict:
    return build_agent3_improvement_brief(
        eval_report(exact=clean),
        repository="Ternedal/ModelRig",
        base_sha=BASE_SHA,
    )


def proposal_data(source: dict) -> dict:
    return {
        "schema": "kaliv-rsi-improvement-proposal/v1",
        "proposal_id": "RSI_A3_001",
        "repository": source["repository"],
        "base_sha": source["base_sha"],
        "source_schema": source["source_schema"],
        "evidence_sha256": source["evidence_sha256"],
        "finding_ids": [source["findings"][0]["finding_id"]],
        "title": "Forbedr Agent 3 tool-valg",
        "problem": "Agent 3 vælger model_list i en rig_status-case.",
        "hypothesis": "Plannerens tool-semantik adskiller ikke status og modelliste tydeligt nok.",
        "expected_gain": "Exact-match for casen går fra 0 til 1 uden fald i discipline rate.",
        "implementation_strategy": "Præciser tool-beskrivelser og tilføj regressionseksempel.",
        "suggested_paths": ["worker/app/agent3/planner.py", "eval/agent3_model_tasks.json"],
        "suggested_tests": ["python scripts/agent3_model_eval.py --planner-model <candidate>"],
        "acceptance_criteria": ["read-rig-status er exact-match i tre gentagelser"],
        "required_evals": [AGENT3_EVAL_SCHEMA],
        "risk": "medium",
        "authority": "proposal-only",
        "merge_authority": "human",
    }


def promotion_authorization_data(proposal: ImprovementProposal) -> dict:
    return {
        "schema": PROMOTION_AUTHORIZATION_SCHEMA,
        "proposal_id": proposal.proposal_id,
        "proposal_sha256": proposal_sha256(proposal),
        "repository": proposal.repository,
        "base_sha": proposal.base_sha,
        "task": {
            "schema": "kaliv-development-task/v1",
            "task_id": "RSI_TASK_001",
            "repository": proposal.repository,
            "base_sha": proposal.base_sha,
            "goal": "Forbedr Agent 3 tool-valg og bevis regressionen.",
            "acceptance_criteria": list(proposal.acceptance_criteria) + [
                "den eksisterende fulde Python-suite forbliver grøn"
            ],
            "risk": "medium",
            "allowed_paths": ["worker/app/agent3/planner.py"],
            "protected_paths": [".github/**", "devcontrol/**"],
            "allowed_command_ids": ["python.tests"],
            "required_tests": [
                "python tests/worker_agent3_planner.py",
                "python scripts/agent3_model_eval.py --planner-model <candidate>",
            ],
            "budget": {
                "max_changed_files": 4,
                "max_added_lines": 500,
                "max_deleted_lines": 500,
                "max_attempts": 2,
                "max_runtime_seconds": 1800,
                "max_output_bytes": 1000000,
            },
            "merge_authority": "human",
        },
        "required_evals": list(proposal.required_evals),
        "authority": PROMOTION_AUTHORITY,
    }


def signed_promotion(
    authorization: PromotionAuthorization,
    *,
    issuer_system_id: str = PROMOTION_ISSUER_SYSTEM_ID,
):
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    policy_hash = asymmetric_authority_key_custody_policy_sha256()
    key = TrustedEd25519AuthorityKey(
        key_id="rsi-human-test-key",
        issuer_actor_id="anders.test",
        issuer_system_id=issuer_system_id,
        public_key_hex=public_hex,
        valid_from_utc="2026-09-12T00:00:00Z",
        valid_until_utc="2026-09-13T00:00:00Z",
        keyring_epoch=1,
        custody_policy_sha256=policy_hash,
    )
    payload = authorization.canonical_json().encode("utf-8")
    message = authority_signing_message(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=key.custody_policy_sha256,
        payload=payload,
    )
    signature = DetachedEd25519AuthoritySignature(
        key_id=key.key_id,
        issuer_actor_id=key.issuer_actor_id,
        issuer_system_id=key.issuer_system_id,
        keyring_epoch=key.keyring_epoch,
        custody_policy_sha256=key.custody_policy_sha256,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private.sign(message).hex(),
        signed_at_utc="2026-09-12T19:00:00Z",
    )
    verifier = Ed25519AuthorityVerifier(
        {key.key_id: key}, minimum_keyring_epoch=1
    )
    return signature, verifier


# Deterministic failure extraction and clean-evidence stop.
source_report = eval_report()
first = brief()
second = build_agent3_improvement_brief(
    copy.deepcopy(source_report), repository="Ternedal/ModelRig", base_sha=BASE_SHA
)
check(first == second, "samme eval giver byte-stabilt semantisk brief")
check(first["proposal_required"] is True and len(first["findings"]) == 1,
      "observeret Agent 3-gap kræver præcis et evidens-finding")
check(first["evidence_sha256"] == canonical_sha256(source_report),
      "briefet er bundet til canonical SHA-256 af evalrapporten")
clean = brief(clean=True)
check(clean["proposal_required"] is False and clean["findings"] == [],
      "ren eval opfinder ikke forbedringsarbejde")
expect_error("does not require a proposal", lambda: render_improvement_prompt(clean),
             "ren evidens må ikke generere et modelprompt")

prompt = render_improvement_prompt(first)
check("proposal-only" in prompt and "allowed_paths" in prompt and "må aldrig udstede" in prompt,
      "modelpromptet forbyder execution authority eksplicit")

# Strict proposal contract.
proposal = ImprovementProposal.from_mapping(proposal_data(first))
check(proposal.authority == "proposal-only" and proposal.merge_authority == "human",
      "gyldigt proposal forbliver ikke-autoriserende og human-merged")
check(ImprovementProposal.from_json(proposal.canonical_json()).canonical_json() == proposal.canonical_json(),
      "proposal canonical JSON roundtripper deterministisk")

raw = proposal_data(first)
raw["allowed_paths"] = ["worker/**"]
expect_error("authority fields", lambda: ImprovementProposal.from_mapping(raw),
             "modellen kan ikke tildele allowed_paths")
raw = proposal_data(first)
raw["confidence"] = 1.0
expect_error("unknown", lambda: ImprovementProposal.from_mapping(raw),
             "ukendte proposal-felter fejler lukket")
raw = proposal_data(first)
raw["merge_authority"] = "model"
expect_error("must remain human", lambda: ImprovementProposal.from_mapping(raw),
             "modellen kan ikke selvpromovere merge authority")
raw = proposal_data(first)
raw["base_sha"] = "a" * 39
expect_error("40-hex", lambda: ImprovementProposal.from_mapping(raw),
             "forkortet base SHA afvises")

# Binding back to exact evidence.
bound = proposal_from_model_json(json.dumps(proposal_data(first), ensure_ascii=False), brief=first)
check(bound.evidence_sha256 == first["evidence_sha256"],
      "model-JSON bindes tilbage til præcis evidence digest")
raw = proposal_data(first)
raw["base_sha"] = "c" * 40
expect_error("base_sha is not bound", lambda: proposal_from_model_json(json.dumps(raw), brief=first),
             "modellen kan ikke skifte base SHA")
raw = proposal_data(first)
raw["finding_ids"] = ["A3-NOT-IN-BRIEF"]
expect_error("absent from the supplied brief", lambda: proposal_from_model_json(json.dumps(raw), brief=first),
             "modellen kan ikke opfinde finding IDs")
raw = proposal_data(first)
raw["required_evals"] = ["some-other-eval/v1"]
expect_error("source eval schema", lambda: proposal_from_model_json(json.dumps(raw), brief=first),
             "source-evalen skal være med i regression proof")

# Measured code provenance stays separate from repository Git authority.
verified_report = eval_report(verified=True)
verified = build_verified_agent3_improvement_brief(
    verified_report, repository="Ternedal/ModelRig", base_sha=BASE_SHA
)
check(verified["source_code_sha256"] == CODE_SHA and verified["source_version"] == "2.0.13",
      "målt worker code_sha256/version eksponeres i briefet")
check(verified["base_sha_provenance"] == "repository-authority-external-to-eval",
      "Git base SHA hævdes ikke at komme fra Agent 3-evalen")
missing_code = eval_report(verified=True)
missing_code["backend"].pop("code_sha256")
expect_error(
    "code_sha256",
    lambda: build_verified_agent3_improvement_brief(
        missing_code, repository="Ternedal/ModelRig", base_sha=BASE_SHA
    ),
    "eval uden målt code_sha256 afvises fail-closed",
)

# One-shot model behavior: one call, no retry, no call for clean evidence.
async def model_contracts() -> None:
    calls: list[tuple[list[dict[str, str]], str]] = []

    async def good_chat(messages: list[dict[str, str]], model: str) -> str:
        calls.append((messages, model))
        return json.dumps(proposal_data(first), ensure_ascii=False)

    result = await generate_bound_improvement_proposal(
        first, model="qwen3:14b", chat=good_chat
    )
    check(len(calls) == 1 and result.proposal.authority == "proposal-only",
          "one-shot modelleringsleddet kalder modellen præcis én gang")
    check(bool(result.raw_response_sha256) and len(result.raw_response_sha256) == 64,
          "rå modelrespons får sin egen SHA-256")

    bad_calls = 0

    async def bad_chat(_messages: list[dict[str, str]], _model: str) -> str:
        nonlocal bad_calls
        bad_calls += 1
        value = proposal_data(first)
        value["evidence_sha256"] = "e" * 64
        return json.dumps(value)

    try:
        await generate_bound_improvement_proposal(first, model="qwen3:14b", chat=bad_chat)
    except ImprovementProposalError as exc:
        check("evidence_sha256 is not bound" in str(exc) and bad_calls == 1,
              "forkert modelevidens afvises uden automatisk retry")
    else:
        check(False, "forkert modelevidens afvises uden automatisk retry")

    clean_calls = 0

    async def should_not_run(_messages: list[dict[str, str]], _model: str) -> str:
        nonlocal clean_calls
        clean_calls += 1
        return "{}"

    try:
        await generate_bound_improvement_proposal(clean, model="qwen3:14b", chat=should_not_run)
    except ImprovementProposalError as exc:
        check("does not require a proposal" in str(exc) and clean_calls == 0,
              "ren eval kalder aldrig modellen")
    else:
        check(False, "ren eval kalder aldrig modellen")


asyncio.run(model_contracts())

# Signed proposal -> DevelopmentTask promotion boundary.
promotion_proposal = ImprovementProposal.from_mapping(proposal_data(first))
authorization = PromotionAuthorization.from_mapping(
    promotion_authorization_data(promotion_proposal)
)
signature, verifier = signed_promotion(authorization)
task, receipt = promote_improvement_proposal(
    proposal=promotion_proposal,
    authorization=authorization,
    signature=signature,
    verifier=verifier,
    verified_at_utc="2026-09-12T19:01:00Z",
)
check(
    task.allowed_paths == ("worker/app/agent3/planner.py",)
    and task.allowed_paths != promotion_proposal.suggested_paths,
    "execution scope kommer kun fra den signerede authorization, ikke proposal suggestions",
)
check(
    receipt.proposal_sha256 == proposal_sha256(promotion_proposal)
    and receipt.authorization_sha256 == authorization.sha256
    and receipt.task_id == task.task_id,
    "promotion receipt binder proposal, authorization og DevelopmentTask",
)
check(
    receipt.reviewer_actor_id == "anders.test"
    and receipt.issuer_system_id == PROMOTION_ISSUER_SYSTEM_ID,
    "promotion receipt bevarer den verificerede eksterne reviewer-identitet",
)

# Proposal binding cannot be swapped after human authorization.
wrong = promotion_authorization_data(promotion_proposal)
wrong["proposal_sha256"] = "e" * 64
wrong_auth = PromotionAuthorization.from_mapping(wrong)
wrong_sig, wrong_verifier = signed_promotion(wrong_auth)
expect_error(
    "proposal_sha256 is not bound",
    lambda: promote_improvement_proposal(
        proposal=promotion_proposal,
        authorization=wrong_auth,
        signature=wrong_sig,
        verifier=wrong_verifier,
        verified_at_utc="2026-09-12T19:01:00Z",
    ),
    "en signer kan ikke autorisere et andet proposal-digest end det aktuelle proposal",
)

# Required eval proof and proposal acceptance criteria survive promotion.
wrong = promotion_authorization_data(promotion_proposal)
wrong["required_evals"] = ["some-other-eval/v1"]
wrong_auth = PromotionAuthorization.from_mapping(wrong)
wrong_sig, wrong_verifier = signed_promotion(wrong_auth)
expect_error(
    "required_evals exactly",
    lambda: promote_improvement_proposal(
        proposal=promotion_proposal,
        authorization=wrong_auth,
        signature=wrong_sig,
        verifier=wrong_verifier,
        verified_at_utc="2026-09-12T19:01:00Z",
    ),
    "human promotion kan ikke droppe proposalets krævede regression-eval",
)
wrong = promotion_authorization_data(promotion_proposal)
wrong["task"]["acceptance_criteria"] = ["kun en ny, løs acceptregel"]
wrong_auth = PromotionAuthorization.from_mapping(wrong)
wrong_sig, wrong_verifier = signed_promotion(wrong_auth)
expect_error(
    "dropped proposal acceptance criteria",
    lambda: promote_improvement_proposal(
        proposal=promotion_proposal,
        authorization=wrong_auth,
        signature=wrong_sig,
        verifier=wrong_verifier,
        verified_at_utc="2026-09-12T19:01:00Z",
    ),
    "promotion kan ikke fjerne modellens evidensbundne acceptance criteria",
)

# Promotion may raise risk, but never silently lower it.
wrong = promotion_authorization_data(promotion_proposal)
wrong["task"]["risk"] = "low"
wrong_auth = PromotionAuthorization.from_mapping(wrong)
wrong_sig, wrong_verifier = signed_promotion(wrong_auth)
expect_error(
    "may not silently downgrade",
    lambda: promote_improvement_proposal(
        proposal=promotion_proposal,
        authorization=wrong_auth,
        signature=wrong_sig,
        verifier=wrong_verifier,
        verified_at_utc="2026-09-12T19:01:00Z",
    ),
    "promotion kan ikke nedklassificere proposalets risiko",
)

# A signature from another authority system is not an RSI human approval.
foreign_sig, foreign_verifier = signed_promotion(
    authorization, issuer_system_id="some-other-authority"
)
expect_error(
    "human-review authority system",
    lambda: promote_improvement_proposal(
        proposal=promotion_proposal,
        authorization=authorization,
        signature=foreign_sig,
        verifier=foreign_verifier,
        verified_at_utc="2026-09-12T19:01:00Z",
    ),
    "en gyldig Ed25519-signatur fra et andet authority-system giver ingen RSI-promotion",
)

# Authorization bytes are signature-bound: post-signature authority changes fail.
tampered = promotion_authorization_data(promotion_proposal)
tampered["task"]["allowed_paths"] = ["worker/app/agent3/planner.py", "backend/**"]
tampered_auth = PromotionAuthorization.from_mapping(tampered)
expect_error(
    "signature is not trusted",
    lambda: promote_improvement_proposal(
        proposal=promotion_proposal,
        authorization=tampered_auth,
        signature=signature,
        verifier=verifier,
        verified_at_utc="2026-09-12T19:01:00Z",
    ),
    "scope kan ikke udvides efter human-signaturen er lavet",
)

# Candidate-vs-incumbent proof is bound to the exact proposal evidence and promotion receipt.
regression_baseline = regression_report(exact=False, code_sha="1" * 64)
regression_brief = build_verified_agent3_improvement_brief(
    regression_baseline,
    repository="Ternedal/ModelRig",
    base_sha=BASE_SHA,
)
regression_proposal = ImprovementProposal.from_mapping(proposal_data(regression_brief))
regression_authorization = PromotionAuthorization.from_mapping(
    promotion_authorization_data(regression_proposal)
)
regression_signature, regression_verifier = signed_promotion(regression_authorization)
_, regression_receipt = promote_improvement_proposal(
    proposal=regression_proposal,
    authorization=regression_authorization,
    signature=regression_signature,
    verifier=regression_verifier,
    verified_at_utc="2026-09-12T19:01:00Z",
)
regression_candidate = regression_report(exact=True, code_sha="2" * 64)
proof = build_candidate_regression_proof(
    proposal=regression_proposal,
    promotion_receipt=regression_receipt,
    baseline_report=regression_baseline,
    candidate_report=regression_candidate,
)
check(
    proof.accepted
    and proof.baseline_exact_match_rate == 0.0
    and proof.candidate_exact_match_rate == 1.0
    and proof.exact_improvements == ("read-rig-status#1",),
    "candidate accepteres kun ved en målbar exact-match forbedring",
)
check(
    proof.authority == REGRESSION_AUTHORITY
    and proof.merge_authority == "human"
    and proof.baseline_eval_sha256 == regression_proposal.evidence_sha256,
    "regression proof er evidens-only og bundet til proposalets originale eval",
)
check(
    proof.promotion_receipt_sha256 == regression_receipt.sha256
    and proof.task_sha256 == regression_receipt.task_sha256
    and proof.candidate_code_sha256 == "2" * 64,
    "regression proof binder promotion/task og den målte candidate code fingerprint",
)

# Re-running the incumbent is not a distinct candidate identity.
same_identity = regression_report(exact=True, code_sha="1" * 64)
expect_regression_error(
    "same measured code/model identity",
    lambda: build_candidate_regression_proof(
        proposal=regression_proposal,
        promotion_receipt=regression_receipt,
        baseline_report=regression_baseline,
        candidate_report=same_identity,
    ),
    "samme målte code/model-identitet kan ikke kaldes en ny candidate",
)

# The evaluation universe itself must remain identical.
changed_task_set = copy.deepcopy(regression_candidate)
changed_task_set["task_set"]["version"] = "2"
expect_regression_error(
    "task_set is not identical",
    lambda: build_candidate_regression_proof(
        proposal=regression_proposal,
        promotion_receipt=regression_receipt,
        baseline_report=regression_baseline,
        candidate_report=changed_task_set,
    ),
    "candidate må ikke skifte task-set under forbedringsmålingen",
)
changed_expected = copy.deepcopy(regression_candidate)
changed_expected["results"][0]["evaluation"]["expected_steps"][0]["tool"] = "model_list"
expect_regression_error(
    "expected_steps differ",
    lambda: build_candidate_regression_proof(
        proposal=regression_proposal,
        promotion_receipt=regression_receipt,
        baseline_report=regression_baseline,
        candidate_report=changed_expected,
    ),
    "candidate må ikke flytte målstregen ved at ændre expected steps",
)

# A distinct candidate that is not better yields an auditable reject proof, not authority.
no_gain = regression_report(exact=False, code_sha="2" * 64)
no_gain_proof = build_candidate_regression_proof(
    proposal=regression_proposal,
    promotion_receipt=regression_receipt,
    baseline_report=regression_baseline,
    candidate_report=no_gain,
)
check(
    not no_gain_proof.accepted
    and "candidate exact_match_rate is not strictly higher than baseline" in no_gain_proof.findings,
    "candidate uden strict gain afvises som regression proof",
)

# Safety/discipline cannot be traded for task accuracy.
discipline_loss = regression_report(
    exact=True,
    code_sha="2" * 64,
    discipline=False,
)
discipline_proof = build_candidate_regression_proof(
    proposal=regression_proposal,
    promotion_receipt=regression_receipt,
    baseline_report=regression_baseline,
    candidate_report=discipline_loss,
)
check(
    not discipline_proof.accepted
    and discipline_proof.discipline_regressions == ("read-rig-status#1",),
    "exact-match gain kan ikke købe en discipline-regression",
)
risk_loss = regression_report(
    exact=True,
    code_sha="2" * 64,
    risk_score=0.5,
)
risk_proof = build_candidate_regression_proof(
    proposal=regression_proposal,
    promotion_receipt=regression_receipt,
    baseline_report=regression_baseline,
    candidate_report=risk_loss,
)
check(
    not risk_proof.accepted
    and risk_proof.risk_score_regressions == ("read-rig-status#1",),
    "candidate med lavere per-case risk score afvises",
)

# The incumbent must be exactly the eval digest that generated the proposal.
wrong_baseline = copy.deepcopy(regression_baseline)
wrong_baseline["started_at"] = "2026-09-12T18:00:02+00:00"
expect_regression_error(
    "not the proposal source evidence",
    lambda: build_candidate_regression_proof(
        proposal=regression_proposal,
        promotion_receipt=regression_receipt,
        baseline_report=wrong_baseline,
        candidate_report=regression_candidate,
    ),
    "et andet incumbent-run kan ikke erstatte proposalets originale evidence digest",
)

print(f"\n===== RSI IMPROVEMENT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
