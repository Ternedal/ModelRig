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
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

OBS_SCHEMA = "kaliv-recovery-soak-observations/v1"
RECEIPT_SCHEMA = "kaliv-recovery-soak-qualification/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGE_B_FINAL_SCHEMA = "kaliv-stage-b-physical-final/v1"
_EXPECTED_STAGE_B_STEPS = (
    ("strict source/bootstrap/interruption gate", "stage_b_strict_evidence.py"),
    ("base Stage B physical gate", "stage_b_physical_gate.py"),
    ("release freeze", "freeze_check.py"),
    ("updater-chain gate", "appliance_lifecycle_updater_chain.py"),
    ("eight-proof release campaign", "physical_validation_campaign.py"),
    ("nine-proof component final gate", "physical_validation_final_gate.py"),
)
_EXPECTED_STAGE_B_PROOFS = (
    "preflight",
    "agent3",
    "model_eval",
    "voice",
    "rag",
    "lifecycle",
    "scheduler_pilot",
    "task_ui",
    "browser_peer_physical",
)
_REQUIRED_RECOVERY_KINDS = (
    "reboot",
    "backend_restart",
    "worker_restart",
    "interruption_recovery",
)
_MAX_SAMPLES = 100_000
_MAX_RECOVERY_EVENTS = 128
_MAX_EVIDENCE_REF = 512
_MAX_COMPONENT_BYTES = 32 * 1024 * 1024
_STAGE_B_COMPONENTS = {
    "updater_chain": (
        "kaliv-appliance-lifecycle-updater-chain/v1",
        ("passed", "updater_chain_complete"),
    ),
    "physical_campaign": (
        "kaliv-physical-validation-campaign/v1",
        ("passed", "physical_campaign_complete"),
    ),
    "component_final_gate": (
        "kaliv-physical-validation-final/v1",
        ("passed", "all_physical_evidence_complete"),
    ),
    "strict_stage_b": (
        "kaliv-stage-b-strict-evidence/v1",
        ("passed", "strict_evidence_complete"),
    ),
}


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


def _stage_b_evidence_ref(value: Any, *, stage_b_sha256: str) -> str:
    ref = _evidence_ref(value, "stage_b_evidence_ref")
    marker = "#sha256="
    if marker not in ref:
        raise RecoverySoakError(
            "stage_b_evidence_ref must end with #sha256=<64 lowercase hex>"
        )
    prefix, digest = ref.rsplit(marker, 1)
    if not prefix or _SHA256.fullmatch(digest) is None:
        raise RecoverySoakError(
            "stage_b_evidence_ref must end with #sha256=<64 lowercase hex>"
        )
    if digest != stage_b_sha256:
        raise RecoverySoakError(
            "stage_b_evidence_ref digest does not match the Stage-B report bytes"
        )
    return ref


