from __future__ import annotations

import base64
from pathlib import Path
import sys
import unittest


class H10EMaterializeSemanticCore(unittest.TestCase):
    def test_materialize_model_only_core(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "devcontrol" / "src" / "kaliv_dev_control" / "_semantic_review_core.py"
        source = path.read_text(encoding="utf-8")
        source = source.replace("import os\n", "", 1)
        source = source.replace("import tempfile\n", "", 1)

        start = source.index("\ndef _write_canonical_file(")
        end = source.index("\ndef load_semantic_review_request(", start)
        source = source[:start] + source[end:]

        start = source.index("\ndef write_semantic_review_request(")
        end = source.index("\ndef load_signed_semantic_review_verdict(", start)
        source = source[:start] + source[end:]

        start = source.index("\ndef write_signed_semantic_review_verdict(")
        source = source[:start].rstrip() + "\n"

        compile(source, str(path), "exec")
        for forbidden in (
            "tempfile.mkstemp",
            "os.replace",
            "os.fsync",
            "def _write_canonical_file(",
            "def write_semantic_review_request(",
            "def write_signed_semantic_review_verdict(",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("def load_semantic_review_request(", source)
        self.assertIn("def load_signed_semantic_review_verdict(", source)

        payload = base64.b64encode(source.encode("utf-8")).decode("ascii")
        sys.stderr.write(f"H10E_CORE_BASE64={payload}\n")
        self.fail("intentional H10E materialization stop")


if __name__ == "__main__":
    unittest.main()
