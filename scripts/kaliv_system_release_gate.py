#!/usr/bin/env python3
"""Fail-closed cross-repository Kaliv system release qualification.

This gate binds a release candidate to exact Git commit SHAs for the core rigs
and to explicit evidence for the physical/runtime gates that repository CI
cannot prove. It never activates production and never treats CI as a substitute
for physical or human acceptance.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "kaliv-system-release-manifest/v1"
VERDICT_SCHEMA = "kaliv-system-release-verdict/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_ID = re.compile(r"^kaliv-rc-[A-Za-z0-9._-]{1,64}$")
_ANDROID_LIVE_BODY_REF = re.compile(
    r"^kaliv-body-android-physical-gate:([0-9a-f]{40}):([0-9a-f]{64})$"
)
_CONSCIOUSNESS_LIFECYCLE_REF = re.compile(
    r"^consciousness-live-lifecycle:([0-9a-f]{40}):([0-9a-f]{64})$"
)
_VISIONRIG_PHYSICAL_REF = re.compile(
    r"^visionrig-physical-perception:([0-9a-f]{40}):([0-9a-f]{64})$"
)
_END_TO_END_LATENCY_REF = re.compile(
    r"^kaliv-end-to-end-latency:([0-9a-f]{40}):([0-9a-f]{64})$"
)

REQUIRED_REPOSITORIES = (
    "Ternedal/ModelRig",
    "Ternedal/BodyRig",
    "Ternedal/VisionRig",
    "Ternedal/VoiceRig",
)

REQUIRED_GATES = (
    "software_exact_green",
    "consciousness_live_lifecycle",
    "visionrig_physical_perception",
    "bodyrig_photoreal_likeness",
    "bodyrig_digital_twin_m6",
    "bodyrig_android_live_body",
    "end_to_end_latency",
    "recovery_soak",
    "repository_authority",
)

_ALLOWED_STATUS = {"PASS", "PENDING", "FAIL"}
_MAX_EVIDENCE_REFS = 32
_MAX_REF_LEN = 512


class SystemReleaseManifestError(RuntimeError):
    """The supplied release manifest is malformed or overclaims authority."""


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemReleaseManifestError(
            "cannot verify ModelRig evidence ancestry/tree equivalence"
        ) from exc
    return result.stdout.strip()


def _modelrig_evidence_matches_pin(evidence_sha: str, pinned_sha: str) -> bool:
    if evidence_sha == pinned_sha:
        return True

    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", evidence_sha, pinned_sha],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError:
        # Non-ancestor and unknown/unavailable commit objects are both
        # non-equivalent evidence. Fail closed without converting this into an
        # infrastructure authority error.
        return False
    except OSError as exc:
        raise SystemReleaseManifestError(
            "cannot verify ModelRig evidence ancestry"
        ) from exc

    evidence_tree = _git("rev-parse", f"{evidence_sha}^{{tree}}")
    pinned_tree = _git("rev-parse", f"{pinned_sha}^{{tree}}")
    return evidence_tree == pinned_tree


@dataclass(frozen=True)
class SystemReleaseVerdict:
    schema: str
    release_id: str
    state: str
    release_ready: bool
    production_activation: bool
    pinned_repositories: dict[str, str]
    pending_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "release_id": self.release_id,
            "state": self.state,
            "release_ready": self.release_ready,
            "production_activation": self.production_activation,
            "pinned_repositories": dict(self.pinned_repositories),
            "pending_gates": list(self.pending_gates),
            "failed_gates": list(self.failed_gates),
        }


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SystemReleaseManifestError(f"{name} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    keys = set(value)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise SystemReleaseManifestError(f"{name} has invalid fields: {'; '.join(detail)}")


def _validate_repositories(value: Any) -> dict[str, str]:
    if not isinstance(value, list) or not value:
        raise SystemReleaseManifestError("repositories must be a non-empty list")

    pinned: dict[str, str] = {}
    for index, raw in enumerate(value):
        item = _require_mapping(raw, f"repositories[{index}]")
        _exact_keys(item, {"repository", "git_sha"}, f"repositories[{index}]")
        repository = item["repository"]
        git_sha = item["git_sha"]
        if not isinstance(repository, str) or not repository.strip():
            raise SystemReleaseManifestError(
                f"repositories[{index}].repository must be nonblank"
            )
        repository = repository.strip()
        if repository in pinned:
            raise SystemReleaseManifestError(f"duplicate repository pin: {repository}")
        if not isinstance(git_sha, str) or _SHA40.fullmatch(git_sha) is None:
            raise SystemReleaseManifestError(
                f"{repository} must be pinned to a lowercase 40-hex Git SHA"
            )
        pinned[repository] = git_sha

    missing = [name for name in REQUIRED_REPOSITORIES if name not in pinned]
    if missing:
        raise SystemReleaseManifestError(
            "missing required repository pins: " + ", ".join(missing)
        )
    return pinned


def _validate_evidence_refs(value: Any, gate: str, *, require: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > _MAX_EVIDENCE_REFS:
        raise SystemReleaseManifestError(
            f"{gate}.evidence_refs must be a bounded list"
        )
    refs: list[str] = []
    for index, ref in enumerate(value):
        if (
            not isinstance(ref, str)
            or not ref.strip()
            or len(ref.strip()) > _MAX_REF_LEN
        ):
            raise SystemReleaseManifestError(
                f"{gate}.evidence_refs[{index}] must be a bounded nonblank reference"
            )
        refs.append(ref.strip())
    if len(set(refs)) != len(refs):
        raise SystemReleaseManifestError(f"{gate}.evidence_refs contains duplicates")
    if require and not refs:
        raise SystemReleaseManifestError(
            f"{gate} cannot PASS without explicit evidence"
        )
    return tuple(refs)


def _validate_gates(
    value: Any,
    *,
    modelrig_sha: str,
    visionrig_sha: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    gates = _require_mapping(value, "gates")
    expected = set(REQUIRED_GATES)
    _exact_keys(gates, expected, "gates")

    pending: list[str] = []
    failed: list[str] = []
    for gate in REQUIRED_GATES:
        entry = _require_mapping(gates[gate], gate)
        _exact_keys(entry, {"status", "evidence_refs"}, gate)
        status = entry["status"]
        if status not in _ALLOWED_STATUS:
            raise SystemReleaseManifestError(
                f"{gate}.status must be PASS, PENDING or FAIL"
            )
        refs = _validate_evidence_refs(
            entry["evidence_refs"],
            gate,
            require=status == "PASS",
        )
        if gate == "consciousness_live_lifecycle" and status == "PASS":
            if len(refs) != 1:
                raise SystemReleaseManifestError(
                    "consciousness_live_lifecycle PASS requires exactly one "
                    "lifecycle qualification evidence ref"
                )
            match = _CONSCIOUSNESS_LIFECYCLE_REF.fullmatch(refs[0])
            if match is None:
                raise SystemReleaseManifestError(
                    "consciousness_live_lifecycle PASS requires exact-head-bound "
                    "consciousness-live-lifecycle evidence"
                )
            if not _modelrig_evidence_matches_pin(match.group(1), modelrig_sha):
                raise SystemReleaseManifestError(
                    "consciousness_live_lifecycle evidence is not exact-tree-equivalent "
                    "to the pinned ModelRig revision"
                )
        if gate == "visionrig_physical_perception" and status == "PASS":
            if len(refs) != 1:
                raise SystemReleaseManifestError(
                    "visionrig_physical_perception PASS requires exactly one "
                    "physical qualification evidence ref"
                )
            match = _VISIONRIG_PHYSICAL_REF.fullmatch(refs[0])
            if match is None:
                raise SystemReleaseManifestError(
                    "visionrig_physical_perception PASS requires exact-head-bound "
                    "visionrig-physical-perception evidence"
                )
            if match.group(1) != visionrig_sha:
                raise SystemReleaseManifestError(
                    "visionrig_physical_perception evidence is bound to a different "
                    "VisionRig Git SHA"
                )
        if gate == "bodyrig_android_live_body" and status == "PASS":
            if len(refs) != 1:
                raise SystemReleaseManifestError(
                    "bodyrig_android_live_body PASS requires exactly one "
                    "independent physical gate evidence ref"
                )
            match = _ANDROID_LIVE_BODY_REF.fullmatch(refs[0])
            if match is None:
                raise SystemReleaseManifestError(
                    "bodyrig_android_live_body PASS requires exact-head-bound "
                    "kaliv-body-android-physical-gate evidence refs"
                )
            if not _modelrig_evidence_matches_pin(match.group(1), modelrig_sha):
                raise SystemReleaseManifestError(
                    "bodyrig_android_live_body evidence is not exact-tree-equivalent "
                    "to the pinned ModelRig revision"
                )
        if gate == "end_to_end_latency" and status == "PASS":
            if len(refs) != 1:
                raise SystemReleaseManifestError(
                    "end_to_end_latency PASS requires exactly one "
                    "measurement qualification evidence ref"
                )
            match = _END_TO_END_LATENCY_REF.fullmatch(refs[0])
            if match is None:
                raise SystemReleaseManifestError(
                    "end_to_end_latency PASS requires exact-head-bound "
                    "kaliv-end-to-end-latency evidence"
                )
            if not _modelrig_evidence_matches_pin(match.group(1), modelrig_sha):
                raise SystemReleaseManifestError(
                    "end_to_end_latency evidence is not exact-tree-equivalent "
                    "to the pinned ModelRig revision"
                )
        if status == "PENDING":
            pending.append(gate)
        elif status == "FAIL":
            failed.append(gate)
    return tuple(pending), tuple(failed)


def evaluate_manifest(manifest: Mapping[str, Any]) -> SystemReleaseVerdict:
    root = _require_mapping(manifest, "manifest")
    _exact_keys(
        root,
        {
            "schema",
            "release_id",
            "repositories",
            "gates",
            "production_activation",
        },
        "manifest",
    )

    if root["schema"] != SCHEMA:
        raise SystemReleaseManifestError("unsupported release manifest schema")
    release_id = root["release_id"]
    if not isinstance(release_id, str) or _RELEASE_ID.fullmatch(release_id) is None:
        raise SystemReleaseManifestError("release_id must be kaliv-rc-<bounded-id>")

    # This qualification surface deliberately cannot activate production.
    if root["production_activation"] is not False:
        raise SystemReleaseManifestError(
            "system release qualification cannot activate production"
        )

    pinned = _validate_repositories(root["repositories"])
    pending, failed = _validate_gates(
        root["gates"],
        modelrig_sha=pinned["Ternedal/ModelRig"],
        visionrig_sha=pinned["Ternedal/VisionRig"],
    )
    ready = not pending and not failed
    return SystemReleaseVerdict(
        schema=VERDICT_SCHEMA,
        release_id=release_id,
        state="QUALIFIED" if ready else "BLOCKED",
        release_ready=ready,
        production_activation=False,
        pinned_repositories=pinned,
        pending_gates=pending,
        failed_gates=failed,
    )


def load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SystemReleaseManifestError("release manifest cannot be read") from exc
    if len(raw) > 1024 * 1024:
        raise SystemReleaseManifestError("release manifest is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemReleaseManifestError("release manifest is not valid UTF-8 JSON") from exc
    return _require_mapping(value, "manifest")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        verdict = evaluate_manifest(load_manifest(args.manifest))
    except SystemReleaseManifestError as exc:
        print(json.dumps({"schema": VERDICT_SCHEMA, "state": "INVALID", "error": str(exc)}))
        return 2
    print(json.dumps(verdict.as_dict(), indent=2, sort_keys=True))
    return 0 if verdict.release_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
