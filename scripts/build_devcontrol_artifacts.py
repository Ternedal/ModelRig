#!/usr/bin/env python3
"""Build deterministic local wheel and sdist artifacts without publishing them."""
from __future__ import annotations

import argparse
import copy
import gzip
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

EPOCH = 1_700_000_000


def _normalize_sdist(path: Path) -> None:
    entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(path, "r:gz") as source:
        for member in source.getmembers():
            extracted = source.extractfile(member) if member.isfile() else None
            entries.append((member, extracted.read() if extracted is not None else None))
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=EPOCH) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target:
                for original, payload in sorted(entries, key=lambda item: item[0].name):
                    member = copy.copy(original)
                    member.mtime = EPOCH
                    member.uid = 0
                    member.gid = 0
                    member.uname = ""
                    member.gname = ""
                    member.pax_headers = {}
                    target.addfile(member, io.BytesIO(payload) if payload is not None else None)
    os.replace(temporary, path)


def build(source: Path, outdir: Path) -> tuple[Path, Path]:
    source = source.resolve()
    outdir = outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"SOURCE_DATE_EPOCH": str(EPOCH), "PYTHONHASHSEED": "0", "TZ": "UTC"})
    subprocess.run(
        (sys.executable, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(outdir)),
        cwd=source,
        env=env,
        check=True,
    )
    wheel = next(outdir.glob("*.whl"))
    sdist = next(outdir.glob("*.tar.gz"))
    _normalize_sdist(sdist)
    return wheel, sdist


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    wheel, sdist = build(args.source, args.outdir)
    print(wheel)
    print(sdist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
