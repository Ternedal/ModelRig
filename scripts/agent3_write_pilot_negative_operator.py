#!/usr/bin/env python3
"""Safe entrypoint for the T-022 negative physical recorder wizard.

The recorder core mints unique negative markers itself, but replay and
stop/retry/replan deliberately reuse a positive marker. This entrypoint replaces
only two orchestration policies:

- an interrupted positive stage is resumed on the same exact candidate branch;
- reused positive markers record their real existing note count before a negative
  case begins.

It then delegates the ceremony to the hash-chained recorder core.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent3_write_pilot_negative_one_click as core  # noqa: E402


def safe_positive_stage() -> tuple[dict[str, Any], dict[str, Any], dict[str, Path], str]:
    identity = core.positive.ensure_candidate()
    should_resume = not core.MANIFEST.is_file() or not core.POSITIVE_OBSERVATIONS.is_file()
    if not should_resume:
        manifest, _raw = core.common._load_json(core.MANIFEST)
        _bound, pending = core.positive.manifest_progress(manifest)
        should_resume = bool(pending)
    if should_resume:
        core.positive.main()

    manifest, _raw = core.common._load_json(core.MANIFEST)
    observations, _observations_raw = core.common._load_json(core.POSITIVE_OBSERVATIONS)
    errors = core.common.validate_manifest(manifest, require_bound=True)
    errors.extend(core.positive.validate_resume(observations, manifest, identity))
    bound, pending = core.positive.manifest_progress(manifest)
    if pending or len(bound) != core.common.RUN_COUNT:
        errors.append(
            f"positive stage is incomplete: {len(bound)}/{core.common.RUN_COUNT}"
        )
    if errors:
        raise core.OperatorError(
            "Den positive del er ikke exact-candidate komplet: " + "; ".join(errors)
        )
    token = core.positive.ensure_token()
    paths = core.positive.database_paths()
    return manifest, observations, paths, token


def safe_case_start(
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

    ordinal = core.POSITIVE_ORDINALS.get(name)
    note_before = 0
    if ordinal is not None:
        manifest, _raw = core.common._load_json(core.MANIFEST)
        item = next(
            (
                value
                for value in manifest.get("runs", [])
                if isinstance(value, Mapping) and value.get("ordinal") == ordinal
            ),
            None,
        )
        if not isinstance(item, Mapping) or not isinstance(item.get("marker"), str):
            raise core.OperatorError(
                f"{name} kræver positiv ordinal {ordinal}, men markeren mangler."
            )
        note_before = core.note_count(paths["notes"], str(item["marker"]))

    approval_before = core.approval_count(paths["approval_db"])
    case_id, marker = core.cases_module.begin_case(
        journal=core.JOURNAL,
        manifest_path=core.MANIFEST,
        name=name,
        note_count=note_before,
        approval_count=approval_before,
        positive_ordinal=ordinal,
    )
    rows, _final_hash = core.store.verify_journal(core.JOURNAL)
    _meta, states = core.store._state(rows)
    return case_id, marker, states[case_id]


def main() -> int:
    core.ensure_positive_stage = safe_positive_stage
    core.ensure_case_started = safe_case_start
    return core.main()


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
