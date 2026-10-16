"""Static regression guards for voice streaming cancellation and temp cleanup.

Runs without GPU, ASR, TTS or an Android device:
    PYTHONPATH=worker python tests/worker_voice_stream_cleanup.py
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
        self.assertIn("rmtree", endpoint_source)
        self.assertIn("tmp_dir", endpoint_source)

    def test_generator_runtime_cleans_files_on_normal_completion(self):
        """Execute the real nested generator with a fake completed producer."""
        import asyncio
        import json
        import tempfile

        async def scenario():
            with tempfile.TemporaryDirectory() as parent:
                tmp_dir = Path(parent) / "voice-turn"
                tmp_dir.mkdir()
                (tmp_dir / "chunk.wav").write_bytes(b"RIFF")
                queue = asyncio.Queue()
                await queue.put({"type": "done", "reply": "hej"})
                await queue.put(None)
                async def producer():
                    return None
                namespace = {
                    "_asyncio": asyncio, "_json": json,
                    "queue": queue, "tmp_dir": str(tmp_dir),
                    "run": producer,
                }
                # The nested gen() refers to task created in its own scope.
                gen_source = ast.unparse(self.generator)
                exec("async def wrapper():\n" + "\n".join("    " + line for line in gen_source.splitlines()) + "\n    return gen", namespace)
                stream = await namespace["wrapper"]()
                events = [json.loads(line) async for line in stream()]
                self.assertEqual(events[0]["type"], "done")
                self.assertFalse(tmp_dir.exists())
        asyncio.run(scenario())

    def test_generator_runtime_cleans_files_on_client_disconnect(self):
        """Closing the stream must cancel the producer and remove its WAVs."""
        import asyncio
        import json
        import tempfile

        async def scenario():
            with tempfile.TemporaryDirectory() as parent:
                tmp_dir = Path(parent) / "voice-turn"
                tmp_dir.mkdir()
                (tmp_dir / "chunk.wav").write_bytes(b"RIFF")
                queue = asyncio.Queue()
                await queue.put({"type": "transcript", "text": "hej"})
                cancelled = asyncio.Event()
                started = asyncio.Event()

                async def producer():
                    try:
                        started.set()
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()

                namespace = {
                    "_asyncio": asyncio, "_json": json,
                    "queue": queue, "tmp_dir": str(tmp_dir),
                    "run": producer,
                }
                gen_source = ast.unparse(self.generator)
                exec("async def wrapper():\n" + "\n".join("    " + line for line in gen_source.splitlines()) + "\n    return gen", namespace)
                stream = (await namespace["wrapper"]())()
                first = json.loads(await stream.__anext__())
                self.assertEqual(first["type"], "transcript")
                await asyncio.wait_for(started.wait(), timeout=3)
                await asyncio.wait_for(stream.aclose(), timeout=3)
                self.assertTrue(cancelled.is_set())
                self.assertFalse(tmp_dir.exists())
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
