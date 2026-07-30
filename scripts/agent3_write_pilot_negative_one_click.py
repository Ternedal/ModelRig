#!/usr/bin/env python3
"""Resumable physical operator for the seven negative T-022 cases.

The wizard composes the existing positive operator and hash-chained recorder. It
never sends the adversarial request itself. The operator performs each request
through the existing clients, copies the exact response body, supplies the real
status/run id and physically attests the visible result. The recorder remains the
authoritative append-only source for before/after counts and response hashes.
"""
from __future__ import annotations

import getpass
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VALIDATION = ROOT / "validation"
MANIFEST = VALIDATION / "agent3-write-pilot-manifest.json"
POSITIVE_OBSERVATIONS = VALIDATION / "agent3-write-pilot-positive-observations.json"
JOURNAL = VALIDATION / "agent3-write-pilot-negative-journal.db"
NEGATIVE_JSON = VALIDATION / "agent3-write-pilot-negative.json"
OBSERVATIONS = VALIDATION / "agent3-write-pilot-negative-observations.json"
EVIDENCE_DIR = VALIDATION / "agent3-write-pilot-evidence" / "negative"
BRANCH = "agent/t022-write-pilot-negative-operator"
VERSION = "1.58.146"
OBSERVATIONS_SCHEMA = "kaliv-agent3-write-pilot-negative-observations/v1"
CASES = (
    "deny",
    "timeout",
    "changed_args",
    "stale_revision",
    "replay",
    "concurrent_approval",
    "stop_retry_replan",
)
OBSERVATION_COUNTS = {
    "deny": 1,
    "timeout": 1,
    "changed_args": 1,
    "stale_revision": 1,
    "replay": 1,
    "concurrent_approval": 2,
    "stop_retry_replan": 3,
}
POSITIVE_ORDINALS = {"replay": 1, "stop_retry_replan": 2}

sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise OperatorError(f"Kan ikke indlæse {path.name}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OperatorError(RuntimeError):
    pass


positive = _load(
    "t022_negative_positive_stage",
    SCRIPTS / "agent3_write_pilot_positive_one_click.py",
)
positive.BRANCH = BRANCH
positive.VERSION = VERSION
cases_module = _load(
    "t022_negative_cases",
    SCRIPTS / "agent3_write_pilot_journal_cases.py",
)
store = _load(
    "t022_negative_store",
    SCRIPTS / "agent3_write_pilot_journal_store.py",
)
forensics = _load(
    "t022_negative_forensics",
    SCRIPTS / "agent3_write_pilot_forensics.py",
)
common = _load(
    "t022_negative_common",
    SCRIPTS / "agent3_write_pilot_common.py",
)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    common._atomic_json(path, dict(value))


def prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"  {message}{suffix}: ").strip()
    return value or (default or "")


def require_phrase(case_name: str, observation: int) -> None:
    expected = f"NEGATIVE {case_name.upper()} OBS {observation} REGISTRERET"
    entered = input(f"  Skriv præcis '{expected}' for at attestere: ").strip()
    if entered != expected:
        raise OperatorError("Attesteringen matchede ikke; observationen er ikke gemt.")


def clipboard_text() -> str:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise OperatorError(f"Kunne ikke læse Windows-clipboard: {result.stderr[-500:]}")
    if not result.stdout:
        raise OperatorError("Clipboard-response body er tomt.")
    raw = result.stdout.encode("utf-8")
    if len(raw) > store.MAX_RESPONSE_BYTES:
        raise OperatorError("Clipboard-response body overstiger recorderens maksimum.")
    return result.stdout


def copy_marker(marker: str) -> None:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard -Value $env:KALIV_T022_MARKER"],
        cwd=ROOT,
        env={**os.environ, "KALIV_T022_MARKER": marker},
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise OperatorError(f"Kunne ikke kopiere marker: {result.stderr[-500:]}")


def response_artifact(case_name: str, number: int, body: str) -> dict[str, Any]:
    path = EVIDENCE_DIR / case_name / f"response-{number}.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = body.encode("utf-8")
    path.write_bytes(raw)
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def screenshot_artifacts(case_name: str, number: int, adb: str) -> dict[str, Any]:
    windows = positive.capture_windows(
        EVIDENCE_DIR / case_name / f"observation-{number}-windows.png"
    )
    android = positive.capture_android(
        adb,
        EVIDENCE_DIR / case_name / f"observation-{number}-android.png",
    )
    return {"windows": windows, "android": android}


