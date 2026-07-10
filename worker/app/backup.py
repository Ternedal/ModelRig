"""Kaliv backup & restore.

Bundles everything on the rig that cannot be rebuilt from the repo into one
timestamped archive, and restores it. Roadmap V7.3 -- and V7's exit criterion
says a restore must be proven once, so this ships with a test that does a full
round trip (backup -> wipe -> restore -> verify byte-for-byte).

WHAT IS IN A BACKUP, and why each one hurts to lose:

  rag.db          the embedding index. Losing it means re-ingesting every
                  document by hand.
  data.json       the Go server's pairing state and device tokens. Losing it
                  means re-pairing every device.
  audit.db        the append-only tool audit log. It is a security record;
                  losing it is losing the answer to "what did Kaliv do".
  tools-state     the kill-switch decision (v1.28.0). Losing it re-arms the
                  layer from the env default -- exactly the surprise that
                  persistence was added to prevent.
  notes/          what note_append wrote. The user's own words.

WHAT IS NOT: model weights (re-pullable via Ollama), Piper voices (re-
downloadable), anything under the repo. A backup is for the irreplaceable, not
the merely large.

The manifest records a schema version and each file's sha256, so a restore can
refuse a corrupt or truncated archive instead of writing half of one over live
data -- the failure mode that turns a backup into an outage.

Usage:
    python -m worker.app.backup create  [--out DIR]
    python -m worker.app.backup restore ARCHIVE.tar.gz [--force]
    python -m worker.app.backup verify  ARCHIVE.tar.gz
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import time
from dataclasses import dataclass
from typing import Optional

BACKUP_SCHEMA = 1

# Resolved the same way the worker resolves them, so a backup captures the live
# locations rather than a guessed default.
from . import tools as _tools  # noqa: E402


@dataclass
class Item:
    key: str          # stable name inside the archive
    path: str         # absolute source path on the rig
    kind: str         # "file" or "dir"
    required: bool    # a missing required item aborts restore; optional is fine


def _rag_db() -> str:
    return os.getenv("MODELRIG_DB", "./modelrig-rag.db")


def _backend_data() -> str:
    return os.getenv("MODELRIG_DATA_PATH", "./modelrig-data.json")


def items() -> list[Item]:
    """The manifest of what a backup covers. One place, so create and restore
    can never disagree about the set."""
    return [
        Item("rag.db", _rag_db(), "file", required=False),
        Item("data.json", _backend_data(), "file", required=False),
        Item("audit.db", os.getenv("KALIV_AUDIT_DB", "./kaliv-audit.db"), "file", required=False),
        Item("tools-state.json", os.getenv("KALIV_TOOLS_STATE", "./kaliv-tools-state.json"), "file", required=False),
        Item("notes", _tools.tools_dir(), "dir", required=False),
    ]


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _walk(path: str) -> list[str]:
    out = []
    for root, _dirs, files in os.walk(path):
        for fn in sorted(files):
            out.append(os.path.join(root, fn))
    return sorted(out)


def create(out_dir: str = ".") -> str:
    """Write a timestamped archive. Returns its path."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    archive = os.path.join(out_dir, f"kaliv-backup-{stamp}.tar.gz")

    manifest: dict = {"schema": BACKUP_SCHEMA, "created": stamp, "files": {}}

    # Build the archive in a temp path, then atomically rename: a reader must
    # never see a half-written backup and mistake it for a whole one.
    tmp = archive + ".tmp"
    with tarfile.open(tmp, "w:gz") as tar:
        for it in items():
            if it.kind == "file":
                if not os.path.exists(it.path):
                    continue
                digest = _sha256_file(it.path)
                manifest["files"][it.key] = {"sha256": digest, "kind": "file"}
                tar.add(it.path, arcname=f"data/{it.key}")
            else:  # dir
                if not os.path.isdir(it.path):
                    continue
                filed: dict = {}
                for f in _walk(it.path):
                    rel = os.path.relpath(f, it.path)
                    arc = f"data/{it.key}/{rel}"
                    filed[rel] = _sha256_file(f)
                    tar.add(f, arcname=arc)
                manifest["files"][it.key] = {"kind": "dir", "files": filed}

        payload = json.dumps(manifest, indent=2, sort_keys=True).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    os.replace(tmp, archive)
    return archive


