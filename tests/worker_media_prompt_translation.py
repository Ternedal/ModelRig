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


# Shapes measured on the rig, Ollama 0.40.16, 18 Nov 2026 (#2418): a local qwen3:14b and a cloud model
# that was never pulled. The cloud model's /api/show answers 200 with details and NO remote_* field.
LOCAL_SHOW = {"license": "Apache", "modelfile": "FROM qwen3:4b", "parameters": "", "template": "{{ .Prompt }}",
              "details": {"parent_model": "", "format": "gguf", "family": "qwen3", "families": ["qwen3"],
                          "parameter_size": "4.0B", "quantization_level": "Q4_K_M"},
              "model_info": {}, "capabilities": ["completion"], "modified_at": "2026-11-15T10:00:00Z"}
CLOUD_SHOW_MEASURED = {"details": {"parent_model": "gpt-oss:120b", "format": "", "family": "gptoss", "families": None,
                                   "parameter_size": "116829156672", "quantization_level": "MXFP4"},
                       "model_info": {}, "capabilities": ["completion"], "modified_at": "2026-11-18T20:48:00Z"}
LOCAL_TAG = {"name": "qwen3:4b", "size": 2497293931, "details": {"format": "gguf", "family": "qwen3"}}
LOCAL_TAGS = {"models": [LOCAL_TAG, {"name": "nomic-embed-text:latest", "size": 274302450, "details": {"format": "gguf"}}]}


class ScriptedOllama:
    """One /api/generate answer per test: a JSON body, a raw body, a status or a delay. /api/show answers
    show_reply (local model metadata by default) with show_status. Records generate requests in
    `requests` and show requests in `shows`."""

    def __init__(self):
        self.requests = []
        self.shows = []
        self.show_reply = LOCAL_SHOW
        self.show_raw = None
        self.show_status = 200
        self.tags_reply = LOCAL_TAGS
        self.tags_gets = 0
        self.reply = {"response": ENGLISH}
        self.raw = None
        self.status = 200
        self.delay_s = 0.0
        self.location = None  # with a 3xx status: where the server tries to send the client
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/api/tags":
                    self.send_response(404)
                    self.end_headers()
                    return
                server.tags_gets += 1
                body = json.dumps(server.tags_reply).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/show":
                    server.shows.append(payload)
                    body = server.show_raw if server.show_raw is not None else json.dumps(server.show_reply).encode("utf-8")
                    self.send_response(server.show_status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                server.requests.append((self.path, payload))
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

    # --- execution: the model must be local by the daemon's own metadata (#2418 review, P2) ---------
    def test_a_cloud_tagged_model_is_refused_at_construction(self):
        for model in ("gpt-oss:120b-cloud", "qwen3-coder:480b-cloud", "deepseek-v3.1:671b-cloud", "kimi-k2:cloud",
                      "gpt-oss:CLOUD", "something-cloud"):
            with self.subTest(model=model), self.assertRaisesRegex(PromptTranslationConfigError, "cloud"):
                PromptTranslator(url=self.ollama.url, model=model)
        for model in ("qwen3:4b", "cloudy-llama:7b", "llama3.2:3b-instruct-q4"):
            with self.subTest(model=model):
                PromptTranslator(url=self.ollama.url, model=model)

    def test_the_model_is_checked_before_every_prompt_and_only_its_name_is_sent(self):
        self.assertEqual(self.rewrite(), (ENGLISH, "translated"))
        self.assertEqual(self.rewrite(), (ENGLISH, "translated"))
        self.assertEqual(self.ollama.shows, [{"model": "qwen3:4b"}, {"model": "qwen3:4b"}])
        self.assertEqual(self.ollama.tags_gets, 2, "the local inventory is read before every prompt too")

    def test_a_model_that_is_not_proven_local_gets_no_prompt(self):
        cases = [
            # (tags, show, raw show, show status, outcome)
            (LOCAL_TAGS, CLOUD_SHOW_MEASURED, None, 200, "fallback:model_not_local"),      # the measured cloud shape
            ({"models": [LOCAL_TAGS["models"][1]]}, LOCAL_SHOW, None, 200, "fallback:model_not_installed"),
            ({"models": []}, LOCAL_SHOW, None, 200, "fallback:model_not_installed"),
            ({"models": [{**LOCAL_TAG, "details": {"format": ""}}]}, LOCAL_SHOW, None, 200, "fallback:model_not_local"),
            ({"models": [{**LOCAL_TAG, "size": 0}]}, LOCAL_SHOW, None, 200, "fallback:model_not_local"),
            ({"models": [{**LOCAL_TAG, "size": "big"}]}, LOCAL_SHOW, None, 200, "fallback:model_not_local"),
            ({"models": [{**LOCAL_TAG, "remote_host": "https://ollama.com:443"}]}, LOCAL_SHOW, None, 200,
             "fallback:model_not_local"),
            (LOCAL_TAGS, {**LOCAL_SHOW, "remote_model": "gpt-oss:120b"}, None, 200, "fallback:model_not_local"),
            (LOCAL_TAGS, {k: v for k, v in LOCAL_SHOW.items() if k != "modelfile"}, None, 200, "fallback:model_not_local"),
            (LOCAL_TAGS, {**LOCAL_SHOW, "details": {**LOCAL_SHOW["details"], "format": "safetensors"}}, None, 200,
             "fallback:model_not_local"),
            (LOCAL_TAGS, {**LOCAL_SHOW, "details": "gguf"}, None, 200, "fallback:model_unverified"),
            (LOCAL_TAGS, None, b"<html>not json", 200, "fallback:model_unverified"),
            (LOCAL_TAGS, None, b"\xff\xfe", 200, "fallback:model_unverified"),
            (LOCAL_TAGS, {"error": "model 'qwen3:4b' not found"}, None, 404, "fallback:http_404"),
            ({"tags": []}, LOCAL_SHOW, None, 200, "fallback:model_unverified"),
            (["qwen3:4b"], LOCAL_SHOW, None, 200, "fallback:model_unverified"),
        ]
        for tags, show, raw, status, outcome in cases:
            with self.subTest(outcome=outcome, tags=str(tags)[:40], show=str(show or raw)[:40]):
                self.ollama.requests.clear()
                self.ollama.tags_reply = tags
                self.ollama.show_reply, self.ollama.show_raw, self.ollama.show_status = show, raw, status
                self.assertEqual(self.rewrite(), (DANISH, outcome))
                self.assertEqual(self.ollama.requests, [], "no /api/generate, so the prompt was never sent")
        self.ollama.tags_reply = LOCAL_TAGS
        self.ollama.show_reply, self.ollama.show_raw, self.ollama.show_status = LOCAL_SHOW, None, 200
        self.assertEqual(self.rewrite(), (ENGLISH, "translated"), "a proven local model translates")
        self.ollama.show_reply = {**LOCAL_SHOW, "remote_host": "", "remote_model": None}
        self.assertEqual(self.rewrite(), (ENGLISH, "translated"), "empty remote_* fields are not a remote model")

    def test_an_untagged_model_name_is_looked_up_as_latest(self):
        untagged = PromptTranslator(url=self.ollama.url, model="nomic-embed-text", timeout_s=5)
        self.assertEqual(untagged.rewrite(DANISH, max_chars=500), (ENGLISH, "translated"))
        self.ollama.tags_reply = {"models": [LOCAL_TAG]}
        self.assertEqual(untagged.rewrite(DANISH, max_chars=500), (DANISH, "fallback:model_not_installed"))

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
