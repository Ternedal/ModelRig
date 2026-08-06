from __future__ import annotations

import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaliv_dev_control import durable_publication as publication_module
from kaliv_dev_control.durable_publication import (
    DurablePublicationError,
    create_once_file,
    rename_directory_no_replace,
    replace_file_durable,
    sync_tree,
    unlink_durable,
)


class DurablePublicationTests(unittest.TestCase):
    def test_create_once_file_is_immutable_and_parallel_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "entry.json"

            def attempt(payload: bytes):
                try:
                    create_once_file(target, payload)
                    return payload
                except FileExistsError as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(attempt, (b"one", b"two")))
            winners = [item for item in results if isinstance(item, bytes)]
            failures = [item for item in results if isinstance(item, FileExistsError)]
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(failures), 1)
            self.assertEqual(target.read_bytes(), winners[0])
            self.assertEqual([item.name for item in root.iterdir()], ["entry.json"])
            with self.assertRaises(FileExistsError):
                create_once_file(target, b"replacement")

    def test_directory_commit_is_no_replace_and_leaves_no_pending_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            pending = root / ".transaction.pending"
            final = root / "transaction"
            (pending / "nested").mkdir(parents=True)
            (pending / "nested" / "payload.bin").write_bytes(b"payload")
            rename_directory_no_replace(pending, final)
            self.assertFalse(pending.exists())
            self.assertEqual((final / "nested" / "payload.bin").read_bytes(), b"payload")

            second = root / ".transaction-2.pending"
            second.mkdir()
            (second / "payload.bin").write_bytes(b"different")
            with self.assertRaises(FileExistsError):
                rename_directory_no_replace(second, final)
            self.assertTrue(second.is_dir())
            self.assertEqual((final / "nested" / "payload.bin").read_bytes(), b"payload")

    @unittest.skipIf(os.name == "nt", "portable link proof uses POSIX links")
    def test_tree_sync_rejects_symlinks_and_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            tree = root / "tree"
            tree.mkdir()
            source = tree / "source.bin"
            source.write_bytes(b"payload")
            alias = tree / "alias.bin"
            os.link(source, alias)
            with self.assertRaisesRegex(DurablePublicationError, "aliased"):
                sync_tree(tree)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            tree = root / "tree"
            tree.mkdir()
            target = root / "outside.bin"
            target.write_bytes(b"payload")
            (tree / "linked.bin").symlink_to(target)
            with self.assertRaisesRegex(DurablePublicationError, "linked"):
                sync_tree(tree)

    def test_durable_unlink_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "entry"
            create_once_file(target, b"payload")
            unlink_durable(target)
            self.assertFalse(target.exists())
            unlink_durable(target)

    @unittest.skipIf(os.name == "nt", "POSIX parent fsync is observable directly")
    def test_replace_file_syncs_parent_directory_after_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / ".record.pending"
            target = root / "record.json"
            source.write_bytes(b"new")
            target.write_bytes(b"old")
            with patch(
                "kaliv_dev_control.durable_publication.sync_directory"
            ) as directory_sync:
                replace_file_durable(source, target)
            self.assertEqual(target.read_bytes(), b"new")
            self.assertFalse(source.exists())
            directory_sync.assert_called_once_with(root)

    def test_windows_directory_sync_opens_and_flushes_a_directory_handle(self) -> None:
        calls: dict[str, object] = {}

        class Function:
            def __init__(self, name: str, result: object) -> None:
                self.name = name
                self.result = result
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                calls[self.name] = args
                return self.result

        class Kernel32:
            CreateFileW = Function("create", 123)
            FlushFileBuffers = Function("flush", 1)
            CloseHandle = Function("close", 1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(
                publication_module.ctypes,
                "WinDLL",
                return_value=Kernel32(),
                create=True,
            ):
                publication_module._windows_sync_directory(root)

        create_args = calls["create"]
        self.assertEqual(create_args[0], str(root))
        self.assertEqual(create_args[1], 0xC0000000)
        self.assertEqual(create_args[2], 0x00000007)
        self.assertEqual(create_args[4], 3)
        self.assertEqual(create_args[5], 0x82000000)
        self.assertEqual(calls["flush"], (123,))
        self.assertEqual(calls["close"], (123,))


if __name__ == "__main__":
    unittest.main()
