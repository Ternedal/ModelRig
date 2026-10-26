#!/usr/bin/env python3
"""Guided Pixel observations for what changed in voice after v2.0.15.

The five Stage A trials (stage_a_voice_observations.py) cover interruption:
stop, barge-in, network loss. They were written before v2.0.16-2.0.18 and
before the cloud rule of 2026-10-26, so they do not observe:

  change-01  local voice keeps conversation context        (#2224, v2.0.16)
  change-02  cloud voice receives the current turn only     (#2248, D5)
  change-03  completed voice turns survive an app restart   (#2243, v2.0.18)
  change-04  a finished turn ends in idle, not a hang       (#2242, v2.0.18)

Cold start (#2240/#2251) is already measured by voice_baseline.py in the same
launcher and is not repeated here.

Same rules as the Stage A collector it reuses: the operator performs every
trial, answers are saved after each one, the file is bound to the exact
candidate, and nothing is ever guessed or marked green automatically. A trial
the operator cannot run (no cloud key on the phone) is recorded as not_run,
which makes the whole result INCOMPLETE, never PASS.

Exit codes: 0 PASS, 1 FAIL, 2 safe stop on error, 3 INCOMPLETE (some trial
not run). The launcher keeps going on 3, so the cold-start baseline is not lost
because the phone lacks a cloud key, and it reports the incomplete result last.
"""
from __future__ import annotations

import argparse
import importlib.util
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kaliv-voice-change-observations/v1"
STATE_SCHEMA = "kaliv-voice-change-observations-state/v1"
DEFAULT_PHONE_STATE = Path("validation/stage-a-runtime/phone-test-state.json")
DEFAULT_MANUAL = Path("validation/voice-manual-observations.json")
DEFAULT_RESUME = Path("validation/voice-change-observations-state.json")
DEFAULT_OUTPUT = Path("validation/voice-change-observations.json")

RESULTS = ("pass", "fail", "not_run")

# Ordinary Danish nouns: easy to say and for ASR to hear, unlikely to be guessed.
WORDS = (
    "agurk", "ballon", "citron", "delfin", "elefant", "fyrtårn", "giraf",
    "harmonika", "isbjørn", "jordbær", "kanin", "lommelygte", "marmelade",
    "næsehorn", "ostehøvl", "papegøje", "regnbue", "sommerfugl", "trompet",
    "ugle", "vandmelon", "zebra", "æblekage", "østers",
)

TRIALS: tuple[dict[str, Any], ...] = (
    {
        "id": "change-01",
        "change": "#2224 local voice conversation context",
        "title": "Lokal voice husker forrige tur",
        "needs_word": True,
        "instruction": (
            "Kontrollér at cloud er SLÅET FRA i Kaliv.\n"
            "  1. Sig: \"Mit testord er {word}.\" Vent på svaret.\n"
            "  2. Sig: \"Hvad var mit testord?\""
        ),
        "question": "Sagde Kaliv '{word}' i svaret på spørgsmål 2? [J/N]",
        "expected": True,
    },
    {
        "id": "change-02",
        "change": "#2248 cloud voice receives the current turn only (D5)",
        "title": "Cloud-voice kender IKKE forrige tur",
        "needs_word": True,
        "cloud": True,
        "instruction": (
            "Slå cloud TIL i Kaliv (kræver en Ollama Cloud-nøgle).\n"
            "  1. Sig: \"Mit testord er {word}.\" Vent på svaret.\n"
            "  2. Sig: \"Hvad var mit testord?\"\n"
            "  Forventet: Kaliv kender det IKKE. Kun den aktuelle tur må gå til cloud."
        ),
        "question": "Sagde Kaliv '{word}' i svaret på spørgsmål 2? [J/N]",
        "expected": False,
        # A non-recall only means something if the cloud actually answered: a bad
        # key or a failed request also "does not know" the word. Without a real
        # cloud answer to both turns the privacy property was not observed.
        "preconditions": (
            ("Har Kaliv-appen en Ollama Cloud-nøgle, så cloud kan slås til? [J/N]",
             "ingen Ollama Cloud-nøgle på telefonen"),
            ("Kom der et rigtigt svar på BEGGE spørgsmål, markeret som cloud-svar i appen "
             "(ikke en fejlmeddelelse)? [J/N]",
             "cloud svarede ikke på begge ture; privatlivsegenskaben blev ikke observeret"),
        ),
    },
    {
        "id": "change-03",
        "change": "#2243 completed voice turns are persisted atomically",
        "title": "Voice-ture overlever genstart af appen",
        "instruction": (
            "Luk Kaliv HELT (stryg appen væk fra seneste apps), og åbn den igen."
        ),
        "question": "Står de seneste voice-ture stadig i samtalen, med både spørgsmål og svar? [J/N]",
        "expected": True,
    },
    {
        "id": "change-04",
        "change": "#2242 a finished voice turn ends on the terminal event",
        "title": "En færdig tur ender i ro, ikke i et hæng",
        "instruction": (
            "Stil et kort spørgsmål med cloud SLÅET FRA, og lad svaret spille helt færdigt."
        ),
        "question": (
            "Var Kaliv klar til næste spørgsmål inden for få sekunder, uden at hænge i "
            "'tænker' eller 'taler'? [J/N]"
        ),
        "expected": True,
    },
)


