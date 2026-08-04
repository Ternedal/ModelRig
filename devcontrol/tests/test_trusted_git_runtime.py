from __future__ import annotations

import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from kaliv_dev_control.trusted_git_runtime import (
    TrustedGitRuntime,
    TrustedGitRuntimeError,
    TrustedGitRunner,
    capture_trusted_git_runtime_manifest,
    load_trusted_git_runtime_receipt,
    stage_trusted_git_runtime,
)

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = b'''#!/bin/sh
while [ "$#" -ge 2 ] && [ "$1" = "-c" ]; do
    shift 2
done
case "$1" in
    --version)
        printf 'git version staged-test-1\n'
        ;;
    show-environment)
        printf '{"PATH":"%s","GIT_EXEC_PATH":"%s","LD_LIBRARY_PATH":"%s","HOME":"%s","GIT_CONFIG_NOSYSTEM":"%s"}\n' "$PATH" "$GIT_EXEC_PATH" "$LD_LIBRARY_PATH" "$HOME" "$GIT_CONFIG_NOSYSTEM"
        ;;
    run-helper)
        exec "$GIT_EXEC_PATH/git-helper"
        ;;
    *)
        exit 9
        ;;
esac
'''

HELPER = b'''#!/bin/sh
printf 'trusted-helper\n'
'''


def require_posix() -> None:
    if os.name == "nt":
        raise unittest.SkipTest("the synthetic executable fixture requires POSIX")


def make_source(root: Path) -> Path:
    source = root / "source"
    (source / "bin").mkdir(parents=True)
    (source / "libexec" / "git-core").mkdir(parents=True)
    (source / "lib").mkdir(parents=True)
    executable = source / "bin" / "git"
    helper = source / "libexec" / "git-core" / "git-helper"
    executable.write_bytes(SCRIPT)
    helper.write_bytes(HELPER)
    (source / "lib" / "runtime.so").write_bytes(b"library-bytes")
    executable.chmod(0o755)
    helper.chmod(0o755)
    return source.resolve()


def capture(source: Path):
    return capture_trusted_git_runtime_manifest(
        source,
        executable_relative_path="bin/git",
        exec_path_relative_path="libexec/git-core",
        path_relative_directories=("bin", "libexec/git-core", "lib"),
    )


def stage(root: Path):
    source = make_source(root)
    staging = root / "staging"
    operation = root / "operation"
    staging.mkdir()
    operation.mkdir()
    manifest = capture(source)
    transaction = stage_trusted_git_runtime(
        manifest,
        source_root=source,
        staging_root=staging.resolve(),
    )
    runtime = TrustedGitRuntime(transaction.resolve())
    runner = TrustedGitRunner(runtime, operation_root=operation.resolve())
    return source, staging, manifest, runtime, runner


class TrustedGitRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        require_posix()

    def test_complete_runtime_stages_and_invokes_with_exact_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, manifest, runtime, runner = stage(Path(directory))
            evidence = runner.evidence()
            self.assertEqual(evidence.runtime_manifest_sha256, manifest.sha256)
            self.assertEqual(evidence.runtime_file_count, 3)
            self.assertEqual(evidence.runtime_bytes, manifest.total_bytes)
            self.assertEqual(evidence.library_relative_directories, ("lib",))
            self.assertEqual(evidence.version, "git version staged-test-1")

            with patch.dict(os.environ, {"PATH": "/untrusted/path"}, clear=False):
                observed = json.loads(
                    runner.run(
                        ("show-environment",),
                        cwd=runner.operation_root,
                        maximum=16_384,
                    ).decode("utf-8")
                )
            expected_path = os.pathsep.join(
                os.fspath(path) for path in runtime.path_directories
            )
            self.assertEqual(observed["PATH"], expected_path)
            self.assertNotIn("/untrusted/path", observed["PATH"])
            self.assertEqual(observed["GIT_EXEC_PATH"], os.fspath(runtime.exec_path))
            self.assertEqual(
                observed["LD_LIBRARY_PATH"],
                os.fspath(runtime.runtime_root / "lib"),
            )
            self.assertEqual(observed["HOME"], os.fspath(runner._home))
            self.assertEqual(observed["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertEqual(
                runner.run(("run-helper",), cwd=runner.operation_root),
                b"trusted-helper\n",
            )

    def test_manifest_is_content_deterministic_across_source_roots(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = capture(make_source(Path(first)))
            two = capture(make_source(Path(second)))
            self.assertEqual(one.canonical_json(), two.canonical_json())
            self.assertEqual(one.sha256, two.sha256)

    def test_source_change_after_capture_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            staging = root / "staging"
            staging.mkdir()
            manifest = capture(source)
            (source / "libexec" / "git-core" / "git-helper").write_bytes(
                b"changed"
            )
            with self.assertRaisesRegex(
                TrustedGitRuntimeError,
                "does not match the pinned manifest",
            ):
                stage_trusted_git_runtime(
                    manifest,
                    source_root=source,
                    staging_root=staging.resolve(),
                )
            self.assertEqual(list(staging.iterdir()), [])

    def test_staged_tampering_and_extra_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, runtime, _ = stage(Path(directory))
            helper = runtime.runtime_root / "libexec" / "git-core" / "git-helper"
            helper.write_bytes(b"tampered")
            with self.assertRaisesRegex(TrustedGitRuntimeError, "changed"):
                runtime.verify()

        with tempfile.TemporaryDirectory() as directory:
            _, _, _, runtime, _ = stage(Path(directory))
            (runtime.runtime_root / "unexpected.txt").write_text(
                "unexpected",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TrustedGitRuntimeError, "extra file"):
                runtime.verify()

    def test_noncanonical_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, runtime, _ = stage(Path(directory))
            receipt = runtime.transaction_root / "receipt.json"
            receipt.write_bytes(receipt.read_bytes() + b"\n")
            with self.assertRaisesRegex(TrustedGitRuntimeError, "canonical"):
                load_trusted_git_runtime_receipt(runtime.transaction_root)

    def test_create_once_and_parallel_publication_have_one_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            staging = root / "staging"
            staging.mkdir()
            manifest = capture(source)

            def attempt():
                try:
                    return stage_trusted_git_runtime(
                        manifest,
                        source_root=source,
                        staging_root=staging.resolve(),
                    )
                except TrustedGitRuntimeError as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: attempt(), range(2)))
            winners = [value for value in results if isinstance(value, Path)]
            failures = [
                value for value in results if isinstance(value, TrustedGitRuntimeError)
            ]
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(failures), 1)
            self.assertEqual(len([item for item in staging.iterdir() if item.is_dir()]), 1)
            with self.assertRaisesRegex(TrustedGitRuntimeError, "already"):
                stage_trusted_git_runtime(
                    manifest,
                    source_root=source,
                    staging_root=staging.resolve(),
                )

    def test_symlinks_hardlinks_and_unapproved_environment_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            alias = source / "lib" / "alias.so"
            alias.symlink_to(source / "lib" / "runtime.so")
            with self.assertRaisesRegex(TrustedGitRuntimeError, "link-free"):
                capture(source)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            duplicate = source / "lib" / "duplicate.so"
            os.link(source / "lib" / "runtime.so", duplicate)
            with self.assertRaisesRegex(TrustedGitRuntimeError, "hard-linked"):
                capture(source)

        with tempfile.TemporaryDirectory() as directory:
            _, _, _, _, runner = stage(Path(directory))
            with self.assertRaisesRegex(TrustedGitRuntimeError, "unsupported field"):
                runner.environment({"PATH": "/escape"})

    def test_schema_and_contract_field_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, manifest, runtime, runner = stage(Path(directory))
            receipt = runtime.receipt
            evidence = runner.evidence()
            cases = (
                (
                    "development-trusted-git-runtime-manifest-v1.schema.json",
                    manifest.to_dict(),
                ),
                (
                    "development-trusted-git-runtime-staging-receipt-v1.schema.json",
                    receipt.to_dict(),
                ),
                (
                    "development-trusted-git-runtime-evidence-v1.schema.json",
                    evidence.to_dict(),
                ),
            )
            for filename, payload in cases:
                with self.subTest(filename=filename):
                    schema = json.loads(
                        (ROOT / "devcontrol" / "schemas" / filename).read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(set(schema["required"]), set(payload))
                    self.assertEqual(set(schema["properties"]), set(payload))


if __name__ == "__main__":
    unittest.main()
