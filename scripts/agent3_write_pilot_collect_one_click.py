#!/usr/bin/env python3
"""One-click physical completion and forensic collection for T-022.

The operator composes the existing positive and negative physical wizards on one
exact collector-branch candidate. It adds no write transport and no new evidence
judge. Before calling the established WAL-consistent forensic collector it
re-hashes every physical artifact and proves that the positive/negative sidecars
match the manifest and append-only journal exactly.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VALIDATION = ROOT / "validation"
EVIDENCE_ROOT = VALIDATION / "agent3-write-pilot-evidence"
POSITIVE_EVIDENCE_ROOT = EVIDENCE_ROOT / "positive"
NEGATIVE_EVIDENCE_ROOT = EVIDENCE_ROOT / "negative"
MANIFEST = VALIDATION / "agent3-write-pilot-manifest.json"
PREFLIGHT = VALIDATION / "agent3-write-pilot-preflight.json"
POSITIVE_OBSERVATIONS = VALIDATION / "agent3-write-pilot-positive-observations.json"
NEGATIVE_JOURNAL = VALIDATION / "agent3-write-pilot-negative-journal.db"
NEGATIVE_JSON = VALIDATION / "agent3-write-pilot-negative.json"
NEGATIVE_OBSERVATIONS = VALIDATION / "agent3-write-pilot-negative-observations.json"
RIG_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
REPORT = VALIDATION / "agent3-write-pilot-latest.json"
BRANCH = "agent/t022-write-pilot-collector"
VERSION = "1.58.146"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent3_write_pilot_negative_operator as negative_entry  # noqa: E402
import agent3_write_pilot_report as report_module  # noqa: E402

core = negative_entry.core
common = core.common
positive = core.positive
store = core.store
stage = positive.stage


class CollectorError(common.PilotEvidenceError):
    pass


def configure_candidate() -> None:
    core.BRANCH = BRANCH
    core.VERSION = VERSION
    positive.BRANCH = BRANCH
    positive.VERSION = VERSION


def _candidate_fields(
    value: Mapping[str, Any],
    identity: Mapping[str, Any],
    label: str,
) -> list[str]:
    errors: list[str] = []
    for key in ("version", "git_sha", "code_sha256", "identity_source"):
        if value.get(key) != identity.get(key):
            errors.append(f"{label}.{key} matcher ikke exact candidate")
    return errors


def _safe_relative_file(
    value: Mapping[str, Any],
    *,
    label: str,
    allowed_root: Path,
) -> Path:
    if set(value) != {"path", "sha256", "bytes"}:
        raise CollectorError(f"{label} har forkert artifact-schema")
    raw_path = value.get("path")
    digest = value.get("sha256")
    size = value.get("bytes")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise CollectorError(f"{label}.path mangler")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise CollectorError(f"{label}.sha256 er ugyldig")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise CollectorError(f"{label}.bytes er ugyldig")

    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise CollectorError(f"{label}.path forlader repositoryet")
    candidate = ROOT / relative
    cursor = ROOT
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CollectorError(f"{label} må ikke gå gennem et symlink")
    if not candidate.is_file():
        raise CollectorError(f"{label} findes ikke som regulær fil")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(allowed_root.resolve())
    except ValueError as exc:
        raise CollectorError(f"{label} ligger uden for {allowed_root}") from exc
    raw = resolved.read_bytes()
    if len(raw) != size:
        raise CollectorError(f"{label} byte-count matcher ikke sidecaren")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise CollectorError(f"{label} SHA-256 matcher ikke sidecaren")
    return resolved


def _load_positive(identity: Mapping[str, Any]) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    manifest, manifest_raw = common._load_json(MANIFEST)
    observations, _observations_raw = common._load_json(POSITIVE_OBSERVATIONS)
    errors = common.validate_manifest(manifest, require_bound=True)
    target = manifest.get("target") if isinstance(manifest.get("target"), Mapping) else {}
    errors.extend(_candidate_fields(target, identity, "manifest.target"))
    errors.extend(positive.validate_resume(observations, manifest, identity))
    if errors:
        raise CollectorError("Positive evidens er ugyldig: " + "; ".join(errors))

    runs = observations.get("runs")
    if not isinstance(runs, list) or len(runs) != common.RUN_COUNT:
        raise CollectorError("Positive observations skal indeholde præcis 20 runs")
    by_ordinal: dict[int, Mapping[str, Any]] = {}
    for item in runs:
        if not isinstance(item, Mapping):
            raise CollectorError("Positive run-observation er ikke et objekt")
        ordinal = item.get("ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal in by_ordinal:
            raise CollectorError("Positive run-ordinals er ugyldige eller dublerede")
        by_ordinal[ordinal] = item
    if set(by_ordinal) != set(range(1, common.RUN_COUNT + 1)):
        raise CollectorError("Positive run-ordinals er ikke præcis 1..20")

    preflight_ref = observations.get("preflight")
    if not isinstance(preflight_ref, Mapping):
        raise CollectorError("Positive observations mangler preflight-binding")
    if preflight_ref.get("report_path") != str(PREFLIGHT.relative_to(ROOT)):
        raise CollectorError("Positive preflight-path matcher ikke den autoritative rapport")
    preflight, _preflight_raw = common._load_json(PREFLIGHT)
    manifest_sha = common._sha_bytes(manifest_raw)
    rig_sha = target.get("rig_validation_report_sha256")
    preflight_evidence = (
        preflight.get("evidence") if isinstance(preflight.get("evidence"), Mapping) else {}
    )
    if (
        preflight.get("success") is not True
        or preflight.get("pilot_id") != manifest.get("pilot_id")
        or preflight.get("production_activation") is not False
        or preflight_ref.get("manifest_sha256") != manifest_sha
        or preflight_evidence.get("manifest_sha256") != manifest_sha
        or preflight_ref.get("rig_validation_report_sha256") != rig_sha
        or preflight_evidence.get("rig_validation_report_sha256") != rig_sha
    ):
        raise CollectorError("Positive preflight-binding er ikke exact-manifest/candidate grøn")

    devices = observations.get("devices")
    android = devices.get("android") if isinstance(devices, Mapping) else None
    windows = devices.get("windows") if isinstance(devices, Mapping) else None
    if not isinstance(android, Mapping) or not isinstance(windows, Mapping):
        raise CollectorError("Positive device-attribution mangler")
    if not _SHA256.fullmatch(str(android.get("serial_sha256") or "")):
        raise CollectorError("Android device-attribution mangler serial-hash")
    for label, value in (
        ("android.model", android.get("model")),
        ("android.os_version", android.get("os_version")),
        ("windows.device_name", windows.get("device_name")),
        ("windows.os_version", windows.get("os_version")),
    ):
        if not isinstance(value, str) or not value.strip():
            raise CollectorError(f"{label} mangler")

    for manifest_item in manifest["runs"]:
        ordinal = int(manifest_item["ordinal"])
        item = by_ordinal[ordinal]
        marker = str(manifest_item["marker"])
        run_id = str(manifest_item["run_id"])
        if (
            item.get("marker_sha256") != common._sha_text(marker)
            or item.get("run_id_sha256") != common._sha_text(run_id)
            or item.get("preview_attested") is not True
            or item.get("approval_attested") is not True
            or item.get("outcome_attested") is not True
            or item.get("production_activation") is not False
            or common._parse_time(item.get("observed_at")) is None
        ):
            raise CollectorError(f"Positive run {ordinal:02d} matcher ikke manifest/attestering")
        for field in ("preview_artifact", "approval_artifact", "outcome_artifact"):
            artifact = item.get(field)
            if not isinstance(artifact, Mapping):
                raise CollectorError(f"Positive run {ordinal:02d} mangler {field}")
            _safe_relative_file(
                artifact,
                label=f"positive[{ordinal}].{field}",
                allowed_root=POSITIVE_EVIDENCE_ROOT,
            )
    return manifest, manifest_raw, observations


def _load_negative(
    *,
    manifest: dict[str, Any],
    manifest_raw: bytes,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    observations, _observations_raw = common._load_json(NEGATIVE_OBSERVATIONS)
    errors: list[str] = []
    if observations.get("schema") != core.OBSERVATIONS_SCHEMA:
        errors.append("negative observations schema mismatch")
    if observations.get("pilot_id") != manifest.get("pilot_id"):
        errors.append("negative observations pilot_id mismatch")
    if observations.get("production_activation") is not False:
        errors.append("negative observations activated production")
    candidate = observations.get("candidate") if isinstance(observations.get("candidate"), Mapping) else {}
    errors.extend(_candidate_fields(candidate, identity, "negative.candidate"))
    if errors:
        raise CollectorError("Negative evidens er ugyldig: " + "; ".join(errors))

    negative_ref = observations.get("negative_json")
    if not isinstance(negative_ref, Mapping):
        raise CollectorError("Negative observations mangler strict negative JSON-binding")
    if negative_ref.get("path") != str(NEGATIVE_JSON.relative_to(ROOT)):
        raise CollectorError("Negative JSON-path matcher ikke den autoritative fil")
    _safe_relative_file(
        negative_ref,
        label="negative_json",
        allowed_root=VALIDATION,
    )

    _manifest, _manifest_bytes, negative, _negative_raw, journal_final = (
        report_module.load_bound_negative_evidence(
            manifest_path=MANIFEST,
            negative_path=NEGATIVE_JSON,
            negative_journal_path=NEGATIVE_JOURNAL,
        )
    )
    if observations.get("journal_final_sha256") != journal_final:
        raise CollectorError("Negative observations matcher ikke journalens final hash")
    rows, verified_final = store.verify_journal_binding(
        NEGATIVE_JOURNAL,
        manifest,
        manifest_raw,
    )
    if verified_final != journal_final:
        raise CollectorError("Negative journal-finaler er uenige")
    _meta, journal_cases = store._state(rows)
    index = core.case_index(journal_cases)

    physical_cases = observations.get("cases")
    if not isinstance(physical_cases, list) or len(physical_cases) != len(core.CASES):
        raise CollectorError("Negative observations skal indeholde præcis syv cases")
    physical_index: dict[str, Mapping[str, Any]] = {}
    for item in physical_cases:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise CollectorError("Negative physical case er ugyldig")
        name = str(item["name"])
        if name in physical_index:
            raise CollectorError(f"Negative physical case {name} er dubleret")
        physical_index[name] = item
    if set(physical_index) != set(core.CASES) or set(index) != set(core.CASES):
        raise CollectorError("Negative physical/journal case-inventory matcher ikke kontrakten")

    for name in core.CASES:
        case_id, state = index[name]
        begin = state.get("begin")
        finish = state.get("finish")
        journal_observations = state.get("observations")
        physical = physical_index[name]
        if (
            not isinstance(begin, Mapping)
            or not isinstance(finish, Mapping)
            or not isinstance(journal_observations, list)
        ):
            raise CollectorError(f"Negative journal-case {name} er ufuldstændig")
        marker = begin["payload"].get("marker")
        items = physical.get("observations")
        expected_count = core.OBSERVATION_COUNTS[name]
        if (
            not isinstance(marker, str)
            or physical.get("finished") is not True
            or physical.get("production_activation") is not False
            or physical.get("case_id_sha256") != common._sha_text(case_id)
            or physical.get("marker_sha256") != common._sha_text(marker)
            or not isinstance(items, list)
            or len(items) != expected_count
            or len(journal_observations) != expected_count
        ):
            raise CollectorError(f"Negative physical case {name} matcher ikke journalen")

        statuses: list[int] = []
        for number, (physical_item, journal_item) in enumerate(
            zip(items, journal_observations, strict=True),
            start=1,
        ):
            if not isinstance(physical_item, Mapping) or not isinstance(journal_item, Mapping):
                raise CollectorError(f"Negative {name} observation {number} er ugyldig")
            payload = journal_item.get("payload")
            screenshots = physical_item.get("screenshots")
            response = physical_item.get("response")
            if not isinstance(payload, Mapping) or not isinstance(response, Mapping):
                raise CollectorError(f"Negative {name} observation {number} mangler journal/response")
            status = payload.get("status")
            run_id = payload.get("run_id")
            if (
                physical_item.get("number") != number
                or physical_item.get("status") != status
                or physical_item.get("run_id_sha256") != common._sha_text(str(run_id))
                or physical_item.get("production_activation") is not False
                or response.get("sha256") != payload.get("response_sha256")
                or response.get("bytes") != payload.get("response_bytes")
            ):
                raise CollectorError(f"Negative {name} observation {number} matcher ikke journalen")
            statuses.append(int(status))
            _safe_relative_file(
                response,
                label=f"negative.{name}[{number}].response",
                allowed_root=NEGATIVE_EVIDENCE_ROOT,
            )
            if not isinstance(screenshots, Mapping) or set(screenshots) != {"windows", "android"}:
                raise CollectorError(f"Negative {name} observation {number} mangler begge screenshots")
            for device in ("windows", "android"):
                artifact = screenshots.get(device)
                if not isinstance(artifact, Mapping):
                    raise CollectorError(
                        f"Negative {name} observation {number} mangler {device}-artifact"
                    )
                _safe_relative_file(
                    artifact,
                    label=f"negative.{name}[{number}].{device}",
                    allowed_root=NEGATIVE_EVIDENCE_ROOT,
                )

        core.validate_statuses(name, statuses)
        begin_payload = begin["payload"]
        finish_payload = finish["payload"]
        note_before = int(begin_payload["note_count_before"])
        note_after = int(finish_payload["note_count_after"])
        approval_before = int(begin_payload["approval_use_count_before"])
        approval_after = int(finish_payload["approval_use_count_after"])
        core.validate_deltas(
            name,
            note_before=note_before,
            note_after=note_after,
            approval_before=approval_before,
            approval_after=approval_after,
        )
        if (
            physical.get("note_count_before") != note_before
            or physical.get("note_count_after") != note_after
            or physical.get("approval_use_count_before") != approval_before
            or physical.get("approval_use_count_after") != approval_after
        ):
            raise CollectorError(f"Negative physical count-binding er forkert for {name}")

    if negative.get("pilot_id") != manifest.get("pilot_id"):
        raise CollectorError("Strict negative JSON matcher ikke pilot-id")
    return observations


def _archive_rolling_report(candidate_sha: str) -> Path | None:
    if not REPORT.exists():
        return None
    if REPORT.is_symlink() or not REPORT.is_file():
        raise CollectorError("Eksisterende rolling T-022-rapport er ikke en regulær fil")
    archive = VALIDATION / "archive" / (
        time.strftime("agent3-write-pilot-report-%Y%m%d-%H%M%S-") + candidate_sha[:12]
    )
    archive.mkdir(parents=True, exist_ok=False)
    destination = archive / REPORT.name
    REPORT.replace(destination)
    stage.note(f"Tidligere rolling T-022-rapport er bevaret i {archive}")
    return destination


def _run_physical_pipeline() -> dict[str, Path]:
    captured: dict[str, Any] = {}
    original_stage = negative_entry.safe_positive_stage

    def capture_stage() -> tuple[dict[str, Any], dict[str, Any], dict[str, Path], str]:
        result = original_stage()
        captured["paths"] = result[2]
        return result

    negative_entry.safe_positive_stage = capture_stage
    try:
        result = negative_entry.main()
    finally:
        negative_entry.safe_positive_stage = original_stage
    if result != 0:
        raise CollectorError(f"Physical pipeline stoppede med exit {result}")
    paths = captured.get("paths")
    if not isinstance(paths, Mapping) or set(paths) != {"agent_db", "approval_db", "audit_db", "notes"}:
        raise CollectorError("Physical pipeline returnerede ikke de fire forensic paths")
    converted = {name: Path(value) for name, value in paths.items()}
    return converted


def _collect(paths: Mapping[str, Path]) -> dict[str, Any]:
    return report_module.collect_report(
        manifest_path=MANIFEST,
        negative_path=NEGATIVE_JSON,
        negative_journal_path=NEGATIVE_JOURNAL,
        rig_validation_path=RIG_REPORT,
        agent_db=paths["agent_db"],
        approval_db=paths["approval_db"],
        audit_db=paths["audit_db"],
        notes_path=paths["notes"],
    )


def main() -> int:
    os.chdir(ROOT)
    configure_candidate()
    stage.heading("Kaliv T-022 — samlet physical write-pilot og forensic collect")
    print("  Del 3/4: færdiggør del 1/2 på samme SHA og krydstjek al evidens read-only.")
    print("  Collector tilføjer ingen write-request, approval eller ny evidensdommer.")

    identity = positive.ensure_candidate()
    identity_map = common.candidate_identity(ROOT)
    if identity_map.get("git_sha") != identity:
        raise CollectorError("Stage-wizard og candidate identity er uenige om Git-SHA")
    _archive_rolling_report(identity)

    paths = _run_physical_pipeline()
    identity_map = common.candidate_identity(ROOT)
    manifest, manifest_raw, _positive_observations = _load_positive(identity_map)
    _load_negative(
        manifest=manifest,
        manifest_raw=manifest_raw,
        identity=identity_map,
    )

    report = _collect(paths)
    common._atomic_json(REPORT, report)
    if report.get("production_activation") is not False:
        raise CollectorError("Collector-rapporten må aldrig aktivere produktion")
    if report.get("success") is True:
        stage.heading("T-022 FORENSIC EVIDENCE: GREEN")
        stage.ok(f"Rapport: {REPORT}")
        stage.ok("20 positive runs, syv negative cases og alle ledgers matcher.")
        stage.ok("Dette er evidens — ikke merge, release eller produktionsaktivering.")
        return 0

    blockers = report.get("blockers") if isinstance(report.get("blockers"), list) else []
    stage.heading(f"T-022 FORENSIC EVIDENCE: RED ({len(blockers)} blockers)")
    for blocker in blockers:
        print(f"  - {blocker}")
    print(f"  Rød rapport er gemt i {REPORT}")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: ingen rolling grøn rapport er efterladt.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1600]}",
            file=sys.stderr,
        )
        print("  Ingen evidens auto-godkendes; produktion forbliver inaktiv.", file=sys.stderr)
        raise SystemExit(1)