class ChangeObservationError(RuntimeError):
    pass


def _base():
    """The Stage A collector: same candidate binding, prompts and atomic writes."""
    path = ROOT / "scripts" / "stage_a_voice_observations.py"
    spec = importlib.util.spec_from_file_location("voice_change_stage_a_base", path)
    if spec is None or spec.loader is None:
        raise ChangeObservationError("Stage A-voice-observationerne kunne ikke indlæses")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pick_words(count: int = 2) -> list[str]:
    """Distinct words, so the cloud trial cannot pass on the local trial's word."""
    pool = list(WORDS)
    chosen: list[str] = []
    while len(chosen) < count:
        chosen.append(pool.pop(secrets.randbelow(len(pool))))
    return chosen


def trial_record(spec: dict[str, Any], *, ran: bool, observed: bool | None,
                 word: str | None = None, reason: str | None = None) -> dict[str, Any]:
    """One stored trial. ``observed`` is the operator's literal J/N answer."""
    if not ran:
        if observed is not None:
            raise ChangeObservationError("et forsøg, der ikke blev kørt, kan ikke have et svar")
        if not reason:
            raise ChangeObservationError("et forsøg, der ikke blev kørt, kræver en begrundelse")
        result = "not_run"
    elif observed is None:
        raise ChangeObservationError("et kørt forsøg kræver et J/N-svar")
    else:
        result = "pass" if observed is spec["expected"] else "fail"
    record: dict[str, Any] = {
        "id": spec["id"],
        "change": spec["change"],
        "expected": spec["expected"],
        "observed": observed,
        "result": result,
    }
    if word is not None:
        record["word"] = word
    if reason:
        record["not_run_reason"] = reason
    return record


