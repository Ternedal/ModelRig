"""Frozen-candidate attestation: written by the freeze gate, inherited offline.

One module owns the contract (F-1304). Before this, the writer
(freeze_check) and TWO independent readers (physical_validation_campaign,
rig_preflight) each had their own idea of what a valid attestation was --
the readers checked only "version matches and the sha is 40 hex", so a
hand-written JSON file satisfied the whole chain of custody.

The contract now has teeth without any secret material:

- STRICT SCHEMA: every field is required and validated; an old or partial
  file is refused by name.
- FRESHNESS: `checked_at` must be recent (<= MAX_AGE_HOURS) and not from
  the future. A replayed attestation from an earlier candidate dies here
  or on the version pin.
- OFFLINE TAMPER-EVIDENCE: `code_sha256` is the worker source fingerprint
  the freeze gate computed from the tree it verified. Every reader
  RECOMPUTES the fingerprint from the tree it is actually standing on and
  refuses on mismatch. Editing the tree after freeze, or fabricating the
  file for a tree the gate never saw, breaks the match -- no network, no
  signatures, just the same bytes hashed twice.

The release-side binding (local tree <-> published release commit) is the
freeze gate's own job via the GitHub git/trees API and happens BEFORE this
file is written; see freeze_check. This module is the portable half: what
the gate proved, carried to readers that must work offline.
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "kaliv-frozen-candidate/v2"
MAX_AGE_HOURS = 24.0
_CLOCK_SKEW = timedelta(minutes=5)
_MODES = {"git", "gitless-api"}

REQUIRED_FIELDS = (
    "schema",
    "version",
    "git_sha",
    "mode",
    "checked_at",
    "ci",
    "codeql",
    "code_sha256",
    "tree_files_verified",
)


class AttestationError(Exception):
    """A frozen-candidate attestation is missing, stale, or does not match."""


def attestation_path(root: Path) -> Path:
    return Path(root) / "validation" / "frozen-candidate.json"


def compute_code_sha256(root: Path) -> str:
    """The same worker-source fingerprint the appliance stamps (F-607)."""
    path = Path(root) / "worker" / "app" / "build_identity.py"
    spec = importlib.util.spec_from_file_location(
        "attestation_build_identity", path
    )
    if spec is None or spec.loader is None:
        raise AttestationError(f"kan ikke indlaese build_identity fra {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.code_fingerprint()


def write_attestation(
    root: Path,
    *,
    version: str,
    git_sha: str,
    mode: str,
    tree_files_verified: int,
    now: datetime | None = None,
) -> Path:
    """Write the attestation for a FROZEN verdict. The gate calls this once."""
    if mode not in _MODES:
        raise AttestationError(f"ukendt attestation-mode: {mode!r}")
    path = attestation_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "version": version,
        "git_sha": git_sha,
        "mode": mode,
        "checked_at": (now or datetime.now(timezone.utc)).isoformat(),
        "ci": "success",
        "codeql": "success",
        "code_sha256": compute_code_sha256(root),
        "tree_files_verified": int(tree_files_verified),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def load_attestation(
    root: Path,
    *,
    expected_version: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Strictly validate and return the attestation, or refuse loudly.

    Every refusal names the failing field, so a rig-day operator sees WHAT
    is wrong, not just that something is.
    """
    path = attestation_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AttestationError(
            "git er utilgaengelig og der findes ingen frossen-kandidat-"
            "attestation -- koer foerst: python scripts\\freeze_check.py "
            "(den skriver validation\\frozen-candidate.json paa FROZEN)"
        ) from exc
    except json.JSONDecodeError as exc:
        raise AttestationError(
            f"attestationen er ikke gyldig JSON ({exc}) -- koer freeze_check "
            "igen; rediger den aldrig i haanden"
        ) from exc

    if not isinstance(data, dict):
        raise AttestationError("attestationen er ikke et JSON-objekt")
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise AttestationError(
            "attestationen mangler felter: " + ", ".join(missing)
            + " -- en aeldre eller haandskrevet fil; koer freeze_check igen"
        )
    if data["schema"] != SCHEMA:
        raise AttestationError(
            f"attestation-schema er {data['schema']!r}, forventede {SCHEMA!r}"
            " -- koer freeze_check fra samme kandidat igen"
        )
    if data["version"] != expected_version:
        raise AttestationError(
            f"attestationen gaelder version {data['version']!r}, traeet siger "
            f"{expected_version!r} -- en replayet eller forkert fil"
        )
    if not isinstance(data["git_sha"], str) or not re.fullmatch(
        r"[0-9a-f]{40}", data["git_sha"]
    ):
        raise AttestationError("attestationens git_sha er ikke en 40-hex sha")
    if data["mode"] not in _MODES:
        raise AttestationError(f"ukendt attestation-mode: {data['mode']!r}")
    if data["ci"] != "success" or data["codeql"] != "success":
        raise AttestationError(
            "attestationen paastaar ikke ci=success og codeql=success -- "
            "kun en groen kandidat kan fryses"
        )

    try:
        checked_at = datetime.fromisoformat(str(data["checked_at"]))
    except ValueError as exc:
        raise AttestationError(
            f"checked_at er ikke en ISO-8601 tid: {data['checked_at']!r}"
        ) from exc
    if checked_at.tzinfo is None:
        raise AttestationError("checked_at mangler tidszone (skal vaere UTC)")
    current = now or datetime.now(timezone.utc)
    if checked_at > current + _CLOCK_SKEW:
        raise AttestationError(
            "checked_at ligger i fremtiden -- uret eller filen er forkert"
        )
    age = current - checked_at
    if age > timedelta(hours=MAX_AGE_HOURS):
        raise AttestationError(
            f"attestationen er {age.total_seconds() / 3600.0:.1f} timer "
            f"gammel (max {MAX_AGE_HOURS:.0f}) -- koer freeze_check igen, "
            "saa dommen gaelder DENNE rig-dag"
        )

    recorded = data["code_sha256"]
    if not isinstance(recorded, str) or not re.fullmatch(
        r"[0-9a-f]{64}", recorded
    ):
        raise AttestationError("code_sha256 er ikke en 64-hex sha256")
    actual = compute_code_sha256(root)
    if actual != recorded:
        raise AttestationError(
            "worker-kildernes fingerprint matcher ikke attestationen -- "
            f"traeet er aendret efter freeze (eller filen er fabrikeret). "
            f"attesteret: {recorded[:12]}..., beregnet: {actual[:12]}..."
        )

    tfv = data["tree_files_verified"]
    if not isinstance(tfv, int) or isinstance(tfv, bool) or tfv < 0:
        raise AttestationError("tree_files_verified er ikke et ikke-negativt tal")
    if data["mode"] == "gitless-api" and tfv < 1:
        raise AttestationError(
            "gitless-attestation uden verificerede trae-filer -- freeze-"
            "gatens release-binding manglede; koer freeze_check igen"
        )
    return data
