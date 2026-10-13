"""Default-off Ollama worker integration contracts; no live Ollama needed."""
import asyncio
import os
import unittest
from unittest.mock import patch

from app import ollama_client as oc


class _Response:
    status_code = 200
    text = ""
    response_data = {"message": {"content": "Hej"}}

    def json(self):
        return self.response_data


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

    def test_opt_in_rejects_truncated_and_empty_answers(self):
        for data in (
            {"message": {"content": "Incomplete"}, "done_reason": "length"},
            {"message": {"content": ""}, "done_reason": "stop"},
            {"message": {"content": "   "}, "done_reason": "stop"},
        ):
            with self.subTest(data=data), patch.dict(
                os.environ, {"MODELRIG_EXPERIMENTAL_CHAT_PROFILE": "voice_brief"}
            ), patch.object(
                oc.httpx, "AsyncClient", side_effect=lambda **kwargs: _Client([])
            ), patch.object(_Response, "response_data", data):
                with self.assertRaises(oc.OllamaError):
                    asyncio.run(oc.chat([{"role": "user", "content": "Hej"}]))

    def test_default_preserves_legacy_empty_behavior(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            oc.httpx, "AsyncClient", side_effect=lambda **kwargs: _Client([])
        ), patch.object(_Response, "response_data",
                        {"message": {"content": ""}, "done_reason": "length"}):
            self.assertEqual(asyncio.run(
                oc.chat([{"role": "user", "content": "Hej"}])), "")


    def test_retry_once_on_length_then_success(self):
        captured = []
        responses = [
            {"message": {"content": "Afbrudt"}, "done_reason": "length"},
            {"message": {"content": "Færdigt"}, "done_reason": "stop"},
        ]

        class SequentialClient(_Client):
            async def post(self, url, json):
                self.captured.append({"url": url, "payload": json})
                response = _Response()
                response.response_data = responses.pop(0)
                return response

        with patch.dict(os.environ, {"MODELRIG_EXPERIMENTAL_CHAT_PROFILE": "voice_brief"}), patch.object(
            oc.httpx, "AsyncClient", side_effect=lambda **kwargs: SequentialClient(captured)
        ):
            result = asyncio.run(oc.chat([{"role": "user", "content": "Hej"}]))
        self.assertEqual(result, "Færdigt")
        self.assertEqual(len(captured), 2)
        self.assertEqual([x["payload"]["options"]["num_predict"] for x in captured], [128, 256])

    def test_no_retry_on_empty_content(self):
        captured = []
        with patch.dict(os.environ, {"MODELRIG_EXPERIMENTAL_CHAT_PROFILE": "voice_brief"}), patch.object(
            oc.httpx, "AsyncClient", side_effect=lambda **kwargs: _Client(captured)
        ), patch.object(_Response, "response_data",
                        {"message": {"content": ""}, "done_reason": "stop"}):
            with self.assertRaises(oc.OllamaError):
                asyncio.run(oc.chat([{"role": "user", "content": "Hej"}]))
        self.assertEqual(len(captured), 1)

    def test_second_length_response_fails_after_exactly_two_calls(self):
        captured = []
        with patch.dict(os.environ, {"MODELRIG_EXPERIMENTAL_CHAT_PROFILE": "voice_brief"}), patch.object(
            oc.httpx, "AsyncClient", side_effect=lambda **kwargs: _Client(captured)
        ), patch.object(_Response, "response_data",
                        {"message": {"content": "Partial"}, "done_reason": "length"}):
            with self.assertRaisesRegex(oc.OllamaError, "after retry"):
                asyncio.run(oc.chat([{"role": "user", "content": "Hej"}]))
        self.assertEqual(len(captured), 2)

    def test_http_failure_does_not_retry(self):
        captured = []

        class BadResponse(_Response):
            status_code = 503
            text = "server unavailable"

        class BadClient(_Client):
            async def post(self, url, json):
                self.captured.append(json)
                return BadResponse()

        with patch.dict(os.environ, {"MODELRIG_EXPERIMENTAL_CHAT_PROFILE": "voice_brief"}), patch.object(
            oc.httpx, "AsyncClient", side_effect=lambda **kwargs: BadClient(captured)
        ):
            with self.assertRaisesRegex(oc.OllamaError, "503"):
                asyncio.run(oc.chat([{"role": "user", "content": "Hej"}]))
        self.assertEqual(len(captured), 1)

    def test_explicit_unsupported_mode_aborts_before_network(self):
        with patch.dict(os.environ, {"MODELRIG_EXPERIMENTAL_CHAT_PROFILE": "invalid"}), patch.object(
            oc.httpx, "AsyncClient"
        ) as client:
            with self.assertRaises(ValueError):
                asyncio.run(oc.chat([{"role": "user", "content": "Hej"}]))
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
