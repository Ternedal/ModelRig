from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.read_connector_eval import (  # noqa: E402
    CandidateFact,
    EvalCandidate,
    EvalCase,
    ReadConnectorEvalError,
    default_eval_cases,
    evaluate,
    validate_eval_corpus,
)

passed = failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def candidate_for(case: EvalCase, *, answer: str = "Grounded synthetic answer") -> EvalCandidate:
    return EvalCandidate(
        case_id=case.case_id,
        case_sha256=case.digest,
        answer=answer,
        facts=tuple(
            CandidateFact(fact.key, fact.value, fact.source_ids)
            for fact in case.expected_facts
        ),
        selected_source_ids=case.expected_selected_source_ids,
    )


def raises(exc_type, fn, contains: str) -> bool:
    try:
        fn()
    except exc_type as exc:
        return contains in str(exc)
    return False


def main() -> int:
    cases = default_eval_cases()
    check(len(cases) == 4, "default corpus has exactly four T-037 acceptance scenarios")
    check(
        tuple(case.scenario for case in cases)
        == (
            "calendar_brief",
            "document_finding",
            "mail_notion_summary",
            "source_grounding",
        ),
        "default corpus covers calendar, document, mail/Notion and grounding in fixed order",
    )

    for case in cases:
        result = evaluate(case, candidate_for(case))
        check(result.passed, f"perfect structured candidate passes {case.scenario}")
        check(result.fact_accuracy == 1.0, f"perfect facts score 1.0 for {case.scenario}")
        check(result.grounding_accuracy == 1.0, f"perfect grounding scores 1.0 for {case.scenario}")
        check(result.source_selection_accuracy == 1.0, f"perfect source selection scores 1.0 for {case.scenario}")
        check(result.production_activation is False, f"eval result remains non-production for {case.scenario}")

    calendar = cases[0]
    wrong_digest = EvalCandidate(
        case_id=calendar.case_id,
        case_sha256="0" * 64,
        answer="Grounded synthetic answer",
        facts=candidate_for(calendar).facts,
        selected_source_ids=calendar.expected_selected_source_ids,
    )
    result = evaluate(calendar, wrong_digest)
    check(not result.passed, "candidate from stale corpus digest is rejected")
    check("case_digest_mismatch" in result.violations, "stale corpus has explicit digest violation")

    doc = cases[1]
    invented_source = EvalCandidate(
        case_id=doc.case_id,
        case_sha256=doc.digest,
        answer="Mediaarkiv-arkitektur-beslutning",
        facts=(
            CandidateFact(
                "best_match",
                "Mediaarkiv-arkitektur-beslutning",
                ("invented-file-999",),
            ),
        ),
        selected_source_ids=("invented-file-999",),
    )
    result = evaluate(doc, invented_source)
    check(not result.passed, "invented source cannot pass document finding")
    check("invented_selected_source" in result.violations, "invented selected source is explicit")
    check(
        "invented_fact_source:best_match" in result.violations,
        "invented fact grounding is explicit",
    )

    mail_notion = cases[2]
    one_connector_only = EvalCandidate(
        case_id=mail_notion.case_id,
        case_sha256=mail_notion.digest,
        answer="Go-live 21. august; QA 20. august",
        facts=(
            CandidateFact("go_live_date", "21. august", ("gmail-msg-301",)),
            CandidateFact("qa_deadline", "20. august", ("gmail-msg-301",)),
        ),
        selected_source_ids=("gmail-msg-301",),
    )
    result = evaluate(mail_notion, one_connector_only)
    check(not result.passed, "mail/Notion summary cannot collapse grounding to Gmail only")
    check("wrong_grounding:qa_deadline" in result.violations, "Notion fact must retain Notion source")
    check(result.source_selection_accuracy < 1.0, "missing Notion source lowers selection score")

    grounding = cases[3]
    leak = candidate_for(grounding, answer="Godkendt — ungrounded-secret-canary")
    result = evaluate(grounding, leak)
    check(not result.passed, "forbidden non-projected canary fails source grounding")
    check("forbidden_projection_leak" in result.violations, "projection leak has explicit violation")

    unexpected = EvalCandidate(
        case_id=grounding.case_id,
        case_sha256=grounding.digest,
        answer="Godkendt af Platformteam",
        facts=candidate_for(grounding).facts
        + (CandidateFact("invented_claim", "Må ikke accepteres", ("drive-file-401",)),),
        selected_source_ids=grounding.expected_selected_source_ids,
    )
    result = evaluate(grounding, unexpected)
    check(not result.passed, "extra unrequested fact cannot hide inside a grounded answer")
    check("unexpected_fact" in result.violations, "unexpected fact is explicit")

    check(
        raises(
            ReadConnectorEvalError,
            lambda: validate_eval_corpus(cases[:-1]),
            "each T-037 scenario exactly once",
        ),
        "corpus validation rejects missing source-grounding scenario",
    )

    source_path = os.path.join(
        os.path.dirname(__file__), "..", "worker", "app", "read_connector_eval.py"
    )
    tree = ast.parse(open(source_path, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    check(
        {"socket", "ssl", "subprocess", "requests", "httpx", "urllib", "os"}.isdisjoint(imported),
        "eval harness has no network/process/environment imports",
    )

    source_text = open(source_path, encoding="utf-8").read()
    for needle in (
        "REGISTRY[",
        "APIRouter(",
        "FastAPI(",
        "os.getenv(",
        "Authorization",
        "Bearer ",
        "ollama_client",
        "chat_tools(",
    ):
        check(needle not in source_text, f"eval harness remains dormant: no {needle}")

    check(
        all("@" not in source.to_dict()["object_id"] for case in cases for source in case.sources),
        "synthetic eval corpus contains no email address object identifiers",
    )
    check(
        all(case.production_activation is False for case in cases),
        "all eval cases structurally keep production_activation=false",
    )

    print(f"\n===== T-037 DETERMINISTIC EVAL: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
