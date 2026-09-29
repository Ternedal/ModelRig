#!/usr/bin/env python3
"""Fail-closed qualification for Kaliv recovery + soak evidence.

The qualifier is deliberately read-only. It does not start, stop, restart,
update, schedule or activate anything. Operators first run the agreed physical
campaign, then this script validates that the resulting observations satisfy
the explicitly declared campaign policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

OBS_SCHEMA = "kaliv-recovery-soak-observations/v1"
RECEIPT_SCHEMA = "kaliv-recovery-soak-qualification/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_RECOVERY_KINDS = (
    "reboot",
    "backend_restart",
    "worker_restart",
    "interruption_recovery",
)
_MAX_SAMPLES = 100_000
_MAX_RECOVERY_EVENTS = 128
_MAX_EVIDENCE_REF = 512


class RecoverySoakError(RuntimeError):
    pass


@dataclass(frozen=True)
class Qualification:
    schema: str
    candidate_sha: str
    qualified: bool
    production_activation: bool
    observed_duration_seconds: int
    required_duration_seconds: int
    sample_count: int
    max_observed_gap_seconds: int
    required_recovery_kinds: tuple[str, ...]
    observations_sha256: str
    stage_b_evidence_ref: str
    release_evidence_ref: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "candidate_sha": self.candidate_sha,
            "qualified": self.qualified,
            "production_activation": self.production_activation,
            "observed_duration_seconds": self.observed_duration_seconds,
            "required_duration_seconds": self.required_duration_seconds,
            "sample_count": self.sample_count,
            "max_observed_gap_seconds": self.max_observed_gap_seconds,
            "required_recovery_kinds": list(self.required_recovery_kinds),
            "observations_sha256": self.observations_sha256,
            "stage_b_evidence_ref": self.stage_b_evidence_ref,
            "release_evidence_ref": self.release_evidence_ref,
        }


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecoverySoakError(f"{name} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    keys = set(value)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if extra:
            parts.append("unknown " + ", ".join(extra))
        raise RecoverySoakError(f"{name} has invalid fields: {'; '.join(parts)}")


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RecoverySoakError(f"{name} must be a nonblank ISO-8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RecoverySoakError(f"{name} is not valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecoverySoakError(f"{name} must be timezone-aware")
    return parsed


def _bounded_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RecoverySoakError(f"{name} must be a positive integer")
    return value


def _evidence_ref(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise RecoverySoakError(f"{name} must be a string")
    ref = value.strip()
    if not ref or len(ref) > _MAX_EVIDENCE_REF:
        raise RecoverySoakError(f"{name} must be a bounded nonblank reference")
    return ref


def qualify(observations: Mapping[str, Any], *, observations_sha256: str) -> Qualification:
    root = _mapping(observations, "observations")
    _exact_keys(
        root,
        {
            "schema",
            "candidate_sha",
            "production_activation",
            "policy",
            "stage_b_evidence_ref",
            "samples",
            "recovery_events",
        },
        "observations",
    )
    if root["schema"] != OBS_SCHEMA:
        raise RecoverySoakError("unsupported observations schema")

    candidate_sha = root["candidate_sha"]
    if not isinstance(candidate_sha, str) or _SHA40.fullmatch(candidate_sha) is None:
        raise RecoverySoakError("candidate_sha must be a lowercase 40-hex Git SHA")
    if root["production_activation"] is not False:
        raise RecoverySoakError("recovery-soak qualification cannot activate production")

    policy = _mapping(root["policy"], "policy")
    _exact_keys(
        policy,
        {"required_duration_seconds", "max_sample_gap_seconds"},
        "policy",
    )
    required_duration = _bounded_positive_int(
        policy["required_duration_seconds"], "policy.required_duration_seconds"
    )
    max_gap_allowed = _bounded_positive_int(
        policy["max_sample_gap_seconds"], "policy.max_sample_gap_seconds"
    )

    stage_b_ref = _evidence_ref(root["stage_b_evidence_ref"], "stage_b_evidence_ref")

    raw_samples = root["samples"]
    if not isinstance(raw_samples, list) or not 2 <= len(raw_samples) <= _MAX_SAMPLES:
        raise RecoverySoakError("samples must contain between 2 and 100000 entries")

    timestamps: list[datetime] = []
    for index, raw in enumerate(raw_samples):
        sample = _mapping(raw, f"samples[{index}]")
        _exact_keys(
            sample,
            {
                "observed_at",
                "backend_healthy",
                "worker_healthy",
                "supervisor_looping",
                "state_error_absent",
            },
            f"samples[{index}]",
        )
        ts = _timestamp(sample["observed_at"], f"samples[{index}].observed_at")
        if timestamps and ts <= timestamps[-1]:
            raise RecoverySoakError("sample timestamps must be strictly increasing")
        timestamps.append(ts)
        for field in (
            "backend_healthy",
            "worker_healthy",
            "supervisor_looping",
            "state_error_absent",
        ):
            if sample[field] is not True:
                raise RecoverySoakError(f"samples[{index}].{field} must be true")

    duration = int((timestamps[-1] - timestamps[0]).total_seconds())
    if duration < required_duration:
        raise RecoverySoakError(
            f"observed duration {duration}s is below declared policy {required_duration}s"
        )

    gaps = [
        int((right - left).total_seconds())
        for left, right in zip(timestamps, timestamps[1:])
    ]
    max_gap = max(gaps)
    if max_gap > max_gap_allowed:
        raise RecoverySoakError(
            f"sample gap {max_gap}s exceeds declared policy {max_gap_allowed}s"
        )

    raw_events = root["recovery_events"]
    if not isinstance(raw_events, list) or not 1 <= len(raw_events) <= _MAX_RECOVERY_EVENTS:
        raise RecoverySoakError("recovery_events must be a bounded non-empty list")

    seen: set[str] = set()
    for index, raw in enumerate(raw_events):
        event = _mapping(raw, f"recovery_events[{index}]")
        _exact_keys(
            event,
            {"kind", "observed_at", "passed", "evidence_ref"},
            f"recovery_events[{index}]",
        )
        kind = event["kind"]
        if kind not in _REQUIRED_RECOVERY_KINDS:
            raise RecoverySoakError(f"recovery_events[{index}].kind is not allowed")
        _timestamp(event["observed_at"], f"recovery_events[{index}].observed_at")
        if event["passed"] is not True:
            raise RecoverySoakError(f"recovery event {kind} did not pass")
        _evidence_ref(event["evidence_ref"], f"recovery_events[{index}].evidence_ref")
        if kind in seen:
            raise RecoverySoakError(f"duplicate recovery event kind: {kind}")
        seen.add(kind)

    missing = [kind for kind in _REQUIRED_RECOVERY_KINDS if kind not in seen]
    if missing:
        raise RecoverySoakError(
            "missing required recovery events: " + ", ".join(missing)
        )

    payload = {
        "schema": RECEIPT_SCHEMA,
        "candidate_sha": candidate_sha,
        "qualified": True,
        "production_activation": False,
        "observed_duration_seconds": duration,
        "required_duration_seconds": required_duration,
        "sample_count": len(timestamps),
        "max_observed_gap_seconds": max_gap,
        "required_recovery_kinds": list(_REQUIRED_RECOVERY_KINDS),
        "observations_sha256": observations_sha256,
        "stage_b_evidence_ref": stage_b_ref,
    }
    digest = hashlib.sha256(_canonical(payload)).hexdigest()
    release_evidence_ref = (
        "kaliv-recovery-soak:" + candidate_sha + ":" + digest
    )

    return Qualification(
        schema=RECEIPT_SCHEMA,
        candidate_sha=candidate_sha,
        qualified=True,
        production_activation=False,
        observed_duration_seconds=duration,
        required_duration_seconds=required_duration,
        sample_count=len(timestamps),
        max_observed_gap_seconds=max_gap,
        required_recovery_kinds=_REQUIRED_RECOVERY_KINDS,
        observations_sha256=observations_sha256,
        stage_b_evidence_ref=stage_b_ref,
        release_evidence_ref=release_evidence_ref,
    )


def load(path: Path) -> tuple[Mapping[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RecoverySoakError("observations file cannot be read") from exc
    if len(raw) > 16 * 1024 * 1024:
        raise RecoverySoakError("observations file is too large")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoverySoakError("observations file is not valid UTF-8 JSON") from exc
    return _mapping(parsed, "observations"), digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("observations", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        observations, digest = load(args.observations)
        receipt = qualify(observations, observations_sha256=digest).as_dict()
    except RecoverySoakError as exc:
        print(json.dumps({"schema": RECEIPT_SCHEMA, "qualified": False, "error": str(exc)}))
        return 2

    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.report.with_suffix(args.report.suffix + ".tmp")
        tmp.write_text(rendered, encoding="utf-8")
        tmp.replace(args.report)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
