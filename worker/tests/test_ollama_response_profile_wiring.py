"""Default-off Ollama worker integration contracts; no live Ollama needed."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from app import ollama_client as oc


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"message": {"content": "Hej"}}


class _Client:
    def __init__(self, captured):
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json):
        self.captured.append({"url": url, "payload": json})
        return _Response()


class WorkerProfileWiringTests(unittest.TestCase):
    def _call(self, mode):
        captured = []
        original = [{"role": "system", "content": "Guard"},
                    {"role": "user", "content": "Hej"}]
        environ = {} if mode is None else {"MODELRIG_EXPERIMENTAL_CHAT_PROFILE": mode}
        with patch.dict(os.environ, environ, clear=True), patch.object(
            oc.httpx, "AsyncClient", side_effect=lambda **kwargs: _Client(captured)
        ):
            answer = asyncio.run(oc.chat(original, model="gemma4:26b"))
        self.assertEqual(answer, "Hej")
        self.assertEqual(original[0]["content"], "Guard")
        return captured[0]["payload"]

    def test_default_unchanged(self):
        result = self._call(None)
        self.assertEqual(set(result), {"model", "messages", "stream", "keep_alive"})
        self.assertEqual(result["messages"][0]["content"], "Guard")

    def test_opt_in_profile(self):
        result = self._call("voice_brief")
        self.assertFalse(result["think"])
        self.assertEqual(result["options"]["num_predict"], 128)
        self.assertTrue(result["messages"][0]["content"].startswith("Guard\n\n"))

    def test_explicit_unsupported_mode_aborts_before_network(self):
        with patch.dict(os.environ, {"MODELRIG_EXPERIMENTAL_CHAT_PROFILE": "invalid"}), patch.object(
            oc.httpx, "AsyncClient"
        ) as client:
            with self.assertRaises(ValueError):
                asyncio.run(oc.chat([{"role": "user", "content": "Hej"}]))
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
