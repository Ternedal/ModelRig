from __future__ import annotations

import textwrap
from pathlib import Path

ROOT = Path.cwd()


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(value).lstrip(), encoding="utf-8")


write(
    "scripts/build_devcontrol_artifacts.py",
    r'''
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
    ''',
)

write(
    "devcontrol/tests/test_publisher_protocol_inventory_h10f.py",
    r'''
    from __future__ import annotations

    import ast
    import re
    import unittest
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    PACKAGE = ROOT / "devcontrol/src/kaliv_dev_control"
    REPORT = ROOT / "devcontrol/PUBLISHER_PROTOCOL_INVENTORY.md"
    TOKENS = ("publisher", "semantic_review", "draft_pr_readiness", "local_candidate_materialization")
    EXTRA = {"durable_publication.py", "streaming_publication.py", "store.py", "trusted_git_runtime_staging.py"}


    def _expected_paths() -> set[str]:
        result: set[str] = set()
        for path in PACKAGE.rglob("*.py"):
            relative = path.relative_to(PACKAGE).as_posix()
            if any(token in relative for token in TOKENS) or relative in EXTRA:
                result.add(f"devcontrol/src/kaliv_dev_control/{relative}")
        return result


    class PublisherProtocolInventoryH10FTests(unittest.TestCase):
        def test_recursive_supported_inventory_is_exact(self) -> None:
            report = REPORT.read_text(encoding="utf-8")
            actual = set(re.findall(r"^- `(devcontrol/src/kaliv_dev_control/[^`]+\.py)`$", report, re.MULTILINE))
            self.assertEqual(actual, _expected_paths())
            self.assertIn("static validation/evidence support package", report)
            self.assertIn("Live publication", report)

        def test_rejected_compatibility_package_is_physically_absent(self) -> None:
            self.assertFalse((PACKAGE / "_compatibility_v1").exists())
            self.assertTrue(all("_compatibility_v1" not in path for path in _expected_paths()))

        def test_protocol_modules_do_not_import_remote_or_credential_clients(self) -> None:
            forbidden = {"requests", "urllib", "http", "socket", "paramiko", "boto3", "twine"}
            for relative in sorted(_expected_paths()):
                path = ROOT / relative
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imported: set[str] = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        imported.add(node.module.split(".", 1)[0])
                self.assertFalse(imported & forbidden, (relative, imported & forbidden))

        def test_direct_os_replace_and_named_temporaries_are_confined(self) -> None:
            replace_users: set[str] = set()
            temporary_users: set[str] = set()
            for relative in sorted(_expected_paths()):
                path = ROOT / relative
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    function = node.func
                    if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
                        if function.value.id == "os" and function.attr == "replace":
                            replace_users.add(path.relative_to(PACKAGE).as_posix())
                        if function.value.id == "tempfile" and function.attr == "NamedTemporaryFile":
                            temporary_users.add(path.relative_to(PACKAGE).as_posix())
            self.assertTrue(replace_users <= {"store.py", "_local_candidate_materialization_legacy/__init__.py"}, replace_users)
            self.assertTrue(temporary_users <= {"store.py"}, temporary_users)


    if __name__ == "__main__":
        unittest.main()
    ''',
)

write(
    "devcontrol/tests/test_dc_l14_reproducible_packaging.py",
    r'''
    from __future__ import annotations

    import hashlib
    import shutil
    import subprocess
    import sys
    import tarfile
    import tempfile
    import unittest
    import zipfile
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    PROJECT = ROOT / "devcontrol"
    BUILDER = ROOT / "scripts/build_devcontrol_artifacts.py"


    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


    def _copy_project(destination: Path) -> Path:
        target = destination / "devcontrol"
        shutil.copytree(PROJECT, target, ignore=shutil.ignore_patterns("dist", "build", "*.egg-info", "__pycache__", "*.pyc"))
        return target


    def _build(source: Path, output: Path) -> tuple[Path, Path]:
        result = subprocess.run(
            (sys.executable, str(BUILDER), "--source", str(source), "--outdir", str(output)),
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        del result
        return next(output.glob("*.whl")), next(output.glob("*.tar.gz"))


    class ReproduciblePackagingTests(unittest.TestCase):
        def test_wheel_and_sdist_are_byte_reproducible_and_exclude_compatibility(self) -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                first = _build(_copy_project(root / "first"), root / "dist-first")
                second = _build(_copy_project(root / "second"), root / "dist-second")
                self.assertEqual([_sha256(path) for path in first], [_sha256(path) for path in second])
                with zipfile.ZipFile(first[0]) as archive:
                    wheel_members = sorted(archive.namelist())
                with tarfile.open(first[1], "r:gz") as archive:
                    sdist_members = sorted(member.name.split("/", 1)[-1] for member in archive.getmembers() if "/" in member.name)
                self.assertTrue(any(name.endswith("kaliv_dev_control/__init__.py") for name in wheel_members))
                self.assertTrue(any("_local_candidate_materialization_legacy/__init__.py" in name for name in wheel_members))
                for members in (wheel_members, sdist_members):
                    joined = "\n".join(members)
                    self.assertNotIn("_compatibility_v1", joined)
                    self.assertNotIn("__pycache__", joined)
                    self.assertNotIn(".pyc", joined)

        def test_builder_and_project_have_no_upload_or_publish_tooling(self) -> None:
            combined = (PROJECT / "pyproject.toml").read_text(encoding="utf-8") + BUILDER.read_text(encoding="utf-8")
            for token in ("twine", "repository-url", "api-token"):
                self.assertNotIn(token, combined.lower())
            self.assertIn("setuptools==75.8.2", combined)
            self.assertIn("kaliv_dev_control._compatibility_v1.*", combined)


    if __name__ == "__main__":
        unittest.main()
    ''',
)
