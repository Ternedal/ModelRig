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

import hashlib
import importlib.util
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "kaliv-frozen-candidate/v3"
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
    "tree_paths",
    "tree_sha256",
)


class AttestationError(Exception):
    """A frozen-candidate attestation is missing, stale, or does not match."""


def attestation_path(root: Path) -> Path:
    return Path(root) / "validation" / "frozen-candidate.json"


def _blob_sha1(path: Path) -> str:
    body = path.read_bytes()
    return hashlib.sha1(b"blob %d\x00" % len(body) + body).hexdigest()


# F-1503: the reader's own copy of the freeze gate's extras rule. It cannot
# import freeze_check (freeze_check imports THIS module), so the rule is
# duplicated -- but a parity check in the freeze suite asserts the two stay
# identical, so drift is caught. Only validation/ (the attestation) and .git
# are sanctioned; bytecode is an extra.
_SANCTIONED_ROOT_DIRS = {".git"}
_SANCTIONED_TOP = {"validation"}


def _scan_extras_offline(root: Path, blob_set: set) -> list:
    extras = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        kept = []
        for d in dirnames:
            if d in _SANCTIONED_ROOT_DIRS:
                continue
            if os.path.samefile(dirpath, str(root)) and d in _SANCTIONED_TOP:
                continue
            kept.append(d)
        dirnames[:] = kept
        for fname in filenames:
            rel_path = os.path.relpath(
                os.path.join(dirpath, fname), str(root)
            ).replace(os.sep, "/")
            if rel_path not in blob_set:
                extras.append(rel_path)
    return extras


def compute_tree_sha256(root: Path, paths: list[str]) -> str:
    """Rollup digest over the COMMITTED files' bytes (F-1403).

    code_sha256 guards worker/app; everything else the campaign runs --
    freeze_check itself, the aggregator, preflight, tests, backend sources
    -- could be edited after freeze without the offline recompute noticing.
    This digest covers the full recorded file list: sha256 over sorted
    "path:git-blob-sha1" lines, recomputable offline from bytes on disk.
    A missing listed file raises with its name.
    """
    lines = []
    for rel in sorted(paths):
        p = Path(root) / rel
        try:
            digest = _blob_sha1(p)
        except OSError as exc:
            raise AttestationError(
                f"attesteret fil mangler i traeet: {rel} -- traeet er "
                "aendret efter freeze (eller filen er fabrikeret)"
            ) from exc
        lines.append(f"{rel}:{digest}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


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
    tree_paths: list[str] | None = None,
    tree_sha256: str = "",
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
        "tree_paths": sorted(tree_paths or []),
        "tree_sha256": tree_sha256,
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
    unknown = sorted(set(data) - set(REQUIRED_FIELDS))
    if unknown:
        raise AttestationError(
            "attestationen har ukendte felter: " + ", ".join(unknown)
            + " -- kontrakten er exact (F-1407); en fremmed eller nyere "
            "fil afvises fremfor at ignoreres"
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

    tree_paths = data["tree_paths"]
    tree_sha = data["tree_sha256"]
    if not isinstance(tree_paths, list) or not all(
        isinstance(p, str) and p for p in tree_paths
    ):
        raise AttestationError("tree_paths er ikke en liste af stier")
    if data["mode"] == "gitless-api":
        if not tree_paths or not re.fullmatch(r"[0-9a-f]{64}", str(tree_sha)):
            raise AttestationError(
                "gitless-attestation uden tree digest -- koer freeze_check "
                "fra 1.58.136+ igen"
            )
        actual_tree = compute_tree_sha256(root, tree_paths)
        if actual_tree != tree_sha:
            raise AttestationError(
                "traeets rollup-digest matcher ikke attestationen -- en "
                "committet fil (hvor som helst i traeet, ikke kun worker/) "
                "er aendret efter freeze. "
                f"attesteret: {str(tree_sha)[:12]}..., "
                f"beregnet: {actual_tree[:12]}..."
            )
        # F-1503: the rollup proves the RECORDED files are unchanged, but a
        # file ADDED after freeze is not in tree_paths and would go unseen.
        # Re-inventory the actual tree offline and refuse any extra, using
        # the SAME scanner the freeze gate uses (so gate and reader agree on
        # exactly one rule). Bytecode/__pycache__ count as extras here too.
        blob_set = set(tree_paths)
        extras = _scan_extras_offline(root, blob_set)
        if extras:
            bytecode = [p for p in extras
                        if p.endswith(".pyc") or "__pycache__" in p]
            detail = f" ({len(bytecode)} bytecode)" if bytecode else ""
            raise AttestationError(
                f"{len(extras)} fil(er) er tilfoejet i traeet EFTER freeze"
                f"{detail} -- ikke i attestationen: "
                + ", ".join(sorted(extras)[:3])
                + " -- hent en frisk ZIP og koer freeze_check forfra"
            )
    return data
