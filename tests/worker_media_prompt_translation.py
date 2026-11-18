"""Prompt translation for the media executor: loopback only, fail-open, bounded (#2275, 17 Nov 2026).

Ollama is a real local HTTP server in a thread, scripted per test; nothing is mocked inside the
translator except the clock-free parts. The executor-side contract (outcome events, never prompt
text, the original prompt on every fallback) is in tests/worker_media_executor.py.
"""
import json
import os
import sys
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "worker"))

from app.media_prompt_translation import (  # noqa: E402
    DEFAULT_URL,
    MODEL_ENV,
    TIMEOUT_ENV,
    URL_ENV,
    PromptTranslationConfigError,
    PromptTranslator,
    translator_from_env,
)

DANISH = "en mand i sort frakke ved en sø, en svane i baggrunden"
ENGLISH = "a man in a black coat by a lake, a swan in the background"


class ScriptedOllama:
    """One answer per test: a JSON body, a raw body, a status or a delay. Records every request."""

    def __init__(self):
        self.requests = []
        self.reply = {"response": ENGLISH}
        self.raw = None
        self.status = 200
        self.delay_s = 0.0
        self.location = None  # with a 3xx status: where the server tries to send the client
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                server.requests.append((self.path, json.loads(self.rfile.read(length) or b"{}")))
                if server.delay_s:
                    time.sleep(server.delay_s)
                body = server.raw if server.raw is not None else json.dumps(server.reply).encode("utf-8")
                self.send_response(server.status)
                if server.location:
                    self.send_header("Location", server.location)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ConfigTests(unittest.TestCase):
    def test_only_a_plain_http_loopback_url_is_accepted(self):
        for url in (DEFAULT_URL, "http://127.0.0.1:11434/", "http://[::1]:11434", "http://127.5.5.5:11434",
                    "http://[::ffff:127.0.0.1]:11434"):  # IPv4 loopback on a dual-stack socket: numeric, loopback
            with self.subTest(url=url):
                PromptTranslator(url=url, model="qwen3:4b")
        for url in ("https://ollama.com", "https://127.0.0.1:11434", "http://192.168.1.10:11434",
                    "http://ollama.local:11434", "http://127.0.0.1:11434/api", "http://user:pw@127.0.0.1:11434",
                    "http://127.0.0.1:11434?x=1", "127.0.0.1:11434", "", None, 11434,
                    # names are resolved by someone else at connect time: only numeric loopback literals
                    "http://localhost:11434", "http://127.0.0.1.nip.io:11434", "http://[::ffff:10.0.0.1]:11434",
                    "http://0.0.0.0:11434", "http://0177.0.0.1:11434", "http://2130706433:11434"):
            with self.subTest(url=url), self.assertRaises(PromptTranslationConfigError):
                PromptTranslator(url=url, model="qwen3:4b")

    def test_model_and_timeout_are_strict(self):
        for model in ("", " ", "qwen3 4b", "../x", None, 3, "a" * 129):
            with self.subTest(model=model), self.assertRaises(PromptTranslationConfigError):
                PromptTranslator(model=model)
        for timeout in (0, 0.5, 301, "30", None, float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(PromptTranslationConfigError):
                PromptTranslator(model="qwen3:4b", timeout_s=timeout)

    def test_from_env_is_off_without_a_model_and_strict_with_one(self):
        self.assertIsNone(translator_from_env({}))
        self.assertIsNone(translator_from_env({MODEL_ENV: "  "}))
        on = translator_from_env({MODEL_ENV: "qwen3:4b"})
        self.assertEqual((on.url, on.model, on.timeout_s), (DEFAULT_URL, "qwen3:4b", 30.0))
        custom = translator_from_env({MODEL_ENV: "qwen3:4b", URL_ENV: "http://127.0.0.1:11435/", TIMEOUT_ENV: "12"})
        self.assertEqual((custom.url, custom.timeout_s), ("http://127.0.0.1:11435", 12.0))
        for env in ({MODEL_ENV: "qwen3:4b", URL_ENV: "https://ollama.com"},
                    {MODEL_ENV: "qwen3:4b", TIMEOUT_ENV: "soon"},
                    {MODEL_ENV: "qwen3:4b", TIMEOUT_ENV: "0"}):
            with self.subTest(env=env), self.assertRaises(PromptTranslationConfigError):
                translator_from_env(env)


class RewriteTests(unittest.TestCase):
    def setUp(self):
        self.ollama = ScriptedOllama()
        self.addCleanup(self.ollama.close)
        self.translator = PromptTranslator(url=self.ollama.url, model="qwen3:4b", timeout_s=5)

    def rewrite(self, prompt=DANISH, max_chars=500):
        return self.translator.rewrite(prompt, max_chars=max_chars)

    def test_translates_and_sends_exactly_what_ollama_needs(self):
        self.assertEqual(self.rewrite(), (ENGLISH, "translated"))
        (path, body), = self.ollama.requests
        self.assertEqual(path, "/api/generate")
        self.assertEqual((body["model"], body["prompt"], body["stream"], body["think"]), ("qwen3:4b", DANISH, False, False))
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertIn("English", body["system"])
        self.assertGreater(self.translator.last_duration_s, 0)

    def test_an_already_english_prompt_is_reported_unchanged(self):
        self.ollama.reply = {"response": ENGLISH}
        self.assertEqual(self.rewrite(ENGLISH), (ENGLISH, "unchanged"))
        self.assertEqual(self.rewrite("  " + ENGLISH + " \n"), ("  " + ENGLISH + " \n", "unchanged"),
                         "the original is returned as it was, not the cleaned copy")

    def test_thinking_quotes_and_line_breaks_are_cleaned_away(self):
        for raw in (f"<think>Danish to English.\nEasy.</think>\n\n\"{ENGLISH}\"\n",
                    f"'{ENGLISH}'", f"“{ENGLISH}”", f"  {ENGLISH.replace(', ', ',\n')}  "):
            with self.subTest(raw=raw[:30]):
                self.ollama.reply = {"response": raw}
                prompt, outcome = self.rewrite()
                self.assertEqual(outcome, "translated")
                self.assertEqual(prompt.replace(",", ", ").replace(",  ", ", "), ENGLISH)
                self.assertNotIn("\n", prompt)

    def test_every_bad_answer_falls_back_to_the_original(self):
        cases = [
            ({"response": ""}, "fallback:empty"),
            ({"response": "<think>only thoughts</think>"}, "fallback:empty"),
            ({"response": "\"\""}, "fallback:empty"),
            ({"response": ENGLISH + " " + "word " * 100}, "fallback:too_long"),
            ({"response": "x" * 501}, "fallback:too_long"),
            ({"response": "bad\x00byte"}, "fallback:unprintable"),
            ({"no_response": 1}, "fallback:bad_reply"),
            ({"response": 42}, "fallback:bad_reply"),
            ([ENGLISH], "fallback:bad_reply"),
        ]
        for reply, outcome in cases:
            with self.subTest(outcome=outcome, reply=str(reply)[:40]):
                self.ollama.reply, self.ollama.raw = reply, None
                self.assertEqual(self.rewrite(), (DANISH, outcome))
        self.ollama.raw = b"<html>not json"
        self.assertEqual(self.rewrite(), (DANISH, "fallback:bad_reply"))

    def test_the_profile_limit_is_respected_even_for_a_good_translation(self):
        self.assertEqual(self.rewrite(max_chars=len(ENGLISH) - 1), (DANISH, "fallback:too_long"))
        self.assertEqual(self.rewrite(max_chars=len(ENGLISH)), (ENGLISH, "translated"))

    def test_http_errors_timeouts_and_a_dead_server_fall_back(self):
        self.ollama.status = 500
        self.assertEqual(self.rewrite(), (DANISH, "fallback:http_500"))
        self.ollama.status = 404
        self.assertEqual(self.rewrite(), (DANISH, "fallback:http_404"))
        self.ollama.status = 200
        slow = PromptTranslator(url=self.ollama.url, model="qwen3:4b", timeout_s=1)
        self.ollama.delay_s = 1.6
        self.assertEqual(slow.rewrite(DANISH, max_chars=500), (DANISH, "fallback:timeout"))
        self.ollama.delay_s = 0.0
        dead = ScriptedOllama()
        dead.close()
        gone = PromptTranslator(url=dead.url, model="qwen3:4b", timeout_s=2)
        self.assertEqual(gone.rewrite(DANISH, max_chars=500), (DANISH, "fallback:unreachable"))

    def test_an_opener_that_raises_anything_still_falls_back(self):
        def boom(request, timeout):
            raise RuntimeError("socket library on fire")
        odd = PromptTranslator(url=DEFAULT_URL, model="qwen3:4b", opener=boom)
        self.assertEqual(odd.rewrite(DANISH, max_chars=500), (DANISH, "fallback:error"))

    # --- transport: the bytes of a prompt can only reach the accepted loopback literal ---------------
    def test_proxy_environment_is_ignored_and_the_request_goes_straight_to_loopback(self):
        proxy = ScriptedOllama()  # stands in for a proxy: if the client honoured the environment it would be hit
        self.addCleanup(proxy.close)
        env = {"HTTP_PROXY": proxy.url, "http_proxy": proxy.url, "HTTPS_PROXY": proxy.url, "https_proxy": proxy.url,
               "ALL_PROXY": proxy.url, "all_proxy": proxy.url, "NO_PROXY": "", "no_proxy": ""}
        with patch.dict(os.environ, env, clear=False):
            direct = PromptTranslator(url=self.ollama.url, model="qwen3:4b", timeout_s=5)
            self.assertEqual(direct.rewrite(DANISH, max_chars=500), (ENGLISH, "translated"))
            # the environment-honouring default client WOULD have used the proxy: prove the test can tell
            handler = urllib.request.ProxyHandler()  # reads the environment
            self.assertEqual(handler.proxies.get("http"), proxy.url)
        self.assertEqual(len(self.ollama.requests), 1, "Ollama got the request")
        self.assertEqual(proxy.requests, [], "the proxy saw nothing")

    def test_a_redirect_is_refused_and_nothing_is_sent_to_its_target(self):
        elsewhere = ScriptedOllama()  # the redirect target; loopback here, but the point is: never followed
        self.addCleanup(elsewhere.close)
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.ollama.requests.clear()
                self.ollama.status, self.ollama.location = status, elsewhere.url + "/api/generate"
                self.assertEqual(self.rewrite(), (DANISH, f"fallback:http_{status}"))
                self.assertEqual(len(self.ollama.requests), 1)
                self.assertEqual(elsewhere.requests, [], "the redirect target saw nothing")
        self.ollama.status, self.ollama.location = 200, None

    def test_the_default_client_has_no_proxy_handler_and_refuses_redirects(self):
        from app.media_prompt_translation import _RefuseRedirects, local_only_opener
        opener = local_only_opener().__self__
        # build_opener drops the environment-reading ProxyHandler because one of that class was given,
        # and an empty one registers no protocol at all: the chain has NO proxy handling whatsoever.
        self.assertFalse(any(isinstance(h, urllib.request.ProxyHandler) for h in opener.handlers))
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9/"}):
            default = urllib.request.build_opener()
        self.assertTrue(any(isinstance(h, urllib.request.ProxyHandler) for h in default.handlers),
                        "the stock opener WOULD carry the environment proxy: that is what is being refused")
        self.assertTrue(any(isinstance(h, _RefuseRedirects) for h in opener.handlers))
        self.assertFalse(any(type(h) is urllib.request.HTTPRedirectHandler for h in opener.handlers),
                         "the following redirect handler is not installed")

    def test_the_real_opener_is_urlopen_called_with_a_keyword_timeout(self):
        seen = {}

        def opener(request, timeout):
            seen["timeout"] = timeout
            raise urllib.error.URLError(TimeoutError())
        self.assertEqual(PromptTranslator(model="qwen3:4b", timeout_s=7, opener=opener).rewrite("x", max_chars=5),
                         ("x", "fallback:timeout"))
        self.assertEqual(seen["timeout"], 7.0)
        self.assertIsNot(PromptTranslator(model="qwen3:4b")._opener, urllib.request.urlopen,
                         "the environment-honouring default client is never the translator's client")


if __name__ == "__main__":
    unittest.main()
