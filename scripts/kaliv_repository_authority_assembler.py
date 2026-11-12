#!/usr/bin/env python3
"""Assemble the repository_authority qualifier's input from the four verifier outputs.

Each core repository has a live verifier, ``verify-repository-authority.ps1 -Json``.
It prints one JSON verdict, bound to the exact clean ``main`` checkout it ran from.
The qualifier (``kaliv_repository_authority_qualifier.py``) takes four entries of
``repository / git_sha / live_repository_authority_passed / evidence_ref``. Until
now those were typed by hand. This builds them from the verifier outputs
themselves (#2390 F3, #2109):

- it reads each saved verifier output as bytes (UTF-8, or UTF-16 with a BOM, which
  Windows PowerShell 5.1's ``>`` writes);
- it accepts a verdict only when it is the right repository's own format, version 1,
  ``passed`` with no errors, bound to one exact 40-hex ``head_revision`` (and, where
  the verifier reports it, GitHub's ``main`` on that same revision), and claims no
  physical, Agent 3 or production authority;
- it binds each entry to the SHA-256 of the exact bytes it read
  (``evidence_ref = sha256:<hex>:<format>``), so a verdict cannot be swapped later;
- optionally it requires each head to equal an expected pin (``--expect``);
- it runs the real qualifier on the result before writing it, so nothing it writes
  can be refused there.

Read-only: it calls no GitHub API and changes no setting. A PASS proves only the
four repositories' settings at those exact revisions.

Run (PowerShell, from a ModelRig checkout):

    python scripts/kaliv_repository_authority_assembler.py `
      --modelrig  .\\authority-modelrig.json  --bodyrig  .\\authority-bodyrig.json `
      --visionrig .\\authority-visionrig.json --voicerig .\\authority-voicerig.json `
      --output .\\repository-authority-evidence.json

Exit 0: written and accepted by the qualifier. Exit 2: refused; nothing is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kaliv_repository_authority_qualifier as qualifier  # noqa: E402

MAX_BYTES = 1024 * 1024
_SHA40 = re.compile(r"^[0-9a-f]{40}$")

# repository -> the format its verifier writes. The order is the qualifier's.
FORMATS: dict[str, str] = {
    "Ternedal/ModelRig": "modelrig-repository-authority",
    "Ternedal/BodyRig": "bodyrig-repository-authority",
    "Ternedal/VisionRig": "visionrig-repository-authority",
    "Ternedal/VoiceRig": "voicerig-repository-authority",
}
OPTIONS = {"Ternedal/ModelRig": "modelrig", "Ternedal/BodyRig": "bodyrig",
           "Ternedal/VisionRig": "visionrig", "Ternedal/VoiceRig": "voicerig"}
# A verdict about repository settings must not claim anything beyond them.
MUST_BE_FALSE = ("production_activation", "physical_validation_authority",
                 "physical_acceptance_authority", "agent3_activation_authority")


class AssemblyError(RuntimeError):
    pass


def decode(raw: bytes, label: str) -> Mapping[str, Any]:
    """One JSON object from a saved verifier output; refuses anything else."""
    if len(raw) > MAX_BYTES:
        raise AssemblyError(f"{label}: verifier output is too large")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        codec = "utf-16"
    else:
        codec = "utf-8-sig"
    try:
        text = raw.decode(codec)
    except UnicodeDecodeError as exc:
        raise AssemblyError(f"{label}: verifier output is not UTF-8 or UTF-16 with a BOM") from exc
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise AssemblyError(f"{label}: expected exactly one JSON line from -Json, found {len(lines)}")
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise AssemblyError(f"{label}: verifier output is not JSON") from exc
    if not isinstance(value, dict):
        raise AssemblyError(f"{label}: verifier output is not a JSON object")
    return value


def entry(repository: str, raw: bytes, expected_sha: str | None = None) -> dict[str, Any]:
    """The qualifier entry for one repository, from its verifier output bytes."""
    label = repository
    verdict = decode(raw, label)
    expected_format = FORMATS[repository]
    if verdict.get("format") != expected_format:
        raise AssemblyError(f"{label}: format is not {expected_format}")
    version = verdict.get("version")
    if isinstance(version, bool) or version != 1:
        raise AssemblyError(f"{label}: version is not 1")
    if verdict.get("repository") != repository:
        raise AssemblyError(f"{label}: verdict is for another repository")
    if verdict.get("branch") != "main":
        raise AssemblyError(f"{label}: verdict is not for branch main")
    head = verdict.get("head_revision")
    if not isinstance(head, str) or not _SHA40.match(head):
        raise AssemblyError(f"{label}: head_revision is not an exact lowercase 40-hex revision")
    if "github_head_revision" in verdict and verdict["github_head_revision"] != head:
        raise AssemblyError(f"{label}: GitHub main was on another revision than the checkout")
    if verdict.get("passed") is not True:
        raise AssemblyError(f"{label}: the verifier did not pass")
    if verdict.get("errors") != []:
        raise AssemblyError(f"{label}: a passing verdict must have no errors")
    if verdict.get("production_activation") is not False:
        raise AssemblyError(f"{label}: production_activation must be present and false")
    for key in MUST_BE_FALSE:
        if key in verdict and verdict[key] is not False:
            raise AssemblyError(f"{label}: {key} must be false")
    if expected_sha is not None and head != expected_sha:
        raise AssemblyError(f"{label}: head {head} is not the expected pin {expected_sha}")
    return {
        "repository": repository,
        "git_sha": head,
        "live_repository_authority_passed": True,
        "evidence_ref": f"sha256:{hashlib.sha256(raw).hexdigest()}:{expected_format}",
    }


def assemble(outputs: Mapping[str, bytes], expected: Mapping[str, str] | None = None) -> dict[str, Any]:
    expected = dict(expected or {})
    unknown = sorted(set(expected) - set(FORMATS))
    if unknown:
        raise AssemblyError("--expect names an unknown repository: " + ", ".join(unknown))
    missing = [repo for repo in FORMATS if repo not in outputs]
    if missing:
        raise AssemblyError("missing verifier output for: " + ", ".join(missing))
    evidence = {
        "schema": qualifier.SCHEMA,
        "repositories": [entry(repo, outputs[repo], expected.get(repo)) for repo in FORMATS],
        "production_activation": False,
    }
    try:
        qualifier.qualify(evidence)
    except qualifier.RepositoryAuthorityQualificationError as exc:
        raise AssemblyError(f"the qualifier refused the assembled evidence: {exc}") from exc
    return evidence


def _expect(values: Sequence[str]) -> dict[str, str]:
    pins: dict[str, str] = {}
    for value in values:
        repository, _, sha = value.partition("=")
        if not repository or not _SHA40.match(sha):
            raise AssemblyError(f"--expect must be OWNER/REPO=<40-hex>, got {value!r}")
        pins[repository] = sha
    return pins


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for repository, option in OPTIONS.items():
        parser.add_argument(f"--{option}", type=Path, required=True,
                            help=f"saved output of {repository}'s verify-repository-authority.ps1 -Json")
    parser.add_argument("--expect", action="append", default=[],
                        help="OWNER/REPO=<40-hex>: refuse unless that repository's head is this pin")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        outputs = {}
        for repository, option in OPTIONS.items():
            path: Path = getattr(args, option)
            try:
                outputs[repository] = path.read_bytes()
            except OSError as exc:
                raise AssemblyError(f"{repository}: cannot read {path}") from exc
        evidence = assemble(outputs, _expect(args.expect))
    except AssemblyError as exc:
        print(json.dumps({"assembled": False, "error": str(exc)}), file=sys.stderr)
        return 2
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"assembled": True, "output": str(args.output),
                      "repositories": {e["repository"]: e["git_sha"] for e in evidence["repositories"]}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
