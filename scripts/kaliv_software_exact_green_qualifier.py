#!/usr/bin/env python3
"""Fail-closed qualifier for the Kaliv software_exact_green release gate.

This validates reviewed software evidence for the exact four core repository
revisions. It does not query GitHub, perform merges, synthesize physical
evidence, or activate production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "kaliv-system/software-exact-green-evidence/v1"
VERDICT_SCHEMA = "kaliv-system/software-exact-green-verdict/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_MAX_REF_LEN = 512
REQUIRED_REPOSITORIES = (
    "Ternedal/ModelRig",
    "Ternedal/BodyRig",
    "Ternedal/VisionRig",
    "Ternedal/VoiceRig",
)


class SoftwareExactGreenError(RuntimeError):
    pass


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SoftwareExactGreenError(f"{name} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unknown " + ", ".join(extra))
        raise SoftwareExactGreenError(
            f"{name} has invalid fields: {'; '.join(details)}"
        )


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise SoftwareExactGreenError(
            f"{name} must be a lowercase 40-hex Git SHA"
        )
    return value


def _ref(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > _MAX_REF_LEN
    ):
        raise SoftwareExactGreenError(
            f"{name} must be a bounded nonblank evidence reference"
        )
    return value.strip()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def qualify(value: Mapping[str, Any]) -> dict[str, Any]:
    root = _mapping(value, "evidence")
    _exact_keys(
        root,
        {"schema", "repositories", "production_activation"},
        "evidence",
    )
    if root["schema"] != SCHEMA:
        raise SoftwareExactGreenError("unsupported software exact-green schema")
    if root["production_activation"] is not False:
        raise SoftwareExactGreenError(
            "software exact-green qualification cannot activate production"
        )

    repositories = root["repositories"]
    if not isinstance(repositories, list) or len(repositories) != len(REQUIRED_REPOSITORIES):
        raise SoftwareExactGreenError(
            "repositories must contain exactly the four required core repositories"
        )

    pins: dict[str, str] = {}
    evidence_refs: dict[str, str] = {}
    for index, raw in enumerate(repositories):
        item = _mapping(raw, f"repositories[{index}]")
        _exact_keys(
            item,
            {
                "repository",
                "git_sha",
                "exact_head_qualified",
                "software_green",
                "evidence_ref",
            },
            f"repositories[{index}]",
        )
        repository = item["repository"]
        if repository not in REQUIRED_REPOSITORIES:
            raise SoftwareExactGreenError(
                f"repositories[{index}].repository is not a required core repository"
            )
        if repository in pins:
            raise SoftwareExactGreenError(
                f"duplicate repository evidence: {repository}"
            )
        if item["exact_head_qualified"] is not True:
            raise SoftwareExactGreenError(
                f"{repository} exact_head_qualified must be true"
            )
        if item["software_green"] is not True:
            raise SoftwareExactGreenError(
                f"{repository} software_green must be true"
            )
        pins[repository] = _sha(
            item["git_sha"], f"repositories[{index}].git_sha"
        )
        evidence_refs[repository] = _ref(
            item["evidence_ref"], f"repositories[{index}].evidence_ref"
        )

    missing = [repo for repo in REQUIRED_REPOSITORIES if repo not in pins]
    if missing:
        raise SoftwareExactGreenError(
            "missing required repository evidence: " + ", ".join(missing)
        )
    if len(set(evidence_refs.values())) != len(evidence_refs):
        raise SoftwareExactGreenError(
            "repository software evidence references must be distinct"
        )

    verdict: dict[str, Any] = {
        "schema": VERDICT_SCHEMA,
        "state": "QUALIFIED",
        "software_exact_green_gate_satisfied": True,
        "production_activation": False,
        "repositories": [
            {
                "repository": repo,
                "git_sha": pins[repo],
                "evidence_ref": evidence_refs[repo],
            }
            for repo in REQUIRED_REPOSITORIES
        ],
        "release_gate_satisfied": False,
    }
    digest = hashlib.sha256(_canonical(verdict)).hexdigest()
    verdict["release_evidence_ref"] = (
        "kaliv-software-exact-green:"
        + ":".join(pins[repo] for repo in REQUIRED_REPOSITORIES)
        + ":"
        + digest
    )
    return verdict


def load(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SoftwareExactGreenError(
            "software exact-green evidence file cannot be read"
        ) from exc
    if len(raw) > 1024 * 1024:
        raise SoftwareExactGreenError(
            "software exact-green evidence file is too large"
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoftwareExactGreenError(
            "software exact-green evidence file is not valid UTF-8 JSON"
        ) from exc
    return _mapping(value, "evidence")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    try:
        verdict = qualify(load(args.evidence))
    except SoftwareExactGreenError as exc:
        verdict = {
            "schema": VERDICT_SCHEMA,
            "state": "INVALID",
            "software_exact_green_gate_satisfied": False,
            "release_gate_satisfied": False,
            "production_activation": False,
            "error": str(exc),
        }
        rendered = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 2

    rendered = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
