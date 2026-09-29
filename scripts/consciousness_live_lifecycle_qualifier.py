#!/usr/bin/env python3
"""Fail-closed qualifier for the consciousness_live_lifecycle release gate.

The qualifier combines three already-bounded evidence classes for one exact
ModelRig candidate SHA:

1. a successful live cognitive cycle;
2. dormancy/restart followed by explicit wake reorientation;
3. a ThoughtEngine/CognitiveProfile swap that preserves identity continuity.

It grants no runtime authority and can never activate production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "kaliv-consciousness-core/live-lifecycle-evidence/v1"
VERDICT_SCHEMA = "kaliv-consciousness-core/live-lifecycle-verdict/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class LiveLifecycleQualificationError(RuntimeError):
    pass


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LiveLifecycleQualificationError(f"{name} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise LiveLifecycleQualificationError(
            f"{name} has invalid fields: {'; '.join(detail)}"
        )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:" + hashlib.sha256(_canonical(value)).hexdigest()


def _candidate_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise LiveLifecycleQualificationError(
            f"{name} must be a lowercase 40-hex Git SHA"
        )
    return value


def _require_false(value: Mapping[str, Any], fields: Sequence[str], name: str) -> None:
    for field in fields:
        if value.get(field) is not False:
            raise LiveLifecycleQualificationError(f"{name} overclaimed {field}")


def _validate_live_cycle(value: Any, candidate_sha: str) -> tuple[str, Mapping[str, Any]]:
    report = _mapping(value, "live_cycle")
    if report.get("schema") != "kaliv-consciousness-core/live-cycle-probe/v1":
        raise LiveLifecycleQualificationError("live_cycle schema mismatch")
    candidate = _mapping(report.get("candidate"), "live_cycle.candidate")
    if candidate.get("git_sha") != candidate_sha:
        raise LiveLifecycleQualificationError(
            "live_cycle candidate Git SHA does not match lifecycle candidate"
        )
    if candidate.get("working_tree_clean") is not True:
        raise LiveLifecycleQualificationError("live_cycle candidate was not clean")

    gate = _mapping(report.get("gate"), "live_cycle.gate")
    for field in ("passed", "live_cycle_proven"):
        if gate.get(field) is not True:
            raise LiveLifecycleQualificationError(
                f"live_cycle did not prove {field}"
            )
    for field in (
        "full_lifecycle_qualified",
        "model_swap_qualified",
        "dormancy_restart_qualified",
        "release_gate_satisfied",
        "production_activation",
    ):
        if gate.get(field) is not False:
            raise LiveLifecycleQualificationError(
                f"live_cycle unexpectedly claimed {field}"
            )

    authority = _mapping(report.get("authority"), "live_cycle.authority")
    _require_false(
        authority,
        (
            "automatic_repeat",
            "internal_thread_created",
            "internal_timer_created",
            "durable_memory_write_authority",
            "execution_authority",
            "scheduling_authority",
            "production_activation",
        ),
        "live_cycle.authority",
    )
    cycle = _mapping(report.get("cycle"), "live_cycle.cycle")
    if cycle.get("decision") != "RUN" or cycle.get("model_calls") != 1:
        raise LiveLifecycleQualificationError(
            "live_cycle must contain one successful RUN with exactly one model call"
        )
    return _ref("live-cycle-evidence", report), report


def _validate_dormancy_restart(
    value: Any,
    candidate_sha: str,
) -> tuple[str, Mapping[str, Any]]:
    envelope = _mapping(value, "dormancy_restart")
    _exact_keys(
        envelope,
        {"candidate_git_sha", "restart_proven", "receipt"},
        "dormancy_restart",
    )
    if envelope["candidate_git_sha"] != candidate_sha:
        raise LiveLifecycleQualificationError(
            "dormancy_restart candidate Git SHA does not match lifecycle candidate"
        )
    if envelope["restart_proven"] is not True:
        raise LiveLifecycleQualificationError(
            "dormancy_restart must explicitly prove process restart"
        )
    receipt = _mapping(envelope["receipt"], "dormancy_restart.receipt")
    if receipt.get("schema") != "kaliv-consciousness-core/dormancy-bridge-receipt/v1":
        raise LiveLifecycleQualificationError("dormancy bridge schema mismatch")
    if receipt.get("cognition_during_gap") is not False:
        raise LiveLifecycleQualificationError(
            "dormancy bridge claimed cognition during the gap"
        )
    if receipt.get("explicit_wake_reorientation") is not True:
        raise LiveLifecycleQualificationError(
            "dormancy bridge lacks explicit wake reorientation"
        )
    if receipt.get("reference_only") is not True:
        raise LiveLifecycleQualificationError(
            "dormancy bridge must remain reference-only"
        )
    _require_false(
        receipt,
        (
            "automatic_goal_resume",
            "automatic_loop_resume",
            "identity_authority",
            "persistent_state_authority",
            "durable_memory_write_authority",
            "execution_authority",
            "scheduling_authority",
            "model_authority",
            "raw_chain_of_thought_persisted",
            "production_activation",
        ),
        "dormancy_restart.receipt",
    )
    return _ref("dormancy-restart-evidence", envelope), receipt


def _validate_model_swap(
    value: Any,
    candidate_sha: str,
) -> tuple[str, Mapping[str, Any]]:
    envelope = _mapping(value, "model_swap")
    _exact_keys(envelope, {"candidate_git_sha", "receipt"}, "model_swap")
    if envelope["candidate_git_sha"] != candidate_sha:
        raise LiveLifecycleQualificationError(
            "model_swap candidate Git SHA does not match lifecycle candidate"
        )
    receipt = _mapping(envelope["receipt"], "model_swap.receipt")
    if receipt.get("schema") != (
        "kaliv-consciousness-core/model-swap-continuity-receipt/v1"
    ):
        raise LiveLifecycleQualificationError("model-swap receipt schema mismatch")
    for field in (
        "cognitive_profile_changed",
        "identity_preserved",
        "person_binding_preserved",
        "self_state_preserved",
        "durable_memory_binding_preserved",
        "continuity_preserved",
    ):
        if receipt.get(field) is not True:
            raise LiveLifecycleQualificationError(
                f"model_swap did not prove {field}"
            )

    from_profile = receipt.get("from_cognitive_profile_ref")
    to_profile = receipt.get("to_cognitive_profile_ref")
    if (
        not isinstance(from_profile, str)
        or not from_profile
        or not isinstance(to_profile, str)
        or not to_profile
    ):
        raise LiveLifecycleQualificationError(
            "model_swap cognitive profile refs must be non-empty strings"
        )
    if from_profile == to_profile:
        raise LiveLifecycleQualificationError(
            "model_swap cognitive profile refs did not actually change"
        )
    _require_false(
        receipt,
        (
            "raw_chain_of_thought_persisted",
            "identity_authority",
            "persistent_state_authority",
            "durable_memory_write_authority",
            "execution_authority",
            "scheduling_authority",
            "model_authority",
            "production_activation",
        ),
        "model_swap.receipt",
    )
    return _ref("model-swap-evidence", envelope), receipt


def qualify(value: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(value, "evidence")
    _exact_keys(
        root,
        {
            "schema",
            "candidate_git_sha",
            "live_cycle",
            "dormancy_restart",
            "model_swap",
            "production_activation",
        },
        "evidence",
    )
    if root["schema"] != SCHEMA:
        raise LiveLifecycleQualificationError("unsupported lifecycle evidence schema")
    candidate_sha = _candidate_sha(root["candidate_git_sha"], "candidate_git_sha")
    if root["production_activation"] is not False:
        raise LiveLifecycleQualificationError(
            "live lifecycle qualification cannot activate production"
        )

    live_ref, _live = _validate_live_cycle(root["live_cycle"], candidate_sha)
    dormancy_ref, dormancy = _validate_dormancy_restart(
        root["dormancy_restart"], candidate_sha
    )
    model_ref, model = _validate_model_swap(root["model_swap"], candidate_sha)

    if dormancy.get("self_id") != model.get("self_id"):
        raise LiveLifecycleQualificationError(
            "dormancy and model-swap evidence belong to different Self identities"
        )
    if dormancy.get("person_revision") != model.get("person_revision"):
        raise LiveLifecycleQualificationError(
            "dormancy and model-swap evidence belong to different Person revisions"
        )

    evidence_refs = [live_ref, dormancy_ref, model_ref]
    qualification_id = "live-lifecycle-" + hashlib.sha256(
        _canonical(
            {
                "candidate_git_sha": candidate_sha,
                "evidence_refs": evidence_refs,
                "self_id": model.get("self_id"),
                "person_revision": model.get("person_revision"),
            }
        )
    ).hexdigest()[:32]

    return {
        "schema": VERDICT_SCHEMA,
        "qualification_id": qualification_id,
        "candidate_git_sha": candidate_sha,
        "state": "QUALIFIED",
        "evidence_refs": evidence_refs,
        "live_cycle_qualified": True,
        "dormancy_restart_qualified": True,
        "model_swap_qualified": True,
        "identity_lineage_preserved": True,
        "full_lifecycle_qualified": True,
        "consciousness_live_lifecycle_gate_satisfied": True,
        "raw_chain_of_thought_persisted": False,
        "identity_authority": False,
        "persistent_state_authority": False,
        "durable_memory_write_authority": False,
        "execution_authority": False,
        "scheduling_authority": False,
        "model_authority": False,
        "production_activation": False,
    }


def load(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LiveLifecycleQualificationError("evidence file cannot be read") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise LiveLifecycleQualificationError("evidence file is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveLifecycleQualificationError(
            "evidence file is not valid UTF-8 JSON"
        ) from exc
    return _mapping(value, "evidence")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        verdict = qualify(load(args.evidence))
    except LiveLifecycleQualificationError as exc:
        verdict = {
            "schema": VERDICT_SCHEMA,
            "state": "INVALID",
            "full_lifecycle_qualified": False,
            "consciousness_live_lifecycle_gate_satisfied": False,
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
