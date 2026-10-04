#!/usr/bin/env python3
"""Content-bound qualifier for the Kaliv end_to_end_latency release gate.

The qualifier accepts three concrete source receipt files from one observer:
perception_received, cognition_completed and outward_started. It hashes and
validates those files independently before deriving latency. Caller-authored
reference strings are not release authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

SOURCE_SCHEMA = "kaliv-system/end-to-end-latency-source/v1"
VERDICT_SCHEMA = "kaliv-system/end-to-end-latency-verdict/v2"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_ALLOWED_OUTWARD = {"voice", "body", "voice+body"}
_PHASES = ("perception_received", "cognition_completed", "outward_started")
_MAX_RECEIPT_BYTES = 1024 * 1024
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


def _bounded_token(value: Any, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise EndToEndLatencyQualificationError(f"{label} must be a bounded token")
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


def _clock(value: Any) -> Mapping[str, Any]:
    clock = _mapping(value, "clock")
    _exact_keys(clock, {"kind", "unit", "origin"}, "clock")
    expected = {
        "kind": "monotonic",
        "unit": "milliseconds",
        "origin": "single-observer",
    }
    if clock != expected:
        raise EndToEndLatencyQualificationError(
            "clock must be monotonic milliseconds from one observer"
        )
    return clock


def _resolve_receipt(root: Path, raw_path: Path, label: str) -> tuple[Path, str]:
    root = root.resolve()
    path = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        relative = path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise EndToEndLatencyQualificationError(
            f"{label} must exist under evidence root"
        ) from exc

    probe = root
    for part in relative.parts:
        probe = probe / part
        if probe.is_symlink():
            raise EndToEndLatencyQualificationError(
                f"{label} must not traverse symlinks"
            )
    resolved = root / relative
    if not resolved.is_file():
        raise EndToEndLatencyQualificationError(
            f"{label} must be a regular receipt file"
        )
    return resolved, relative.as_posix()


def _load_receipt(root: Path, raw_path: Path, label: str) -> tuple[Mapping[str, Any], str, str]:
    path, relative = _resolve_receipt(root, raw_path, label)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EndToEndLatencyQualificationError(f"{label} cannot be read") from exc
    if not raw or len(raw) > _MAX_RECEIPT_BYTES:
        raise EndToEndLatencyQualificationError(
            f"{label} must be nonempty and at most {_MAX_RECEIPT_BYTES} bytes"
        )
    digest = hashlib.sha256(raw).hexdigest()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EndToEndLatencyQualificationError(
            f"{label} is not valid UTF-8 JSON"
        ) from exc
    return _mapping(value, label), relative, digest


def _validate_common(
    receipt: Mapping[str, Any],
    *,
    phase: str,
) -> tuple[str, str, str, str, float]:
    _exact_keys(
        receipt,
        {
            "schema",
            "phase",
            "candidate_git_sha",
            "event_id",
            "runtime_epoch",
            "observer_id",
            "clock",
            "observed_at_ms",
            "real_event",
            "simulated",
            "replay",
            "details",
            "production_activation",
        },
        phase,
    )
    if receipt["schema"] != SOURCE_SCHEMA:
        raise EndToEndLatencyQualificationError(
            f"{phase} has unsupported source receipt schema"
        )
    if receipt["phase"] != phase:
        raise EndToEndLatencyQualificationError(
            f"{phase} receipt phase does not match its slot"
        )
    if receipt["real_event"] is not True or receipt["simulated"] is not False:
        raise EndToEndLatencyQualificationError(
            f"{phase} must describe a real, non-simulated event"
        )
    if receipt["replay"] is not False:
        raise EndToEndLatencyQualificationError(
            f"{phase} replay evidence is not accepted"
        )
    if receipt["production_activation"] is not False:
        raise EndToEndLatencyQualificationError(
            f"{phase} cannot activate production"
        )
    _clock(receipt["clock"])
    return (
        _candidate_sha(receipt["candidate_git_sha"]),
        _event_id(receipt["event_id"], f"{phase}.event_id"),
        _bounded_token(receipt["runtime_epoch"], f"{phase}.runtime_epoch"),
        _bounded_token(receipt["observer_id"], f"{phase}.observer_id"),
        _at_ms(receipt["observed_at_ms"], f"{phase}.observed_at_ms"),
    )


def _validate_perception(details: Any) -> None:
    value = _mapping(details, "perception_received.details")
    _exact_keys(value, {"input_kind", "input_id"}, "perception_received.details")
    _bounded_token(value["input_kind"], "perception_received.details.input_kind")
    _bounded_token(value["input_id"], "perception_received.details.input_id")


def _validate_cognition(details: Any, event_id: str) -> None:
    value = _mapping(details, "cognition_completed.details")
    _exact_keys(
        value,
        {"cognition_event_id", "transition_receipt_ref", "completed_cycles"},
        "cognition_completed.details",
    )
    cognition_event_id = _event_id(
        value["cognition_event_id"],
        "cognition_completed.details.cognition_event_id",
    )
    if cognition_event_id != event_id:
        raise EndToEndLatencyQualificationError(
            "cognition_event_id does not match event_id"
        )
    ref = value["transition_receipt_ref"]
    if not isinstance(ref, str) or not ref.strip() or len(ref) > 512:
        raise EndToEndLatencyQualificationError(
            "cognition transition_receipt_ref must be nonblank and bounded"
        )
    cycles = value["completed_cycles"]
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 1:
        raise EndToEndLatencyQualificationError(
            "cognition must contain at least one completed real cycle"
        )


def _validate_outward(details: Any) -> str:
    value = _mapping(details, "outward_started.details")
    _exact_keys(
        value,
        {"outward_kind", "started", "utterance_id", "body_runtime_id"},
        "outward_started.details",
    )
    kind = value["outward_kind"]
    if kind not in _ALLOWED_OUTWARD:
        raise EndToEndLatencyQualificationError(
            "outward_kind must be voice, body or voice+body"
        )
    if value["started"] is not True:
        raise EndToEndLatencyQualificationError(
            "outward evidence must prove actual outward start"
        )

    utterance = value["utterance_id"]
    body = value["body_runtime_id"]
    if utterance is not None:
        utterance = _bounded_token(utterance, "outward_started.details.utterance_id")
    if body is not None:
        body = _bounded_token(body, "outward_started.details.body_runtime_id")

    if kind == "voice" and utterance is None:
        raise EndToEndLatencyQualificationError("voice outward start requires utterance_id")
    if kind == "body" and body is None:
        raise EndToEndLatencyQualificationError("body outward start requires body_runtime_id")
    if kind == "voice+body" and (utterance is None or body is None):
        raise EndToEndLatencyQualificationError(
            "voice+body outward start requires utterance_id and body_runtime_id"
        )
    return kind


def qualify_receipts(
    *,
    evidence_root: Path,
    perception_path: Path,
    cognition_path: Path,
    outward_path: Path,
) -> dict[str, Any]:
    loaded: dict[str, tuple[Mapping[str, Any], str, str]] = {}
    for phase, path in (
        ("perception_received", perception_path),
        ("cognition_completed", cognition_path),
        ("outward_started", outward_path),
    ):
        loaded[phase] = _load_receipt(evidence_root, path, phase)

    paths = [loaded[p][1] for p in _PHASES]
    digests = [loaded[p][2] for p in _PHASES]
    if len(set(paths)) != 3 or len(set(digests)) != 3:
        raise EndToEndLatencyQualificationError(
            "source receipts must be three distinct files with distinct content"
        )

    common = {
        phase: _validate_common(loaded[phase][0], phase=phase)
        for phase in _PHASES
    }
    candidates = {common[p][0] for p in _PHASES}
    events = {common[p][1] for p in _PHASES}
    epochs = {common[p][2] for p in _PHASES}
    observers = {common[p][3] for p in _PHASES}
    if len(candidates) != 1:
        raise EndToEndLatencyQualificationError("candidate SHA mismatch across receipts")
    if len(events) != 1:
        raise EndToEndLatencyQualificationError("mixed correlation/event ids")
    if len(epochs) != 1:
        raise EndToEndLatencyQualificationError("mixed runtime epoch")
    if len(observers) != 1:
        raise EndToEndLatencyQualificationError("mixed observer clock")

    candidate_sha = next(iter(candidates))
    event_id = next(iter(events))
    runtime_epoch = next(iter(epochs))
    observer_id = next(iter(observers))

    _validate_perception(loaded["perception_received"][0]["details"])
    _validate_cognition(loaded["cognition_completed"][0]["details"], event_id)
    outward_kind = _validate_outward(loaded["outward_started"][0]["details"])

    perception_ms = common["perception_received"][4]
    cognition_ms = common["cognition_completed"][4]
    outward_ms = common["outward_started"][4]
    if not perception_ms <= cognition_ms <= outward_ms:
        raise EndToEndLatencyQualificationError(
            "phase timestamps must be monotone perception <= cognition <= outward"
        )
    end_to_end_ms = outward_ms - perception_ms
    if end_to_end_ms > _MAX_LATENCY_MS:
        raise EndToEndLatencyQualificationError(
            "end-to-end latency exceeds the measurement safety cap"
        )

    source_receipts = [
        {
            "phase": phase,
            "path": loaded[phase][1],
            "sha256": loaded[phase][2],
        }
        for phase in _PHASES
    ]
    verdict = {
        "schema": VERDICT_SCHEMA,
        "candidate_git_sha": candidate_sha,
        "event_id": event_id,
        "runtime_epoch": runtime_epoch,
        "observer_id": observer_id,
        "state": "MEASURED",
        "real_event": True,
        "simulated": False,
        "replay": False,
        "outward_kind": outward_kind,
        "source_receipts": source_receipts,
        "perception_to_cognition_ms": cognition_ms - perception_ms,
        "cognition_to_outward_ms": outward_ms - cognition_ms,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--perception", required=True, type=Path)
    parser.add_argument("--cognition", required=True, type=Path)
    parser.add_argument("--outward", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        verdict = qualify_receipts(
            evidence_root=args.evidence_root,
            perception_path=args.perception,
            cognition_path=args.cognition,
            outward_path=args.outward,
        )
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