def summarize(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """PASS only when every expected trial ran and passed. Unknown never becomes PASS."""
    expected_ids = [spec["id"] for spec in TRIALS]
    ids = [t.get("id") for t in trials if isinstance(t, dict)]
    results = [t.get("result") for t in trials if isinstance(t, dict)]
    if ids != expected_ids or any(r not in RESULTS for r in results):
        status = "INVALID"
    elif "fail" in results:
        status = "FAIL"
    elif "not_run" in results:
        status = "INCOMPLETE"
    else:
        status = "PASS"
    return {
        "status": status,
        "trials": len(trials),
        "passed": sum(r == "pass" for r in results),
        "failed": sum(r == "fail" for r in results),
        "not_run": sum(r == "not_run" for r in results),
    }


def validate(value: Any, candidate: dict[str, str] | None = None) -> dict[str, Any]:
    """Structural check of a stored report; returns its summary."""
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ChangeObservationError("forkert eller manglende schema")
    if value.get("production_activation") is not False:
        raise ChangeObservationError("rapporten bevarer ikke production_activation=false")
    if candidate is not None and value.get("candidate") != candidate:
        raise ChangeObservationError("rapporten er bundet til en anden kandidat end denne checkout")
    trials = value.get("trials")
    if not isinstance(trials, list):
        raise ChangeObservationError("trials mangler")
    specs = {spec["id"]: spec for spec in TRIALS}
    for trial in trials:
        spec = specs.get(trial.get("id")) if isinstance(trial, dict) else None
        if spec is None:
            raise ChangeObservationError("ukendt forsøg i rapporten")
        recomputed = trial_record(
            spec,
            ran=trial.get("result") != "not_run",
            observed=trial.get("observed"),
            word=trial.get("word"),
            reason=trial.get("not_run_reason"),
        )["result"]
        if recomputed != trial.get("result"):
            raise ChangeObservationError(f"{trial['id']}: resultatet passer ikke med svaret")
    words = [t.get("word") for t in trials if t.get("word")]
    if len(words) != len(set(words)):
        raise ChangeObservationError("samme testord er brugt i flere forsøg")
    summary = summarize(trials)
    if summary["status"] == "INVALID":
        raise ChangeObservationError("forsøgene er ufuldstændige eller i forkert rækkefølge")
    return summary


def _device(base, manual_path: Path, candidate: dict[str, str]) -> dict[str, Any]:
    """Reuse the device facts the Stage A run just recorded for this candidate."""
    if manual_path.is_file():
        manual = base._read_json(manual_path)
        if manual.get("candidate") == candidate and isinstance(manual.get("device"), dict):
            return manual["device"]
    return base._device_metadata(candidate)


def _load_state(base, path: Path, candidate: dict[str, str]) -> dict[str, Any]:
    if path.is_file():
        value = base._read_json(path)
        if (value.get("schema") == STATE_SCHEMA and value.get("candidate") == candidate
                and isinstance(value.get("trials"), list)
                and isinstance(value.get("words"), list) and len(value["words"]) == 2):
            print(f"  Genoptager {len(value['trials'])}/{len(TRIALS)} gemte forsøg.")
            return value
        base._archive_stale(path)
    value = {
        "schema": STATE_SCHEMA,
        "candidate": candidate,
        "words": pick_words(2),
        "trials": [],
        "production_activation": False,
    }
    base._write_json_atomic(path, value)
    return value


def _not_run(spec: dict[str, Any], word: str | None, reason: str) -> dict[str, Any]:
    print(f"  Registreres som IKKE KØRT ({reason}).")
    print("  Hele resultatet bliver dermed INCOMPLETE, ikke PASS. Forsøget tilbydes igen ved genoptag.")
    return trial_record(spec, ran=False, observed=None, word=word, reason=reason)


def retry_indices(trials: list[dict[str, Any]]) -> list[int]:
    """Saved trials that were not run and may be offered again on resume."""
    return [i for i, t in enumerate(trials) if isinstance(t, dict) and t.get("result") == "not_run"]


def _collect_one(base, spec: dict[str, Any], number: int, word: str | None) -> dict[str, Any]:
    print("\n" + "=" * 68)
    print(f"  ÆNDRINGSFORSØG {number}/{len(TRIALS)} — {spec['title']}")
    print(f"  ({spec['change']})")
    print("=" * 68)
    print("  " + spec["instruction"].format(word=word or ""))
    preconditions = spec.get("preconditions", ())
    if preconditions:
        # The first is asked before the trial (can it run at all), the rest after.
        question, reason = preconditions[0]
        if not base._yes_no("\n  " + question):
            return _not_run(spec, word, reason)
    input("\n  Tryk Enter, når forsøget er udført på telefonen ... ")
    for question, reason in preconditions[1:]:
        if not base._yes_no("  " + question):
            return _not_run(spec, word, reason)
    observed = base._yes_no("  " + spec["question"].format(word=word or ""))
    record = trial_record(spec, ran=True, observed=observed, word=word)
    print("  Resultat: " + ("BESTÅET" if record["result"] == "pass" else "IKKE BESTÅET"))
    return record


def collect(args: argparse.Namespace) -> int:
    base = _base()
    phone_state_path = base._repo_path(args.phone_state)
    manual_path = base._repo_path(args.manual)
    resume_path = base._repo_path(args.resume)
    output_path = base._repo_path(args.output)
    candidate = base._candidate()
    base._phone_state(phone_state_path, candidate)
    state = _load_state(base, resume_path, candidate)
    if not isinstance(state.get("device"), dict):
        state["device"] = _device(base, manual_path, candidate)
        base._write_json_atomic(resume_path, state)

    done = state["trials"]
    if [t.get("id") for t in done] != [s["id"] for s in TRIALS][: len(done)]:
        raise ChangeObservationError("resume-filen indeholder forsøg i forkert rækkefølge")
    words = iter(state["words"])
    word_for = {spec["id"]: next(words) for spec in TRIALS if spec.get("needs_word")}
    # A trial recorded as not_run (no cloud key, no cloud answer) is offered again,
    # so adding a key and relaunching can finish the evidence without hand-editing
    # the resume file. Answered trials are never repeated.
    for index in retry_indices(done):
        spec = TRIALS[index]
        reason = done[index].get("not_run_reason") or "ikke kørt"
        if base._yes_no(f"\n  {spec['id']} blev ikke kørt sidst ({reason}). Kør det nu? [J/N]"):
            done[index] = _collect_one(base, spec, index + 1, word_for.get(spec["id"]))
            state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            base._write_json_atomic(resume_path, state)
    for index in range(len(done), len(TRIALS)):
        spec = TRIALS[index]
        done.append(_collect_one(base, spec, index + 1, word_for.get(spec["id"])))
        state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        base._write_json_atomic(resume_path, state)
        print(f"  Gemt: {index + 1}/{len(TRIALS)}. Kan genoptages uden at gentage forsøget.")

    report = {
        "schema": SCHEMA,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidate": candidate,
        "device": state["device"],
        "trials": state["trials"],
        "production_activation": False,
        "operator": {"method": "guided-stage-a-launcher"},
    }
    summary = validate(report, candidate)
    report["summary"] = summary
    base._write_json_atomic(output_path, report)
    print("\n" + "=" * 68)
    print("  VOICE-ÆNDRINGSFORSØG GEMT")
    print("=" * 68)
    print(f"  Rapport: {output_path.relative_to(ROOT)}")
    print(f"  Status: {summary['status']}  (bestået {summary['passed']}, "
          f"fejlet {summary['failed']}, ikke kørt {summary['not_run']})")
    print("  production_activation=false")
    return exit_code(summary)


def exit_code(summary: dict[str, Any]) -> int:
    return {"PASS": 0, "INCOMPLETE": 3}.get(summary["status"], 1)


def check(path: Path) -> int:
    base = _base()
    candidate = base._candidate()
    summary = validate(base._read_json(base._repo_path(path)), candidate)
    print(f"voice change observations: {summary['status']} "
          f"({summary['passed']}/{summary['trials']} bestået, {summary['not_run']} ikke kørt)")
    return exit_code(summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phone-state", type=Path, default=DEFAULT_PHONE_STATE)
    parser.add_argument("--manual", type=Path, default=DEFAULT_MANUAL)
    parser.add_argument("--resume", type=Path, default=DEFAULT_RESUME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", type=Path, metavar="REPORT",
                        help="validér en gemt rapport mod denne checkout og afslut")
    args = parser.parse_args(argv)
    try:
        if args.check is not None:
            return check(args.check)
        return collect(args)
    except KeyboardInterrupt:
        print("\nSIKKERT STOP: De allerede besvarede forsøg er bevaret.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nSIKKERT STOP: {type(exc).__name__}: {str(exc)[:800]}", file=sys.stderr)
        print("Ingen voice-success, merge, release eller produktionsaktivering blev opfundet.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