def _read_manifest(archive: str) -> dict:
    with tarfile.open(archive, "r:gz") as tar:
        try:
            f = tar.extractfile("manifest.json")
        except KeyError:
            raise ValueError("not a Kaliv backup: no manifest.json")
        if f is None:
            raise ValueError("manifest.json is not a file")
        return json.loads(f.read())


def verify(archive: str) -> dict:
    """Check every stored file against its recorded hash WITHOUT extracting to
    disk. A backup you cannot verify is a backup you cannot trust in the one
    moment you need it."""
    manifest = _read_manifest(archive)
    if manifest.get("schema") != BACKUP_SCHEMA:
        raise ValueError(f"unsupported backup schema: {manifest.get('schema')}")

    problems: list[str] = []
    checked = 0
    with tarfile.open(archive, "r:gz") as tar:
        for key, meta in manifest["files"].items():
            if meta["kind"] == "file":
                member = f"data/{key}"
                got = _member_sha(tar, member)
                if got is None:
                    problems.append(f"missing from archive: {key}")
                elif got != meta["sha256"]:
                    problems.append(f"hash mismatch: {key}")
                else:
                    checked += 1
            else:
                for rel, want in meta["files"].items():
                    member = f"data/{key}/{rel}"
                    got = _member_sha(tar, member)
                    if got is None:
                        problems.append(f"missing from archive: {key}/{rel}")
                    elif got != want:
                        problems.append(f"hash mismatch: {key}/{rel}")
                    else:
                        checked += 1
    return {"ok": not problems, "checked": checked, "problems": problems}


def _member_sha(tar: tarfile.TarFile, name: str) -> Optional[str]:
    try:
        f = tar.extractfile(name)
    except KeyError:
        return None
    if f is None:
        return None
    return _sha256_bytes(f.read())


def restore(archive: str, force: bool = False) -> dict:
    """Restore an archive over the live locations.

    Verifies the whole archive FIRST and refuses if anything fails: restoring
    half a corrupt backup over live data is worse than not restoring at all.
    Without --force, refuses to overwrite existing files, so a restore cannot
    silently clobber a rig that already has data.
    """
    check = verify(archive)
    if not check["ok"]:
        raise ValueError(f"archive failed verification, refusing to restore: {check['problems']}")

    manifest = _read_manifest(archive)
    targets = {it.key: it for it in items()}

    # Pre-flight: without --force, refuse if any destination already exists.
    if not force:
        clashes = []
        for key in manifest["files"]:
            it = targets.get(key)
            if it and os.path.exists(it.path):
                clashes.append(it.path)
        if clashes:
            raise FileExistsError(
                "these already exist (use --force to overwrite): " + ", ".join(clashes))

    restored: list[str] = []
    with tarfile.open(archive, "r:gz") as tar:
        for key, meta in manifest["files"].items():
            it = targets.get(key)
            if it is None:
                continue  # archive has something this version doesn't know; skip
            if meta["kind"] == "file":
                _extract_to(tar, f"data/{key}", it.path)
                restored.append(it.path)
            else:
                os.makedirs(it.path, exist_ok=True)
                for rel in meta["files"]:
                    dest = os.path.join(it.path, rel)
                    _extract_to(tar, f"data/{key}/{rel}", dest)
                    restored.append(dest)
    return {"restored": restored}


def _extract_to(tar: tarfile.TarFile, member: str, dest: str) -> None:
    f = tar.extractfile(member)
    if f is None:
        raise ValueError(f"cannot read {member} from archive")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as out:
        out.write(f.read())
    os.replace(tmp, dest)  # atomic per file: never a half-written restore


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="kaliv-backup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--out", default=".")
    r = sub.add_parser("restore"); r.add_argument("archive"); r.add_argument("--force", action="store_true")
    v = sub.add_parser("verify"); v.add_argument("archive")
    args = ap.parse_args(argv)

    if args.cmd == "create":
        path = create(args.out)
        res = verify(path)  # never hand back a backup without checking it
        print(f"created {path} ({res['checked']} files, verified)")
        return 0
    if args.cmd == "verify":
        res = verify(args.archive)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    if args.cmd == "restore":
        res = restore(args.archive, force=args.force)
        print(f"restored {len(res['restored'])} files")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