def note_count(notes: Path, marker: str) -> int:
    if notes.is_symlink():
        raise OperatorError("notes.md må ikke være et symlink.")
    if not notes.exists():
        return 0
    raw = notes.read_bytes()
    if len(raw) > 16_000_000:
        raise OperatorError("notes.md er for stor til sikker optælling.")
    try:
        return raw.decode("utf-8").count(marker)
    except UnicodeDecodeError as exc:
        raise OperatorError("notes.md er ikke UTF-8.") from exc


def approval_count(database: Path) -> int:
    snapshot = forensics.snapshot_sqlite(database)
    try:
        return len(forensics.load_approval_rows(snapshot))
    finally:
        snapshot.unlink(missing_ok=True)


def ensure_positive_stage() -> tuple[dict[str, Any], dict[str, Any], dict[str, Path], str]:
    identity = positive.ensure_candidate()
    if not MANIFEST.is_file() or not POSITIVE_OBSERVATIONS.is_file():
        positive.main()
    manifest, _ = common._load_json(MANIFEST)
    observations, _ = common._load_json(POSITIVE_OBSERVATIONS)
    errors = common.validate_manifest(manifest, require_bound=True)
    errors.extend(positive.validate_resume(observations, manifest, identity))
    bound, pending = positive.manifest_progress(manifest)
    if pending or len(bound) != common.RUN_COUNT:
        errors.append(f"positive stage is incomplete: {len(bound)}/{common.RUN_COUNT}")
    if errors:
        raise OperatorError("Den positive del er ikke exact-candidate komplet: " + "; ".join(errors))
    token = positive.ensure_token()
    paths = positive.database_paths()
    return manifest, observations, paths, token


