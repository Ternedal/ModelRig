"""Regression guards for opt-in embedding residency, with isolated imports."""
import importlib
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


MODULE = "app.ollama_client"


class EmbedResidencyBudgetTests(unittest.IsolatedAsyncioTestCase):
    def _load(self, **values):
        # Keep the imported module's constants scoped to each test, and avoid
        # mutating the parent process environment or contaminating other tests.
        env = dict(os.environ)
        env.pop("MODELRIG_OLLAMA_EMBED_KEEP_ALIVE", None)
        env.pop("MODELRIG_OLLAMA_MAX_OUTPUT_TOKENS", None)
        env.update(values)
        with patch.dict(os.environ, env, clear=True):
            with patch.dict(sys.modules):
                sys.modules.pop(MODULE, None)
                return importlib.import_module(MODULE)

    def test_default_matches_generation(self):
        mod = self._load(MODELRIG_OLLAMA_KEEP_ALIVE="30m")
        self.assertEqual(mod.EMBED_KEEP_ALIVE, "30m")
        self.assertEqual(mod.EMBED_KEEP_ALIVE, mod.KEEP_ALIVE)

    async def test_embedding_only_uses_override(self):
        mod = self._load(MODELRIG_OLLAMA_KEEP_ALIVE="30m",
                         MODELRIG_OLLAMA_EMBED_KEEP_ALIVE="1m")
        response = MagicMock(status_code=200)
        response.json.side_effect = [
            {"embeddings": [[0.1, 0.2]]},
            {"message": {"content": "ok"}},
        ]
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(mod.httpx, "AsyncClient", return_value=context):
            self.assertEqual(await mod.embed("hello"), [0.1, 0.2])
            self.assertEqual(client.post.call_args.kwargs["json"]["keep_alive"], "1m")
            self.assertEqual(
                await mod.chat([{"role": "user", "content": "hello"}]), "ok"
            )
            self.assertEqual(client.post.call_args.kwargs["json"]["keep_alive"], "30m")

    def test_output_budget_is_opt_in_and_validated(self):
        default = self._load()
        self.assertEqual(default._output_options(), {})
        limited = self._load(MODELRIG_OLLAMA_MAX_OUTPUT_TOKENS="256")
        self.assertEqual(limited._output_options(), {"options": {"num_predict": 256}})
        invalid = self._load(MODELRIG_OLLAMA_MAX_OUTPUT_TOKENS="0")
        with self.assertRaises(invalid.OllamaError):
            invalid._output_options()
        invalid_text = self._load(MODELRIG_OLLAMA_MAX_OUTPUT_TOKENS="oops")
        with self.assertRaises(invalid_text.OllamaError):
            invalid_text._output_options()

    async def test_local_chat_uses_cap_but_cloud_tools_do_not(self):
        mod = self._load(MODELRIG_OLLAMA_MAX_OUTPUT_TOKENS="128")
        response = MagicMock(status_code=200)
        response.json.return_value = {"message": {"content": "ok"}}
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(mod.httpx, "AsyncClient", return_value=context):
            self.assertEqual(await mod.chat([{"role": "user", "content": "hi"}]), "ok")
            self.assertEqual(
                client.post.await_args.kwargs["json"]["options"]["num_predict"], 128
            )
            with patch.object(mod, "_validate_cloud_url", return_value=None):
                await mod.chat_tools([], [], base_url="https://example.com")
            self.assertNotIn("options", client.post.await_args.kwargs["json"])
            self.assertNotIn("keep_alive", client.post.await_args.kwargs["json"])

    async def test_local_tools_request_honors_cap(self):
        mod = self._load(MODELRIG_OLLAMA_MAX_OUTPUT_TOKENS="64")
        response = MagicMock(status_code=200)
        response.json.return_value = {"message": {"content": "ok"}}
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(mod.httpx, "AsyncClient", return_value=context):
            result = await mod.chat_tools([{"role": "user", "content": "hi"}], [])
        self.assertEqual(result["content"], "ok")
        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(payload["options"], {"num_predict": 64})
        self.assertEqual(payload["keep_alive"], mod.KEEP_ALIVE)

    def test_output_budget_rejects_negative_and_excessive_values(self):
        for value in ("-1", "131073", "2.5", "NaN"):
            with self.subTest(value=value):
                mod = self._load(MODELRIG_OLLAMA_MAX_OUTPUT_TOKENS=value)
                with self.assertRaises(mod.OllamaError):
                    mod._output_options()

    async def test_legacy_embed_fallback_uses_embedding_override(self):
        mod = self._load(MODELRIG_OLLAMA_KEEP_ALIVE="30m",
                         MODELRIG_OLLAMA_EMBED_KEEP_ALIVE="0")
        modern = MagicMock(status_code=405)
        legacy = MagicMock(status_code=200)
        legacy.json.return_value = {"embedding": [0.3]}
        client = AsyncMock()
        client.post.side_effect = [modern, legacy]
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(mod.httpx, "AsyncClient", return_value=context):
            self.assertEqual(await mod.embed("hello"), [0.3])
            self.assertEqual(client.post.await_count, 2)
            for call in client.post.await_args_list:
                self.assertEqual(call.kwargs["json"]["keep_alive"], "0")


if __name__ == "__main__":
    unittest.main()
