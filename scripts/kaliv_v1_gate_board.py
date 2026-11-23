#!/usr/bin/env python3
"""Where each release gate stands against a set of pins -- a status board, not a gate.

    python scripts/kaliv_v1_gate_board.py --release-scope v1 \\
        --modelrig-sha <sha> --bodyrig-sha <sha> --visionrig-sha <sha> --voicerig-sha <sha> \\
        [--software-exact-green-ref <ref>] [--repository-authority-ref <ref>] ... [--report board.json]

The manifest assembler refuses a manifest with a gate missing, and the final gate answers for
the whole manifest. Neither says, gate by gate, what is still usable when the pins move -- which
is the question before a rig day (#2264 track D, #2390): "main moved; which evidence still
binds, which must be taken again, which was never taken?"

For every gate of the scope this prints one of:

  MISSING        no evidence ref was given
  STALE          a ref was given, and the final gate refuses it against these pins
                 (the gate's own reason follows -- typically a pinned SHA that differs)
  REF_BINDS      the final gate accepts the ref's form and pins. NOT a pass: the gate does not
                 open the artifact behind a ref (#2111), and this board does not either
  DEFERRED       a body gate under the v1 scope (ADR-SYS-001); never counted

Each ref is judged by ``kaliv_system_release_gate.evaluate_manifest`` itself, in a manifest
where that one gate is PASS and the others are PENDING. There is no second copy of the rules
here, so the board cannot disagree with the gate about a ref.

Exit 0 whenever the board could be made (it reports, it does not qualify), 2 on a usage error.
Nothing is written unless --report is given. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import kaliv_system_release_gate as release_gate

SCHEMA = "kaliv-gate-board/v1"
_SHA = re.compile(r"[0-9a-f]{40}")
REPOSITORY_ARGUMENTS = (
    ("modelrig_sha", "Ternedal/ModelRig"),
    ("bodyrig_sha", "Ternedal/BodyRig"),
    ("visionrig_sha", "Ternedal/VisionRig"),
    ("voicerig_sha", "Ternedal/VoiceRig"),
)


class BoardError(ValueError):
    pass


def _manifest(scope: str, pins: Mapping[str, str], gate: str | None, ref: str | None) -> dict[str, Any]:
    """A manifest in which ``gate`` alone claims PASS on ``ref``; everything else is PENDING."""
    gates = {name: {"status": "PENDING", "evidence_refs": []} for name in release_gate.REQUIRED_GATES}
    if gate is not None:
        gates[gate] = {"status": "PASS", "evidence_refs": [ref]}
    return {
        "schema": release_gate.SCHEMA,
        "release_id": "kaliv-rc-gate-board",
        "release_scope": scope,
        "repositories": [{"repository": name, "git_sha": pins[name]} for name in release_gate.REQUIRED_REPOSITORIES],
        "gates": gates,
        "production_activation": False,
    }


def board(scope: str, pins: Mapping[str, str], refs: Mapping[str, str]) -> dict[str, Any]:
    if scope not in release_gate.RELEASE_SCOPE_GATES:
        raise BoardError("release scope must be one of: " + ", ".join(sorted(release_gate.RELEASE_SCOPE_GATES)))
    if set(pins) != set(release_gate.REQUIRED_REPOSITORIES) or any(
            not isinstance(sha, str) or not _SHA.fullmatch(sha) for sha in pins.values()):
        raise BoardError("every repository needs a lowercase 40-hex pin")
    unknown = set(refs) - set(release_gate.REQUIRED_GATES)
    if unknown:
        raise BoardError("unknown gates: " + ", ".join(sorted(unknown)))
    try:
        release_gate.evaluate_manifest(_manifest(scope, pins, None, None))
    except release_gate.SystemReleaseManifestError as exc:
        raise BoardError(f"the gate refuses these pins before any evidence: {exc}") from None
    in_scope = release_gate.RELEASE_SCOPE_GATES[scope]
    rows = []
    for gate in release_gate.REQUIRED_GATES:
        ref = refs.get(gate)
        row: dict[str, Any] = {"gate": gate, "evidence_ref": ref}
        if gate not in in_scope:
            row.update(status="DEFERRED", reason=f"not required for the {scope} scope")
        elif not ref:
            row.update(status="MISSING", reason="no evidence ref given")
        else:
            try:
                release_gate.evaluate_manifest(_manifest(scope, pins, gate, ref))
            except release_gate.SystemReleaseManifestError as exc:
                row.update(status="STALE", reason=str(exc))
            else:
                row.update(status="REF_BINDS",
                           reason="the final gate accepts this ref's form and pins; the artifact behind it is not checked here")
        rows.append(row)
    counted = [row for row in rows if row["status"] != "DEFERRED"]
    return {
        "schema": SCHEMA,
        "release_scope": scope,
        "pinned_repositories": dict(pins),
        "gates": rows,
        "summary": {status: sum(1 for row in counted if row["status"] == status)
                    for status in ("REF_BINDS", "STALE", "MISSING")},
        # Said once, in the data too: this is not a qualification and can never be read as one.
        "qualifies": False,
    }


def render(result: Mapping[str, Any]) -> str:
    lines = [f"gate board ({result['release_scope']}) -- a status board, not a qualification"]
    for name, sha in result["pinned_repositories"].items():
        lines.append(f"  pin {name:<20} {sha}")
    lines.append("")
    for row in result["gates"]:
        lines.append(f"  {row['status']:<10} {row['gate']:<32} {row['reason']}")
    summary = result["summary"]
    lines.append("")
    lines.append(f"  ref binds: {summary['REF_BINDS']}   stale: {summary['STALE']}   missing: {summary['MISSING']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release-scope", required=True, choices=sorted(release_gate.RELEASE_SCOPE_GATES))
    for argument, _name in REPOSITORY_ARGUMENTS:
        parser.add_argument("--" + argument.replace("_", "-"), required=True)
    for gate in release_gate.REQUIRED_GATES:
        parser.add_argument(f"--{gate.replace('_', '-')}-ref")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    pins = {name: getattr(args, argument) for argument, name in REPOSITORY_ARGUMENTS}
    refs = {gate: value for gate in release_gate.REQUIRED_GATES
            if (value := getattr(args, f"{gate}_ref")) is not None}
    try:
        result = board(args.release_scope, pins, refs)
    except BoardError as exc:
        print(f"gate board: {exc}", file=sys.stderr)
        return 2
    print(render(result))
    if args.report is not None:
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