def journal_state(manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    if not JOURNAL.exists():
        store._init(JOURNAL, MANIFEST)
    manifest_value, manifest_raw = common._load_json(MANIFEST)
    if manifest_value.get("pilot_id") != manifest.get("pilot_id"):
        raise OperatorError("Manifestet ændrede sig under journalinitialisering.")
    rows, final_hash = store.verify_journal_binding(JOURNAL, manifest, manifest_raw)
    meta, states = store._state(rows)
    return meta, states, final_hash


def case_index(states: Mapping[str, Mapping[str, Any]]) -> dict[str, tuple[str, Mapping[str, Any]]]:
    result: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for case_id, state in states.items():
        begin = state.get("begin")
        if not isinstance(begin, Mapping):
            continue
        payload = begin.get("payload")
        if not isinstance(payload, Mapping) or not isinstance(payload.get("name"), str):
            continue
        name = str(payload["name"])
        if name in result:
            raise OperatorError(f"Journalen indeholder flere cases med navnet {name}.")
        result[name] = (case_id, state)
    return result


def new_observations(manifest: Mapping[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": OBSERVATIONS_SCHEMA,
        "pilot_id": manifest.get("pilot_id"),
        "candidate": {
            key: identity.get(key)
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "cases": [],
        "negative_json": None,
        "journal_final_sha256": None,
        "production_activation": False,
    }


def load_observations(manifest: Mapping[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    if not OBSERVATIONS.exists():
        value = new_observations(manifest, identity)
        atomic_json(OBSERVATIONS, value)
        return value
    value, _ = common._load_json(OBSERVATIONS)
    errors: list[str] = []
    if value.get("schema") != OBSERVATIONS_SCHEMA:
        errors.append("schema mismatch")
    if value.get("pilot_id") != manifest.get("pilot_id"):
        errors.append("pilot_id mismatch")
    if value.get("production_activation") is not False:
        errors.append("production activation is not false")
    candidate = value.get("candidate") if isinstance(value.get("candidate"), Mapping) else {}
    for key in ("version", "git_sha", "code_sha256", "identity_source"):
        if candidate.get(key) != identity.get(key):
            errors.append(f"candidate.{key} mismatch")
    if errors:
        raise OperatorError("Negative observations kan ikke resumes: " + "; ".join(errors))
    return value


def observed_case(observations: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    matches = [
        item
        for item in observations.get("cases", [])
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) > 1:
        raise OperatorError(f"Negative observations indeholder dublet-case {name}.")
    return matches[0] if matches else None


def validate_statuses(name: str, statuses: list[int]) -> None:
    if name == "deny" and statuses != [200]:
        raise OperatorError("deny kræver præcis status [200].")
    if name in {"timeout", "changed_args", "stale_revision", "replay"} and statuses != [409]:
        raise OperatorError(f"{name} kræver præcis status [409].")
    if name == "concurrent_approval" and sorted(statuses) != [200, 409]:
        raise OperatorError("concurrent_approval kræver én 200 og én 409.")
    if name == "stop_retry_replan" and (
        len(statuses) < 3 or any(status not in {200, 202, 409} for status in statuses)
    ):
        raise OperatorError("stop_retry_replan kræver mindst tre 200/202/409-observationer.")


def validate_deltas(
    name: str,
    *,
    note_before: int,
    note_after: int,
    approval_before: int,
    approval_after: int,
) -> None:
    note_delta = note_after - note_before
    approval_delta = approval_after - approval_before
    expected = (1, 1) if name == "concurrent_approval" else (0, 0)
    if (note_delta, approval_delta) != expected:
        raise OperatorError(
            f"{name} har forkert delta: note={note_delta}, approval={approval_delta}; "
            f"forventet {expected}."
        )


def case_instructions(name: str, marker: str) -> None:
    print(f"  Case: {name}")
    print("  Markeren er kopieret til clipboard.")
    if name == "deny":
        print("  Opret exact preview, vælg Afvis på den parrede enhed og registrér svaret.")
    elif name == "timeout":
        print("  Opret exact preview, lad confirmation udløbe uden beslutning og registrér 409.")
    elif name == "changed_args":
        print("  Opret approval til markeren, ændr args før anvendelse og registrér 409.")
    elif name == "stale_revision":
        print("  Opret approval, skift plan/revision og forsøg den gamle approval; registrér 409.")
    elif name == "replay":
        print("  Genbrug approval/run-binding mod den allerede anvendte positive marker; registrér 409.")
    elif name == "concurrent_approval":
        print("  Send to samtidige anvendelser af samme approval; registrér både 200 og 409.")
    else:
        print("  Udfør Stop plan, Retry og Replan mod samme positive marker; registrér tre svar.")
    print(f"  Marker: {marker}")
    print("  Efter hvert request: kopiér den eksakte response body til Windows-clipboard.")


def ensure_case_started(
    *,
    name: str,
    index: Mapping[str, tuple[str, Mapping[str, Any]]],
    paths: Mapping[str, Path],
) -> tuple[str, str, Mapping[str, Any]]:
    existing = index.get(name)
    if existing is not None:
        case_id, state = existing
        begin = state["begin"]["payload"]
        return case_id, str(begin["marker"]), state
    note_before = 0
    approval_before = approval_count(paths["approval_db"])
    ordinal = POSITIVE_ORDINALS.get(name)
    case_id, marker = cases_module.begin_case(
        journal=JOURNAL,
        manifest_path=MANIFEST,
        name=name,
        note_count=note_before,
        approval_count=approval_before,
        positive_ordinal=ordinal,
    )
    rows, _ = store.verify_journal(JOURNAL)
    _meta, states = store._state(rows)
    return case_id, marker, states[case_id]


def record_observation(
    *,
    name: str,
    number: int,
    case_id: str,
    adb: str,
) -> dict[str, Any]:
    raw_status = prompt("HTTP-status fra det faktiske request")
    try:
        status = int(raw_status)
    except ValueError as exc:
        raise OperatorError("HTTP-status skal være et heltal.") from exc
    body = clipboard_text()
    response = response_artifact(name, number, body)
    run_id = getpass.getpass("  Indsæt involveret run-id (skjult): ").strip()
    if not run_id:
        raise OperatorError("Run-id er tomt.")
    cases_module.observe_request(
        journal=JOURNAL,
        case_id=case_id,
        status=status,
        response_path=ROOT / response["path"],
        run_id=run_id,
    )
    screenshots = screenshot_artifacts(name, number, adb)
    require_phrase(name, number)
    result = {
        "number": number,
        "status": status,
        "response": response,
        "run_id_sha256": common._sha_text(run_id),
        "screenshots": screenshots,
        "production_activation": False,
    }
    del run_id
    return result


def run_case(
    *,
    name: str,
    manifest: dict[str, Any],
    observations: dict[str, Any],
    paths: Mapping[str, Path],
    adb: str,
) -> None:
    _meta, states, _final = journal_state(manifest)
    index = case_index(states)
    if name in index and index[name][1].get("finish") is not None:
        if observed_case(observations, name) is None:
            raise OperatorError(f"Journalen siger {name} er færdig, men fysisk observation mangler.")
        positive.stage.ok(f"Resume: {name} er allerede færdig.")
        return
    case_id, marker, state = ensure_case_started(name=name, index=index, paths=paths)
    copy_marker(marker)
    positive.launch_desktop()
    adb_path = positive.find_adb()
    positive.launch_android(adb_path)
    positive.stage.heading(f"T-022 NEGATIV CASE — {name}")
    case_instructions(name, marker)

    existing_observations = list(state.get("observations") or [])
    physical = observed_case(observations, name)
    physical_items = list(physical.get("observations") or []) if physical else []
    if len(existing_observations) != len(physical_items):
        raise OperatorError(f"Resume-paritet fejler for {name}: journal og screenshots er uenige.")
    required = OBSERVATION_COUNTS[name]
    for number in range(len(existing_observations) + 1, required + 1):
        input("  Udfør requestet, kopiér exact response body, og tryk Enter: ")
        physical_items.append(
            record_observation(name=name, number=number, case_id=case_id, adb=adb)
        )
        if physical is None:
            physical = {
                "name": name,
                "case_id_sha256": common._sha_text(case_id),
                "marker_sha256": common._sha_text(marker),
                "observations": physical_items,
                "finished": False,
                "production_activation": False,
            }
            observations["cases"].append(physical)
        else:
            physical["observations"] = physical_items
        atomic_json(OBSERVATIONS, observations)

    statuses = [int(item["status"]) for item in physical_items]
    validate_statuses(name, statuses)
    rows, _ = store.verify_journal(JOURNAL)
    _meta, fresh_states = store._state(rows)
    fresh = fresh_states[case_id]
    begin = fresh["begin"]["payload"]
    note_after = note_count(paths["notes"], marker)
    approval_after = approval_count(paths["approval_db"])
    validate_deltas(
        name,
        note_before=int(begin["note_count_before"]),
        note_after=note_after,
        approval_before=int(begin["approval_use_count_before"]),
        approval_after=approval_after,
    )
    cases_module.finish_case(
        journal=JOURNAL,
        case_id=case_id,
        note_count=note_after,
        approval_count=approval_after,
    )
    physical["finished"] = True
    physical["note_count_before"] = int(begin["note_count_before"])
    physical["note_count_after"] = note_after
    physical["approval_use_count_before"] = int(begin["approval_use_count_before"])
    physical["approval_use_count_after"] = approval_after
    atomic_json(OBSERVATIONS, observations)
    positive.stage.ok(f"{name} er færdig og hashkædet.")


def finalize(manifest: dict[str, Any], observations: dict[str, Any]) -> None:
    negative = cases_module.finalize(JOURNAL, MANIFEST)
    atomic_json(NEGATIVE_JSON, negative)
    rows, final_hash = store.verify_journal(JOURNAL)
    _meta, states = store._state(rows)
    finished = {
        state["begin"]["payload"]["name"]
        for state in states.values()
        if state.get("begin") is not None and state.get("finish") is not None
    }
    if finished != set(CASES):
        raise OperatorError(f"Journalens færdige cases matcher ikke kontrakten: {sorted(finished)}")
    observations["negative_json"] = {
        "path": str(NEGATIVE_JSON.relative_to(ROOT)),
        "sha256": hashlib.sha256(NEGATIVE_JSON.read_bytes()).hexdigest(),
        "bytes": NEGATIVE_JSON.stat().st_size,
    }
    observations["journal_final_sha256"] = final_hash
    observations["production_activation"] = False
    atomic_json(OBSERVATIONS, observations)


def main() -> int:
    os.chdir(ROOT)
    positive.stage.heading("Kaliv T-022 — negativ physical recorder-wizard")
    print("  Del 2/4: syv adversarial cases i den eksisterende hashkædede recorder.")
    print("  Wizard'en sender ingen adversarial request og godkender intet automatisk.")
    print("  Del 1 genbruges med branch-override, så hele piloten bindes til samme SHA.")

    manifest, _positive_obs, paths, _token = ensure_positive_stage()
    identity = common.candidate_identity(ROOT)
    observations = load_observations(manifest, identity)
    adb = positive.find_adb()
    positive.build_install_android(adb)

    journal_state(manifest)
    for name in CASES:
        run_case(
            name=name,
            manifest=manifest,
            observations=observations,
            paths=paths,
            adb=adb,
        )
    finalize(manifest, observations)

    positive.stage.heading("DEL 2 FÆRDIG — SYV NEGATIVE CASES HASHKÆDET")
    positive.stage.ok(f"Journal: {JOURNAL}")
    positive.stage.ok(f"Strict negative JSON: {NEGATIVE_JSON}")
    positive.stage.ok(f"Fysiske observationer: {OBSERVATIONS}")
    positive.stage.ok("Næste del er forensic collect; T-022 er endnu ikke grøn.")
    positive.stage.ok("production_activation=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: journal og fysiske observationer er bevaret.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1200]}",
            file=sys.stderr,
        )
        print("  Ingen case auto-godkendes; hashkæden bevares.", file=sys.stderr)
        raise SystemExit(1)
