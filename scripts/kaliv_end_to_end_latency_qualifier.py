#!/usr/bin/env python3
"""Measurement-only qualifier for the Kaliv end_to_end_latency release gate.

This qualifier proves that one real correlated event traversed perception,
cognition, and outward behavior under one monotonic observer clock. It measures
latency but deliberately applies no latency threshold until a physical baseline
establishes a defensible SLO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "kaliv-system/end-to-end-latency-evidence/v1"
VERDICT_SCHEMA = "kaliv-system/end-to-end-latency-verdict/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ALLOWED_OUTWARD = {"voice", "body", "voice+body"}
_MAX_REF_LEN = 512
_MAX_LATENCY_MS = 10 * 60 * 1000.0


class EndToEndLatencyQualificationError(RuntimeError):
    pass


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EndToEndLatencyQualificationError(f"{name} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        detail: list[str] = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise EndToEndLatencyQualificationError(
            f"{name} has invalid fields: {'; '.join(detail)}"
        )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _candidate_sha(value: Any) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise EndToEndLatencyQualificationError(
            "candidate_git_sha must be a lowercase 40-hex Git SHA"
        )
    return value


def _event_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or _EVENT_ID.fullmatch(value) is None:
        raise EndToEndLatencyQualificationError(
            f"{label} must be a bounded correlation id"
        )
    return value


def _at_ms(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EndToEndLatencyQualificationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise EndToEndLatencyQualificationError(
            f"{label} must be finite and non-negative"
        )
    return result


def _evidence_ref(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > _MAX_REF_LEN
    ):
        raise EndToEndLatencyQualificationError(
            f"{label} must be a bounded nonblank evidence ref"
        )
    return value.strip()


def _phase(value: Any, name: str, correlation_id: str) -> tuple[float, str]:
    phase = _mapping(value, name)
    _exact_keys(phase, {"correlation_id", "at_ms", "evidence_ref"}, name)
    if _event_id(phase["correlation_id"], f"{name}.correlation_id") != correlation_id:
        raise EndToEndLatencyQualificationError(
            f"{name} correlation id does not match event_id"
        )
    return (
        _at_ms(phase["at_ms"], f"{name}.at_ms"),
        _evidence_ref(phase["evidence_ref"], f"{name}.evidence_ref"),
    )


def qualify(value: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(value, "evidence")
    _exact_keys(
        root,
        {
            "schema",
            "candidate_git_sha",
            "event_id",
            "real_event",
            "simulated",
            "clock",
            "outward_kind",
            "phases",
            "production_activation",
        },
        "evidence",
    )
    if root["schema"] != SCHEMA:
        raise EndToEndLatencyQualificationError("unsupported latency evidence schema")
    candidate_sha = _candidate_sha(root["candidate_git_sha"])
    event_id = _event_id(root["event_id"], "event_id")

    if root["real_event"] is not True or root["simulated"] is not False:
        raise EndToEndLatencyQualificationError(
            "latency evidence must come from one real, non-simulated event"
        )
    if root["production_activation"] is not False:
        raise EndToEndLatencyQualificationError(
            "latency qualification cannot activate production"
        )
    outward_kind = root["outward_kind"]
    if outward_kind not in _ALLOWED_OUTWARD:
        raise EndToEndLatencyQualificationError(
            "outward_kind must be voice, body or voice+body"
        )

    clock = _mapping(root["clock"], "clock")
    _exact_keys(clock, {"kind", "unit", "origin"}, "clock")
    if clock != {
        "kind": "monotonic",
        "unit": "milliseconds",
        "origin": "single-observer",
    }:
        raise EndToEndLatencyQualificationError(
            "clock must be monotonic milliseconds from one observer"
        )

    phases = _mapping(root["phases"], "phases")
    _exact_keys(
        phases,
        {"perception_received", "cognition_completed", "outward_started"},
        "phases",
    )
    perception_ms, perception_ref = _phase(
        phases["perception_received"], "phases.perception_received", event_id
    )
    cognition_ms, cognition_ref = _phase(
        phases["cognition_completed"], "phases.cognition_completed", event_id
    )
    outward_ms, outward_ref = _phase(
        phases["outward_started"], "phases.outward_started", event_id
    )

    if not perception_ms <= cognition_ms <= outward_ms:
        raise EndToEndLatencyQualificationError(
            "phase timestamps must be monotone perception <= cognition <= outward"
        )
    refs = (perception_ref, cognition_ref, outward_ref)
    if len(set(refs)) != len(refs):
        raise EndToEndLatencyQualificationError(
            "phase evidence refs must be distinct"
        )

    end_to_end_ms = outward_ms - perception_ms
    cognition_ms_from_perception = cognition_ms - perception_ms
    outward_ms_from_cognition = outward_ms - cognition_ms
    if end_to_end_ms > _MAX_LATENCY_MS:
        raise EndToEndLatencyQualificationError(
            "end-to-end latency exceeds the measurement safety cap"
        )

    verdict = {
        "schema": VERDICT_SCHEMA,
        "candidate_git_sha": candidate_sha,
        "event_id": event_id,
        "state": "MEASURED",
        "real_event": True,
        "simulated": False,
        "outward_kind": outward_kind,
        "phase_evidence_refs": list(refs),
        "perception_to_cognition_ms": cognition_ms_from_perception,
        "cognition_to_outward_ms": outward_ms_from_cognition,
        "end_to_end_ms": end_to_end_ms,
        "threshold_applied": False,
        "end_to_end_latency_gate_satisfied": True,
        "release_gate_satisfied": False,
        "production_activation": False,
    }
    digest = hashlib.sha256(_canonical(verdict)).hexdigest()
    verdict["release_evidence_ref"] = (
        "kaliv-end-to-end-latency:" + candidate_sha + ":" + digest
    )
    return verdict


def load(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EndToEndLatencyQualificationError(
            "latency evidence file cannot be read"
        ) from exc
    if len(raw) > 1024 * 1024:
        raise EndToEndLatencyQualificationError("latency evidence file is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EndToEndLatencyQualificationError(
            "latency evidence file is not valid UTF-8 JSON"
        ) from exc
    return _mapping(value, "evidence")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        verdict = qualify(load(args.evidence))
    except EndToEndLatencyQualificationError as exc:
        verdict = {
            "schema": VERDICT_SCHEMA,
            "state": "INVALID",
            "end_to_end_latency_gate_satisfied": False,
            "release_gate_satisfied": False,
            "production_activation": False,
            "error": str(exc),
        }
        encoded = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 2

    encoded = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
