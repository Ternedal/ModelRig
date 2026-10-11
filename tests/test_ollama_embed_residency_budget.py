"""Regression guards for the opt-in embedding residency budget."""
import importlib
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class EmbedResidencyBudgetTests(unittest.IsolatedAsyncioTestCase):
    def _load(self, **values):
        with patch.dict(os.environ, values, clear=False):
            sys.modules.pop("worker.app.ollama_client", None)
            return importlib.import_module("worker.app.ollama_client")

    def test_default_matches_generation(self):
        with patch.dict(os.environ, {"MODELRIG_OLLAMA_KEEP_ALIVE": "30m"}, clear=False):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("MODELRIG_OLLAMA_EMBED_KEEP_ALIVE", None)
                mod = self._load()
                self.assertEqual(mod.EMBED_KEEP_ALIVE, mod.KEEP_ALIVE)

    async def test_embedding_only_uses_override(self):
        mod = self._load(MODELRIG_OLLAMA_KEEP_ALIVE="30m",
                         MODELRIG_OLLAMA_EMBED_KEEP_ALIVE="1m")
        response = MagicMock(status_code=200)
        response.json.side_effect = [{"embeddings": [[0.1, 0.2]]}, {"message": {"content": "ok"}}]
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(mod.httpx, "AsyncClient", return_value=context):
            self.assertEqual(await mod.embed("hello"), [0.1, 0.2])
            self.assertEqual(client.post.call_args.kwargs["json"]["keep_alive"], "1m")
            await mod.chat([{"role": "user", "content": "hello"}])
            self.assertEqual(client.post.call_args.kwargs["json"]["keep_alive"], "30m")


if __name__ == "__main__":
    unittest.main()
