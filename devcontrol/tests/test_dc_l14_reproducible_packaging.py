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