def _component_path(root: Path, raw: Any, name: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RecoverySoakError(f"Stage-B evidence {name}.path must be nonblank")
    relative = Path(raw)
    if relative.is_absolute():
        raise RecoverySoakError(f"Stage-B evidence {name}.path must be repository-relative")
    root = root.resolve()
    candidate = root / relative
    probe = root
    for part in relative.parts:
        probe = probe / part
        if probe.is_symlink():
            raise RecoverySoakError(f"Stage-B evidence {name}.path must not traverse symlinks")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RecoverySoakError(
            f"Stage-B evidence {name}.path escapes repository root"
        ) from exc
    return resolved


def _load_stage_b_validator(script_name: str):
    script = Path(__file__).resolve().parent / script_name
    module_name = "_recovery_soak_" + script.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise RecoverySoakError(
            f"canonical Stage-B validator cannot be loaded: {script_name}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RecoverySoakError(
            f"canonical Stage-B validator failed to load: {script_name}"
        ) from exc
    return module


def _positive_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecoverySoakError(f"{name} must be numeric")
    result = float(value)
    if result <= 0:
        raise RecoverySoakError(f"{name} must be positive")
    return result


def _revalidate_stage_b_component(
    repository_root: Path,
    name: str,
    receipt: Mapping[str, Any],
    *,
    candidate_identity: Mapping[str, Any],
) -> None:
    now = datetime.now(timezone.utc)

    if name in {"strict_stage_b", "updater_chain"}:
        source = _mapping(
            receipt.get("source"),
            f"Stage-B evidence {name}.source",
        )
        source_path = source.get("path")
        if not isinstance(source_path, str) or not source_path:
            raise RecoverySoakError(
                f"Stage-B evidence {name}.source.path must be nonblank"
            )
        script_name = (
            "stage_b_strict_evidence.py"
            if name == "strict_stage_b"
            else "appliance_lifecycle_updater_chain.py"
        )
        module = _load_stage_b_validator(script_name)
        try:
            regenerated, code = module.evaluate(
                repository_root,
                Path(source_path),
                candidate=candidate_identity,
                now=now,
            )
        except Exception as exc:
            raise RecoverySoakError(
                f"Stage-B evidence {name} canonical revalidation failed"
            ) from exc
        if code != 0:
            raise RecoverySoakError(
                f"Stage-B evidence {name} underlying evidence did not revalidate"
            )
        for section in ("source", "evidence", "summary", "gate"):
            if regenerated.get(section) != receipt.get(section):
                raise RecoverySoakError(
                    f"Stage-B evidence {name} does not match canonical revalidation"
                )
        return

    if name == "physical_campaign":
        configuration = _mapping(
            receipt.get("configuration"),
            "Stage-B physical campaign configuration",
        )
        max_age_hours = _positive_number(
            configuration.get("max_age_hours"),
            "Stage-B physical campaign configuration.max_age_hours",
        )
        min_model_exact_raw = configuration.get("min_model_exact")
        if (
            isinstance(min_model_exact_raw, bool)
            or not isinstance(min_model_exact_raw, (int, float))
            or not 0 <= float(min_model_exact_raw) <= 1
        ):
            raise RecoverySoakError(
                "Stage-B physical campaign configuration.min_model_exact is invalid"
            )
        min_model_exact = float(min_model_exact_raw)
        evidence = _mapping(
            receipt.get("evidence"),
            "Stage-B physical campaign evidence",
        )
        expected_names = _EXPECTED_STAGE_B_PROOFS[:-1]
        _exact_keys(
            evidence,
            set(expected_names),
            "Stage-B physical campaign evidence",
        )
        module = _load_stage_b_validator("physical_validation_campaign.py")
        try:
            assessor = module._load_agent3_assessor(repository_root)
        except Exception as exc:
            raise RecoverySoakError(
                "Stage-B physical campaign Agent 3 validator cannot be loaded"
            ) from exc
        thresholds = {
            "min_model_exact": min_model_exact,
            "agent3_assessor": assessor,
            "root": repository_root,
        }
        previous_validators = module._core.VALIDATORS
        module._core.VALIDATORS = module.EXTENDED_VALIDATORS
        try:
            for proof_name in expected_names:
                stored = _mapping(
                    evidence.get(proof_name),
                    f"Stage-B physical campaign evidence.{proof_name}",
                )
                stored_path = stored.get("path")
                if not isinstance(stored_path, str) or not stored_path:
                    raise RecoverySoakError(
                        f"Stage-B physical campaign evidence.{proof_name}.path must be nonblank"
                    )
                result = module.validate_evidence(
                    repository_root,
                    proof_name,
                    Path(stored_path),
                    candidate=dict(candidate_identity),
                    thresholds=thresholds,
                    now=now,
                    max_age_hours=max_age_hours,
                )
                if result.get("status") != "pass":
                    detail = "; ".join(result.get("errors") or [])
                    raise RecoverySoakError(
                        f"Stage-B physical campaign {proof_name} did not revalidate"
                        + (f": {detail[:300]}" if detail else "")
                    )
                for field in ("path", "sha256", "bytes"):
                    if result.get(field) != stored.get(field):
                        raise RecoverySoakError(
                            f"Stage-B physical campaign {proof_name}.{field} "
                            "does not match canonical revalidation"
                        )
        finally:
            module._core.VALIDATORS = previous_validators
        return

    if name == "component_final_gate":
        configuration = _mapping(
            receipt.get("configuration"),
            "Stage-B component final configuration",
        )
        max_age_hours = _positive_number(
            configuration.get("max_age_hours"),
            "Stage-B component final configuration.max_age_hours",
        )
        evidence = _mapping(
            receipt.get("evidence"),
            "Stage-B component final evidence",
        )
        campaign_meta = _mapping(
            evidence.get("physical_campaign"),
            "Stage-B component final evidence.physical_campaign",
        )
        browser_meta = _mapping(
            evidence.get("browser_peer_physical_attestation"),
            "Stage-B component final evidence.browser_peer_physical_attestation",
        )
        campaign_path = campaign_meta.get("path")
        browser_path = browser_meta.get("path")
        if not isinstance(campaign_path, str) or not campaign_path:
            raise RecoverySoakError(
                "Stage-B component final physical campaign path is missing"
            )
        if not isinstance(browser_path, str) or not browser_path:
            raise RecoverySoakError(
                "Stage-B component final browser attestation path is missing"
            )
        module = _load_stage_b_validator("physical_validation_final_gate.py")
        try:
            regenerated, code = module.evaluate_final_gate(
                repository_root,
                Path(campaign_path),
                Path(browser_path),
                candidate=candidate_identity,
                now=now,
                max_age_hours=max_age_hours,
            )
        except Exception as exc:
            raise RecoverySoakError(
                "Stage-B component final canonical revalidation failed"
            ) from exc
        if code != 0:
            detail = "; ".join(regenerated.get("summary", {}).get("errors") or [])
            raise RecoverySoakError(
                "Stage-B component final underlying browser/campaign evidence "
                "did not revalidate"
                + (f": {detail[:300]}" if detail else "")
            )
        for section in ("evidence", "summary", "gate"):
            if regenerated.get(section) != receipt.get(section):
                raise RecoverySoakError(
                    "Stage-B component final does not match canonical revalidation"
                )
        return

    raise RecoverySoakError(f"unsupported Stage-B component: {name}")


def _validate_stage_b_component(
    repository_root: Path,
    name: str,
    meta_value: Any,
    *,
    candidate_identity: Mapping[str, Any],
) -> None:
    expected_schema, required_gate_true = _STAGE_B_COMPONENTS[name]
    meta = _mapping(meta_value, f"stage_b_report.evidence.{name}")
    _exact_keys(meta, {"path", "sha256", "bytes", "schema"}, f"stage_b_report.evidence.{name}")
    if meta.get("schema") != expected_schema:
        raise RecoverySoakError(f"Stage-B evidence {name} schema metadata mismatch")
    digest = meta.get("sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise RecoverySoakError(f"Stage-B evidence {name}.sha256 must be lowercase SHA-256")
    byte_count = meta.get("bytes")
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count <= 0
        or byte_count > _MAX_COMPONENT_BYTES
    ):
        raise RecoverySoakError(f"Stage-B evidence {name}.bytes is invalid")

    path = _component_path(repository_root, meta.get("path"), name)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RecoverySoakError(f"Stage-B evidence {name} file cannot be read") from exc
    if len(raw) != byte_count:
        raise RecoverySoakError(f"Stage-B evidence {name} byte count does not match file")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RecoverySoakError(f"Stage-B evidence {name} SHA-256 does not match file")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoverySoakError(f"Stage-B evidence {name} is not valid UTF-8 JSON") from exc
    receipt = _mapping(parsed, f"Stage-B evidence {name}")
    if receipt.get("schema") != expected_schema:
        raise RecoverySoakError(f"Stage-B evidence {name} embedded schema mismatch")
    candidate = _mapping(receipt.get("candidate"), f"Stage-B evidence {name}.candidate")
    for field in ("version", "git_sha", "code_sha256"):
        if candidate.get(field) != candidate_identity.get(field):
            raise RecoverySoakError(
                f"Stage-B evidence {name} candidate {field} mismatch"
            )
    gate = _mapping(receipt.get("gate"), f"Stage-B evidence {name}.gate")
    for field in required_gate_true:
        if gate.get(field) is not True:
            raise RecoverySoakError(f"Stage-B evidence {name} gate.{field} must be true")
    if gate.get("production_activation") is not False:
        raise RecoverySoakError(
            f"Stage-B evidence {name} must preserve production_activation=false"
        )

    _revalidate_stage_b_component(
        repository_root,
        name,
        receipt,
        candidate_identity=candidate_identity,
    )

    if name == "physical_campaign":
        if receipt.get("mode") != "verify":
            raise RecoverySoakError("Stage-B physical campaign must be verify mode")
        summary = _mapping(receipt.get("summary"), "Stage-B physical campaign summary")
        if summary.get("total") != 8 or tuple(summary.get("passed") or ()) != _EXPECTED_STAGE_B_PROOFS[:-1]:
            raise RecoverySoakError("Stage-B physical campaign must contain canonical eight proofs")
    elif name == "component_final_gate":
        summary = _mapping(receipt.get("summary"), "Stage-B component final summary")
        if summary.get("total") != 9 or tuple(summary.get("passed") or ()) != _EXPECTED_STAGE_B_PROOFS:
            raise RecoverySoakError("Stage-B component final must contain canonical nine proofs")


def _validate_stage_b_report(
    value: Mapping[str, Any],
    *,
    candidate_sha: str,
    repository_root: Path,
) -> None:
    report = _mapping(value, "stage_b_report")
    if report.get("schema") != _STAGE_B_FINAL_SCHEMA:
        raise RecoverySoakError("Stage-B report schema mismatch")
    if report.get("status") != "complete":
        raise RecoverySoakError("Stage-B report status must be complete")

    candidate = _mapping(report.get("candidate"), "stage_b_report.candidate")
    if candidate.get("git_sha") != candidate_sha:
        raise RecoverySoakError(
            "Stage-B report candidate Git SHA does not match recovery candidate"
        )
    if not isinstance(candidate.get("version"), str) or not candidate.get("version"):
        raise RecoverySoakError("Stage-B report candidate version is invalid")
    if not isinstance(candidate.get("code_sha256"), str) or _SHA256.fullmatch(
        candidate.get("code_sha256")
    ) is None:
        raise RecoverySoakError("Stage-B report candidate code_sha256 is invalid")
    if candidate.get("working_tree_clean") is not True:
        raise RecoverySoakError("Stage-B report candidate checkout is not clean")

    evidence = _mapping(report.get("evidence"), "stage_b_report.evidence")
    _exact_keys(
        evidence,
        set(_STAGE_B_COMPONENTS),
        "stage_b_report.evidence",
    )
    for component_name in _STAGE_B_COMPONENTS:
        _validate_stage_b_component(
            repository_root,
            component_name,
            evidence.get(component_name),
            candidate_identity=candidate,
        )

    steps = report.get("steps")
    if not isinstance(steps, list):
        raise RecoverySoakError("Stage-B report steps must be a list")
    if len(steps) != len(_EXPECTED_STAGE_B_STEPS):
        raise RecoverySoakError(
            "Stage-B report must contain the complete six-step execution sequence"
        )
    for index, (raw_step, expected) in enumerate(
        zip(steps, _EXPECTED_STAGE_B_STEPS)
    ):
        step = _mapping(raw_step, f"stage_b_report.steps[{index}]")
        expected_label, expected_script = expected
        if step.get("label") != expected_label:
            raise RecoverySoakError(
                f"Stage-B report steps[{index}].label does not match canonical sequence"
            )
        command = step.get("command")
        if not isinstance(command, list) or len(command) < 2:
            raise RecoverySoakError(
                f"Stage-B report steps[{index}].command must be a command list"
            )
        script = command[1]
        if not isinstance(script, str) or Path(script).name != expected_script:
            raise RecoverySoakError(
                f"Stage-B report steps[{index}].command does not match canonical script"
            )
        exit_code = step.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise RecoverySoakError(
                f"Stage-B report steps[{index}].exit_code must be an integer"
            )
        if exit_code != 0:
            raise RecoverySoakError(
                f"Stage-B report steps[{index}].exit_code must be zero"
            )

    summary = _mapping(report.get("summary"), "stage_b_report.summary")
    if summary.get("total") != len(_EXPECTED_STAGE_B_PROOFS):
        raise RecoverySoakError("Stage-B report summary.total must be nine")
    errors = summary.get("errors")
    if not isinstance(errors, list):
        raise RecoverySoakError("Stage-B report summary.errors must be a list")
    if errors:
        raise RecoverySoakError("Stage-B report summary.errors must be empty")
    passed = summary.get("passed")
    if not isinstance(passed, list):
        raise RecoverySoakError("Stage-B report summary.passed must be a list")
    if tuple(passed) != _EXPECTED_STAGE_B_PROOFS:
        raise RecoverySoakError(
            "Stage-B report summary.passed must contain all nine canonical proofs"
        )

    gate = _mapping(report.get("gate"), "stage_b_report.gate")
    required_true = (
        "passed",
        "release_freeze_complete",
        "updater_chain_complete",
        "strict_evidence_complete",
        "physical_campaign_complete",
        "browser_peer_physical_complete",
        "all_physical_evidence_complete",
    )
    for field in required_true:
        if gate.get(field) is not True:
            raise RecoverySoakError(f"Stage-B report gate.{field} must be true")
    if gate.get("production_activation") is not False:
        raise RecoverySoakError(
            "Stage-B report must preserve production_activation=false"
        )


def qualify(
    observations: Mapping[str, Any],
    *,
    observations_sha256: str,
    stage_b_report: Mapping[str, Any],
    stage_b_sha256: str,
    stage_b_repository_root: Path,
) -> Qualification:
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

    _validate_stage_b_report(
        stage_b_report,
        candidate_sha=candidate_sha,
        repository_root=stage_b_repository_root,
    )
    stage_b_ref = _stage_b_evidence_ref(
        root["stage_b_evidence_ref"], stage_b_sha256=stage_b_sha256
    )

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


def _load_stage_b(path: Path) -> tuple[Mapping[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RecoverySoakError("Stage-B report file cannot be read") from exc
    if not raw or len(raw) > 32 * 1024 * 1024:
        raise RecoverySoakError("Stage-B report file size is invalid")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoverySoakError("Stage-B report is not valid UTF-8 JSON") from exc
    return _mapping(parsed, "stage_b_report"), digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("observations", type=Path)
    parser.add_argument("--stage-b-report", type=Path, required=True)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
        help="ModelRig checkout root used to resolve Stage-B component evidence paths",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        observations, digest = load(args.observations)
        stage_b_report, stage_b_digest = _load_stage_b(args.stage_b_report)
        receipt = qualify(
            observations,
            observations_sha256=digest,
            stage_b_report=stage_b_report,
            stage_b_sha256=stage_b_digest,
            stage_b_repository_root=args.repository_root.resolve(),
        ).as_dict()
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
