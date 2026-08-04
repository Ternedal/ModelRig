from __future__ import annotations

import base64
from pathlib import Path
import sys
import unittest


class H10GStreamingMaterializer(unittest.TestCase):
    @staticmethod
    def _emit(label: str, source: str) -> None:
        compile(source, label, "exec")
        payload = base64.b64encode(source.encode("utf-8")).decode("ascii")
        sys.stderr.write(f"H10G_{label.upper()}_BASE64={payload}\n")

    def test_materialize_shared_streaming_callers(self) -> None:
        root = Path(__file__).resolve().parents[2]
        package = root / "devcontrol" / "src" / "kaliv_dev_control"

        runtime_path = package / "runtime_staging.py"
        runtime = runtime_path.read_text(encoding="utf-8")
        runtime = runtime.replace("import tempfile\n", "", 1)
        runtime = runtime.replace(
            "from .contract import DevelopmentTask\n",
            "from .contract import DevelopmentTask\n"
            "from .streaming_publication import (\n"
            "    StreamingPublicationError,\n"
            "    publish_stream_once,\n"
            ")\n",
            1,
        )
        start = runtime.index("\ndef _fsync_directory(")
        end = runtime.index("\ndef _fix_published_permissions(", start)
        runtime = runtime[:start] + runtime[end:]
        stage_start = runtime.index("        published_here = False\n", runtime.index("    def stage("))
        stage_end = runtime.index("        # Windows' read-only attribute", stage_start)
        runtime_block = '''        published_here = False
        if destination.exists():
            if not destination.is_file():
                raise RuntimeStagingError(
                    "staged runtime destination is not a regular file"
                )
            existing_hash, existing_size = _file_hash_and_size(
                destination, maximum=self.max_executable_bytes
            )
            if existing_hash != executable_sha256 or existing_size != size_bytes:
                raise RuntimeStagingError(
                    "staged runtime destination already exists with different bytes"
                )
        else:
            def validate_concurrent(path: Path) -> None:
                if _is_linkish(path) or not path.is_file():
                    raise RuntimeStagingError(
                        "concurrent runtime staging produced an unsafe destination"
                    )
                existing_hash, existing_size = _file_hash_and_size(
                    path, maximum=self.max_executable_bytes
                )
                if (
                    existing_hash != executable_sha256
                    or existing_size != size_bytes
                ):
                    raise RuntimeStagingError(
                        "concurrent runtime staging produced different bytes"
                    )

            try:
                published_here = publish_stream_once(
                    source,
                    destination,
                    expected_sha256=executable_sha256,
                    expected_size=size_bytes,
                    maximum=self.max_executable_bytes,
                    validate_existing=validate_concurrent,
                    prepare_temporary=(
                        lambda path: _fix_published_permissions(
                            path, published_here=False
                        )
                        if os.name != "nt"
                        else None
                    ),
                    sync_parent_on_race=True,
                )
            except StreamingPublicationError as exc:
                if exc.code == "source_exceeds_budget":
                    raise RuntimeStagingError(
                        "trusted runtime exceeds the staging budget"
                    ) from exc
                if exc.code == "source_changed":
                    raise RuntimeStagingError(
                        "trusted runtime changed while it was being staged"
                    ) from exc
                raise RuntimeStagingError(
                    "trusted runtime publication was not durable"
                ) from exc
            except OSError as exc:
                raise RuntimeStagingError(
                    "trusted runtime publication failed"
                ) from exc

'''
        runtime = runtime[:stage_start] + runtime_block + runtime[stage_end:]
        for forbidden in ("tempfile.mkstemp", "os.link(", "def _fsync_directory("):
            self.assertNotIn(forbidden, runtime)
        self.assertIn("publish_stream_once(", runtime)
        self._emit("runtime_staging", runtime)

        closure_path = package / "_runtime_closure_common.py"
        closure = closure_path.read_text(encoding="utf-8")
        closure = closure.replace("import tempfile\n", "", 1)
        closure = closure.replace(
            "from .contract import DevelopmentTask\n",
            "from .contract import DevelopmentTask\n"
            "from .streaming_publication import (\n"
            "    StreamingPublicationError,\n"
            "    publish_stream_once,\n"
            ")\n",
            1,
        )
        start = closure.index("\ndef _closure_fsync_directory(")
        end = closure.index("\ndef _closure_staged_mode(", start)
        closure = closure[:start] + closure[end:]
        start = closure.index("\ndef _closure_publish_exact_file(")
        closure_function = '''
def _closure_publish_exact_file(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    maximum: int,
) -> None:
    def validate_existing(path: Path, *, concurrent: bool) -> None:
        if (
            _closure_is_linkish(path)
            or not path.is_file()
            or path.stat().st_nlink != 1
        ):
            if concurrent:
                raise RuntimeClosureError(
                    "concurrent runtime staging produced an unsafe destination"
                )
            raise RuntimeClosureError(
                "staged runtime destination is not a single-link regular file"
            )
        digest, size = _closure_file_hash_and_size(path, maximum=maximum)
        if digest != expected_sha256 or size != expected_size:
            if concurrent:
                raise RuntimeClosureError(
                    "concurrent runtime staging produced an unsafe destination"
                )
            raise RuntimeClosureError(
                "staged runtime destination already has different bytes"
            )
        _closure_fix_staged_mode(path)

    if _closure_is_linkish(destination):
        raise RuntimeClosureError("staged runtime destination is a link")
    if destination.exists():
        validate_existing(destination, concurrent=False)
        return

    try:
        published_here = publish_stream_once(
            source,
            destination,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
            maximum=maximum,
            validate_existing=lambda path: validate_existing(
                path, concurrent=True
            ),
        )
    except StreamingPublicationError as exc:
        if exc.code == "source_exceeds_budget":
            raise RuntimeClosureError(
                "runtime closure exceeds its staging byte budget"
            ) from exc
        if exc.code == "source_changed":
            raise RuntimeClosureError(
                "runtime source changed while staging"
            ) from exc
        raise RuntimeClosureError(
            "runtime closure publication was not durable"
        ) from exc
    except OSError as exc:
        raise RuntimeClosureError(
            "runtime closure publication failed"
        ) from exc

    if published_here:
        try:
            _closure_fix_staged_mode(destination)
        except RuntimeClosureError:
            try:
                os.chmod(destination, 0o755)
                destination.unlink()
            except OSError:
                pass
            raise
'''
        closure = closure[:start] + closure_function
        for forbidden in (
            "tempfile.mkstemp",
            "os.link(",
            "def _closure_fsync_directory(",
        ):
            self.assertNotIn(forbidden, closure)
        self.assertIn("publish_stream_once(", closure)
        self._emit("runtime_closure_common", closure)

        inventory_path = (
            root
            / "devcontrol"
            / "tests"
            / "test_publisher_protocol_inventory_h10f.py"
        )
        inventory = inventory_path.read_text(encoding="utf-8")
        marker = "\n_LOW_LEVEL_PROTOCOLS = Counter(\n"
        shared_streaming = '''
_SHARED_STREAMING_PUBLISHERS = Counter(
    {
        (
            "_runtime_closure_common.py",
            "_closure_publish_exact_file",
            "publish_stream_once",
        ): 1,
        ("runtime_staging.py", "stage", "publish_stream_once"): 1,
    }
)

'''
        inventory = inventory.replace(marker, "\n" + shared_streaming + marker.lstrip("\n"), 1)
        for block in (
            '''        (
            "_runtime_closure_common.py",
            "_closure_publish_exact_file",
            "tempfile.mkstemp",
        ): 1,
        (
            "_runtime_closure_common.py",
            "_closure_publish_exact_file",
            "os.link",
        ): 1,
''',
            '''        ("runtime_staging.py", "stage", "tempfile.mkstemp"): 1,
        ("runtime_staging.py", "stage", "os.link"): 1,
''',
        ):
            self.assertIn(block, inventory)
            inventory = inventory.replace(block, "", 1)
        inventory = inventory.replace(
            '        ("durable_publication.py", "create_once_file", "os.link"): 1,\n',
            '        ("durable_publication.py", "create_once_file", "os.link"): 1,\n'
            '        (\n'
            '            "streaming_publication.py",\n'
            '            "publish_stream_once",\n'
            '            "tempfile.mkstemp",\n'
            '        ): 1,\n'
            '        (\n'
            '            "streaming_publication.py",\n'
            '            "publish_stream_once",\n'
            '            "os.link",\n'
            '        ): 1,\n',
            1,
        )
        inventory = inventory.replace(
            '    "rename_directory_no_replace",\n',
            '    "rename_directory_no_replace",\n    "publish_stream_once",\n',
            1,
        )
        inventory = inventory.replace(
            "            + _SHARED_DIRECTORY_PUBLISHERS\n            + _LOW_LEVEL_PROTOCOLS,",
            "            + _SHARED_DIRECTORY_PUBLISHERS\n"
            "            + _SHARED_STREAMING_PUBLISHERS\n"
            "            + _LOW_LEVEL_PROTOCOLS,",
            1,
        )
        method_start = inventory.index(
            "    def test_streaming_publishers_are_create_once_and_never_replace"
        )
        method_end = inventory.index(
            "    def test_named_temporaries_are_only_ephemeral_patch_input_or_mutable_state",
            method_start,
        )
        method = '''    def test_streaming_publishers_share_one_no_replace_primitive(self) -> None:
        observed = _inventory()
        self.assertEqual(
            Counter(
                {
                    key: count
                    for key, count in observed.items()
                    if key[2] == "publish_stream_once"
                }
            ),
            _SHARED_STREAMING_PUBLISHERS,
        )
        self.assertEqual(
            observed[
                (
                    "streaming_publication.py",
                    "publish_stream_once",
                    "tempfile.mkstemp",
                )
            ],
            1,
        )
        self.assertEqual(
            observed[
                (
                    "streaming_publication.py",
                    "publish_stream_once",
                    "os.link",
                )
            ],
            1,
        )
        for relative in ("_runtime_closure_common.py", "runtime_staging.py"):
            with self.subTest(relative=relative):
                source = (_PACKAGE / relative).read_text(encoding="utf-8")
                self.assertIn("publish_stream_once", source)
                self.assertNotIn("tempfile.mkstemp", source)
                self.assertNotIn("os.link(", source)
                self.assertNotIn("os.replace", source)

'''
        inventory = inventory[:method_start] + method + inventory[method_end:]
        self.assertIn("_SHARED_STREAMING_PUBLISHERS", inventory)
        self.assertIn("streaming_publication.py", inventory)
        self._emit("publisher_inventory", inventory)

        self.fail("intentional H10G materialization stop")


if __name__ == "__main__":
    unittest.main()
