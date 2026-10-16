"""Static regression guards for voice streaming cancellation and temp cleanup.

Runs without GPU, ASR, TTS or an Android device:
    python -m unittest tests/test_voice_stream_cleanup.py
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "worker" / "app" / "main_impl.py"


class VoiceStreamCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        cls.endpoint = next(
            n for n in cls.tree.body
            if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "voice_converse_stream"
        )
        cls.generator = next(
            n for n in cls.endpoint.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "gen"
        )

    def test_stream_generator_has_finally_cleanup(self):
        guards = [n for n in ast.walk(self.generator) if isinstance(n, ast.Try)]
        self.assertTrue(any(n.finalbody for n in guards))
        finally_nodes = [n for guard in guards for n in guard.finalbody]
        finally_source = ast.unparse(ast.Module(body=finally_nodes, type_ignores=[]))
        self.assertIn("task.cancel()", finally_source)
        self.assertIn("await task", finally_source)
        self.assertIn("rmtree", finally_source)
        self.assertIn("tmp_dir", finally_source)

    def test_cleanup_runs_on_normal_stream_completion_too(self):
        generator_source = ast.unparse(self.generator)
        self.assertIn("queue.get()", generator_source)
        self.assertIn("if item is None:", generator_source)
        self.assertIn("finally:", generator_source)

    def test_cleanup_does_not_delete_shared_directory(self):
        endpoint_source = ast.unparse(self.endpoint)
        self.assertIn("mkdtemp(", endpoint_source)
        self.assertIn("rmtree(tmp_dir,", endpoint_source)


if __name__ == "__main__":
    unittest.main()
