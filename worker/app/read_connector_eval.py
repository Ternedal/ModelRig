"""Deterministic offline eval harness for T-037 read-first connectors.

The harness scores *structured evidence answers*, not prose quality and not live
provider behavior.  It deliberately performs no model call, network I/O,
credential lookup or ToolGate registration.  Later runtime/provider slices can
feed candidate answers into this scorer without changing what "grounded" means.

The default synthetic corpus covers the four acceptance scenarios from #84:
calendar brief, document finding, Gmail+Notion summarization and source
grounding.  Every expected fact is tied to exact synthetic source ids and every
case is digest-bound so a corpus change cannot silently reuse old evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

EVAL_SCHEMA = "kaliv-read-connector-eval/v1"
CANDIDATE_SCHEMA = "kaliv-read-connector-eval-candidate/v1"
RESULT_SCHEMA = "kaliv-read-connector-eval-result/v1"
PRODUCTION_ACTIVATION = False

Scenario = Literal[
    "calendar_brief",
    "document_finding",
    "mail_notion_summary",
    "source_grounding",
]

_SCENARIOS: tuple[Scenario, ...] = (
    "calendar_brief",
    "document_finding",
    "mail_notion_summary",
    "source_grounding",
)
_CONNECTORS = frozenset({"google_calendar", "google_drive", "gmail", "notion"})
_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,119}$")
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,159}$")


class ReadConnectorEvalError(ValueError):
    """The deterministic eval corpus/candidate is malformed."""


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _bounded_text(value: str, name: str, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise ReadConnectorEvalError(f"{name} must be a string")
    value = " ".join(value.split())
    if not value or len(value) > maximum:
        raise ReadConnectorEvalError(f"{name} must contain 1..{maximum} characters")
    return value


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ReadConnectorEvalError(f"{name} has invalid format")
    return value


@dataclass(frozen=True)
class EvalSource:
    source_id: str
    connector: str
    object_id: str
    revision: str
    fields: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        if self.connector not in _CONNECTORS:
            raise ReadConnectorEvalError("unsupported eval connector")
        _identifier(self.object_id, "object_id")
        if not isinstance(self.revision, str) or not _REVISION.fullmatch(self.revision):
            raise ReadConnectorEvalError("revision has invalid format")
        if not isinstance(self.fields, tuple) or not self.fields:
            raise ReadConnectorEvalError("source fields must be a non-empty tuple")
        keys: list[str] = []
        for key, value in self.fields:
            if not isinstance(key, str) or not _KEY.fullmatch(key):
                raise ReadConnectorEvalError("source field key has invalid format")
            _bounded_text(value, f"source field {key}", 300)
            keys.append(key)
        if len(keys) != len(set(keys)):
            raise ReadConnectorEvalError("source fields contain duplicate keys")

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "connector": self.connector,
            "object_id": self.object_id,
            "revision": self.revision,
            "fields": {key: value for key, value in self.fields},
        }


@dataclass(frozen=True)
class ExpectedFact:
    key: str
    value: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not _KEY.fullmatch(self.key):
            raise ReadConnectorEvalError("fact key has invalid format")
        _bounded_text(self.value, f"fact {self.key}", 300)
        if not isinstance(self.source_ids, tuple) or not self.source_ids:
            raise ReadConnectorEvalError("expected fact requires source ids")
        for source_id in self.source_ids:
            _identifier(source_id, "fact source_id")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ReadConnectorEvalError("expected fact source ids contain duplicates")

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "source_ids": list(self.source_ids)}


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    scenario: Scenario
    prompt: str
    sources: tuple[EvalSource, ...]
    expected_facts: tuple[ExpectedFact, ...]
    expected_selected_source_ids: tuple[str, ...]
    forbidden_strings: tuple[str, ...] = ()
    schema: str = EVAL_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != EVAL_SCHEMA:
            raise ReadConnectorEvalError("unsupported eval schema")
        if self.production_activation is not False:
            raise ReadConnectorEvalError("production activation must remain false")
        _identifier(self.case_id, "case_id")
        if self.scenario not in _SCENARIOS:
            raise ReadConnectorEvalError("unsupported eval scenario")
        _bounded_text(self.prompt, "prompt", 500)
        if not isinstance(self.sources, tuple) or not self.sources:
            raise ReadConnectorEvalError("eval case requires sources")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ReadConnectorEvalError("eval case source ids contain duplicates")
        if not isinstance(self.expected_facts, tuple) or not self.expected_facts:
            raise ReadConnectorEvalError("eval case requires expected facts")
        fact_keys = [fact.key for fact in self.expected_facts]
        if len(fact_keys) != len(set(fact_keys)):
            raise ReadConnectorEvalError("eval case fact keys contain duplicates")
        source_set = set(source_ids)
        for fact in self.expected_facts:
            if not set(fact.source_ids) <= source_set:
                raise ReadConnectorEvalError("expected fact references unknown source")
        if not isinstance(self.expected_selected_source_ids, tuple) or not self.expected_selected_source_ids:
            raise ReadConnectorEvalError("eval case requires expected selected sources")
        if len(self.expected_selected_source_ids) != len(set(self.expected_selected_source_ids)):
            raise ReadConnectorEvalError("expected selected sources contain duplicates")
        if not set(self.expected_selected_source_ids) <= source_set:
            raise ReadConnectorEvalError("expected selected source is unknown")
        for value in self.forbidden_strings:
            _bounded_text(value, "forbidden string", 120)

    @property
    def connectors(self) -> tuple[str, ...]:
        return tuple(sorted({source.connector for source in self.sources}))

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "case_id": self.case_id,
            "scenario": self.scenario,
            "prompt": self.prompt,
            "sources": [source.to_dict() for source in self.sources],
            "expected_facts": [fact.to_dict() for fact in self.expected_facts],
            "expected_selected_source_ids": list(self.expected_selected_source_ids),
            "forbidden_strings": list(self.forbidden_strings),
            "production_activation": False,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


@dataclass(frozen=True)
class CandidateFact:
    key: str
    value: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not _KEY.fullmatch(self.key):
            raise ReadConnectorEvalError("candidate fact key has invalid format")
        _bounded_text(self.value, f"candidate fact {self.key}", 300)
        if not isinstance(self.source_ids, tuple) or not self.source_ids:
            raise ReadConnectorEvalError("candidate fact requires grounding source ids")
        for source_id in self.source_ids:
            _identifier(source_id, "candidate source_id")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ReadConnectorEvalError("candidate fact source ids contain duplicates")


@dataclass(frozen=True)
class EvalCandidate:
    case_id: str
    case_sha256: str
    answer: str
    facts: tuple[CandidateFact, ...]
    selected_source_ids: tuple[str, ...]
    schema: str = CANDIDATE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != CANDIDATE_SCHEMA:
            raise ReadConnectorEvalError("unsupported candidate schema")
        if self.production_activation is not False:
            raise ReadConnectorEvalError("production activation must remain false")
        _identifier(self.case_id, "candidate case_id")
        if not isinstance(self.case_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.case_sha256):
            raise ReadConnectorEvalError("candidate case digest must be lowercase SHA-256")
        _bounded_text(self.answer, "candidate answer", 2000)
        if not isinstance(self.facts, tuple) or not self.facts:
            raise ReadConnectorEvalError("candidate requires facts")
        keys = [fact.key for fact in self.facts]
        if len(keys) != len(set(keys)):
            raise ReadConnectorEvalError("candidate fact keys contain duplicates")
        if not isinstance(self.selected_source_ids, tuple) or not self.selected_source_ids:
            raise ReadConnectorEvalError("candidate requires selected sources")
        for source_id in self.selected_source_ids:
            _identifier(source_id, "candidate selected source_id")
        if len(self.selected_source_ids) != len(set(self.selected_source_ids)):
            raise ReadConnectorEvalError("candidate selected sources contain duplicates")


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    case_sha256: str
    passed: bool
    fact_accuracy: float
    grounding_accuracy: float
    source_selection_accuracy: float
    violations: tuple[str, ...]
    schema: str = RESULT_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "case_id": self.case_id,
            "case_sha256": self.case_sha256,
            "passed": self.passed,
            "fact_accuracy": self.fact_accuracy,
            "grounding_accuracy": self.grounding_accuracy,
            "source_selection_accuracy": self.source_selection_accuracy,
            "violations": list(self.violations),
            "production_activation": False,
        }


def evaluate(case: EvalCase, candidate: EvalCandidate) -> EvalResult:
    """Score exact facts, exact grounding and exact source selection.

    A candidate cannot compensate for an invented source with otherwise correct
    prose.  Unknown facts are violations, every required fact must be present,
    and grounding is exact to keep the harness deterministic and provenance-led.
    """
    if not isinstance(case, EvalCase) or not isinstance(candidate, EvalCandidate):
        raise ReadConnectorEvalError("evaluate requires typed case and candidate")

    violations: list[str] = []
    if candidate.case_id != case.case_id:
        violations.append("case_id_mismatch")
    if candidate.case_sha256 != case.digest:
        violations.append("case_digest_mismatch")

    source_ids = {source.source_id for source in case.sources}
    candidate_sources = set(candidate.selected_source_ids)
    unknown_selected = candidate_sources - source_ids
    if unknown_selected:
        violations.append("invented_selected_source")

    expected_by_key = {fact.key: fact for fact in case.expected_facts}
    candidate_by_key = {fact.key: fact for fact in candidate.facts}
    unknown_fact_keys = set(candidate_by_key) - set(expected_by_key)
    if unknown_fact_keys:
        violations.append("unexpected_fact")

    fact_hits = 0
    grounding_hits = 0
    for key, expected in expected_by_key.items():
        actual = candidate_by_key.get(key)
        if actual is None:
            violations.append(f"missing_fact:{key}")
            continue
        if actual.value == expected.value:
            fact_hits += 1
        else:
            violations.append(f"wrong_fact:{key}")
        actual_sources = set(actual.source_ids)
        if not actual_sources <= source_ids:
            violations.append(f"invented_fact_source:{key}")
        if actual.source_ids == expected.source_ids:
            grounding_hits += 1
        else:
            violations.append(f"wrong_grounding:{key}")

    expected_selected = set(case.expected_selected_source_ids)
    selection_hits = len(candidate_sources & expected_selected)
    selection_denominator = max(len(candidate_sources | expected_selected), 1)

    lowered_answer = candidate.answer.casefold()
    for forbidden in case.forbidden_strings:
        if forbidden.casefold() in lowered_answer:
            violations.append("forbidden_projection_leak")
            break

    count = len(case.expected_facts)
    fact_accuracy = fact_hits / count
    grounding_accuracy = grounding_hits / count
    source_selection_accuracy = selection_hits / selection_denominator
    passed = (
        not violations
        and fact_accuracy == 1.0
        and grounding_accuracy == 1.0
        and source_selection_accuracy == 1.0
    )
    return EvalResult(
        case_id=case.case_id,
        case_sha256=case.digest,
        passed=passed,
        fact_accuracy=fact_accuracy,
        grounding_accuracy=grounding_accuracy,
        source_selection_accuracy=source_selection_accuracy,
        violations=tuple(violations),
    )


def validate_eval_corpus(cases: tuple[EvalCase, ...]) -> None:
    if not isinstance(cases, tuple) or not cases:
        raise ReadConnectorEvalError("eval corpus must be a non-empty tuple")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ReadConnectorEvalError("eval corpus contains duplicate case ids")
    scenarios = tuple(case.scenario for case in cases)
    if set(scenarios) != set(_SCENARIOS) or len(scenarios) != len(_SCENARIOS):
        raise ReadConnectorEvalError("eval corpus must cover each T-037 scenario exactly once")
    by_scenario = {case.scenario: case for case in cases}
    if by_scenario["calendar_brief"].connectors != ("google_calendar",):
        raise ReadConnectorEvalError("calendar brief must be grounded in Google Calendar")
    if by_scenario["document_finding"].connectors != ("google_drive",):
        raise ReadConnectorEvalError("document finding must be grounded in Google Drive")
    if by_scenario["mail_notion_summary"].connectors != ("gmail", "notion"):
        raise ReadConnectorEvalError("mail/Notion summary must exercise both connectors")
    if len(by_scenario["source_grounding"].connectors) < 2:
        raise ReadConnectorEvalError("source grounding must exercise multiple connectors")


def default_eval_cases() -> tuple[EvalCase, ...]:
    cases = (
        EvalCase(
            case_id="calendar-brief-001",
            scenario="calendar_brief",
            prompt="Lav et kort brief over dagens relevante møder fra den viste kalenderprojektion.",
            sources=(
                EvalSource(
                    "cal-event-101",
                    "google_calendar",
                    "event-101",
                    "etag-cal-101",
                    (("title", "Arkitekturreview"), ("start", "2026-08-12T09:00:00+02:00")),
                ),
                EvalSource(
                    "cal-event-102",
                    "google_calendar",
                    "event-102",
                    "etag-cal-102",
                    (("title", "Leverandørstatus"), ("start", "2026-08-12T13:30:00+02:00")),
                ),
            ),
            expected_facts=(
                ExpectedFact("meeting_count", "2", ("cal-event-101", "cal-event-102")),
                ExpectedFact("next_meeting", "Leverandørstatus", ("cal-event-102",)),
            ),
            expected_selected_source_ids=("cal-event-101", "cal-event-102"),
            forbidden_strings=("private-description-canary",),
        ),
        EvalCase(
            case_id="document-finding-001",
            scenario="document_finding",
            prompt="Find det dokument der matcher Mediaarkiv-arkitekturens beslutningsnotat.",
            sources=(
                EvalSource(
                    "drive-file-201",
                    "google_drive",
                    "file-201",
                    "rev-drive-201",
                    (("name", "Mediaarkiv-arkitektur-beslutning"), ("mime", "document")),
                ),
                EvalSource(
                    "drive-file-202",
                    "google_drive",
                    "file-202",
                    "rev-drive-202",
                    (("name", "Ferieplan"), ("mime", "spreadsheet")),
                ),
            ),
            expected_facts=(
                ExpectedFact("best_match", "Mediaarkiv-arkitektur-beslutning", ("drive-file-201",)),
            ),
            expected_selected_source_ids=("drive-file-201",),
            forbidden_strings=("drive-secret-canary",),
        ),
        EvalCase(
            case_id="mail-notion-summary-001",
            scenario="mail_notion_summary",
            prompt="Sammenfat beslutningen fra den viste mail og den relaterede Notion-side med kildegrunding.",
            sources=(
                EvalSource(
                    "gmail-msg-301",
                    "gmail",
                    "message-301",
                    "history-301",
                    (("subject", "Go-live beslutning"), ("summary", "Go-live flyttes til 21. august.")),
                ),
                EvalSource(
                    "notion-page-302",
                    "notion",
                    "page-302",
                    "notion-rev-302",
                    (("title", "Releaseplan"), ("summary", "QA-signoff skal være færdig 20. august.")),
                ),
            ),
            expected_facts=(
                ExpectedFact("go_live_date", "21. august", ("gmail-msg-301",)),
                ExpectedFact("qa_deadline", "20. august", ("notion-page-302",)),
            ),
            expected_selected_source_ids=("gmail-msg-301", "notion-page-302"),
            forbidden_strings=("mail-body-canary", "notion-private-canary"),
        ),
        EvalCase(
            case_id="source-grounding-001",
            scenario="source_grounding",
            prompt="Svar kun med fakta der kan bindes til de viste connector-kilder.",
            sources=(
                EvalSource(
                    "drive-file-401",
                    "google_drive",
                    "file-401",
                    "rev-drive-401",
                    (("name", "Beslutningslog"), ("status", "Godkendt")),
                ),
                EvalSource(
                    "notion-page-402",
                    "notion",
                    "page-402",
                    "notion-rev-402",
                    (("title", "Ejerliste"), ("owner", "Platformteam")),
                ),
            ),
            expected_facts=(
                ExpectedFact("decision_status", "Godkendt", ("drive-file-401",)),
                ExpectedFact("owner", "Platformteam", ("notion-page-402",)),
            ),
            expected_selected_source_ids=("drive-file-401", "notion-page-402"),
            forbidden_strings=("ungrounded-secret-canary",),
        ),
    )
    validate_eval_corpus(cases)
    return cases
