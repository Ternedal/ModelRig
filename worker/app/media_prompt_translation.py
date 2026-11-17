"""Prompt translation for the media executor: Danish (any language) -> English, locally, fail-open.

The first rig run (17 Nov 2026, #2275) showed that SDXL and the Wan video models only really
understand English: a Danish prompt produced visibly worse, often absurd images; the same subject
in English did not. Kaliv is Danish-first, so the translation belongs in the rig, not in the user.

Rules:
- **Local only.** The translator talks to one Ollama at a loopback URL. A URL with any other host,
  or any scheme but http, is refused at construction (D4: nothing of a media job leaves the rig,
  and this is not the chat path, so the cloud policy's "current message" exception does not apply).
- **Fail-open.** Whatever goes wrong (Ollama down, timeout, bad JSON, an answer that is empty,
  too long, not printable or not one line), the job renders with the user's original prompt.
  A translation problem never fails a job.
- **Bounded.** The answer must fit the profile's prompt limit and may not be much longer than the
  input, so a chatty or runaway model cannot replace the prompt with an essay.
- **Private.** Prompt text is never logged here; the caller records an outcome code and a duration.

Nothing here imports torch; the executor runs it inside the media venv with the standard library.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

MODEL_ENV = "KALIV_MEDIA_TRANSLATE_MODEL"      # set -> translation on; unset -> prompts pass through
URL_ENV = "KALIV_MEDIA_TRANSLATE_URL"          # default http://127.0.0.1:11434; loopback only
TIMEOUT_ENV = "KALIV_MEDIA_TRANSLATE_TIMEOUT_S"  # default 30
DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_S = 30.0
MAX_TIMEOUT_S = 300.0
MAX_OUTPUT_TOKENS = 400
# A translation of an image prompt is about as long as the prompt. Allow for English being
# wordier than Danish and for a short prompt growing a little, nothing more.
GROWTH_FACTOR, GROWTH_SLACK = 2.5, 40

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_LOOPBACK_HOSTS = frozenset({"localhost", "::1"})
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_SPACE = re.compile(r"\s+")
_QUOTE_PAIRS = frozenset({('"', '"'), ("'", "'"), ("`", "`"), ("“", "”"), ("‘", "’"), ("«", "»")})

SYSTEM_PROMPT = (
    "You translate prompts for a text-to-image model into English. "
    "Reply with the translated prompt only: one line, no quotes, no explanation, no notes. "
    "Keep proper names, numbers, camera and style terms as they are. "
    "If the prompt is already English, reply with it unchanged."
)

Opener = Callable[..., object]  # urllib.request.urlopen(request, timeout=...) or a test double


class PromptTranslationConfigError(ValueError):
    pass


def _is_loopback(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "http" or parts.username or parts.password or parts.path not in ("", "/"):
        return False
    if parts.query or parts.fragment:
        return False
    host = (parts.hostname or "").lower()
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def translator_from_env(env, *, opener: Opener | None = None) -> "PromptTranslator | None":
    """None when KALIV_MEDIA_TRANSLATE_MODEL is unset: the executor then renders prompts as given."""
    model = (env.get(MODEL_ENV) or "").strip()
    if not model:
        return None
    url = (env.get(URL_ENV) or DEFAULT_URL).strip()
    raw_timeout = (env.get(TIMEOUT_ENV) or "").strip()
    try:
        timeout_s = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_S
    except ValueError:
        raise PromptTranslationConfigError(f"{TIMEOUT_ENV} must be a number of seconds") from None
    return PromptTranslator(url=url, model=model, timeout_s=timeout_s, **({"opener": opener} if opener else {}))


class PromptTranslator:
    def __init__(self, *, url: str = DEFAULT_URL, model: str, timeout_s: float = DEFAULT_TIMEOUT_S,
                 opener: Opener = urllib.request.urlopen):
        if not isinstance(url, str) or not _is_loopback(url):
            raise PromptTranslationConfigError(f"{URL_ENV} must be a plain http URL on loopback (media never leaves the rig)")
        if not isinstance(model, str) or not _MODEL.fullmatch(model):
            raise PromptTranslationConfigError(f"{MODEL_ENV} is malformed")
        if type(timeout_s) not in (int, float) or not 1 <= timeout_s <= MAX_TIMEOUT_S:
            raise PromptTranslationConfigError(f"{TIMEOUT_ENV} must be 1..{int(MAX_TIMEOUT_S)} seconds")
        self.url = url.rstrip("/")
        self.model = model
        self.timeout_s = float(timeout_s)
        self._opener = opener
        self.last_duration_s = 0.0

    def rewrite(self, prompt: str, *, max_chars: int) -> tuple[str, str]:
        """Return (prompt to render, outcome). outcome is 'translated', 'unchanged' or 'fallback:<code>';
        on any fallback the prompt is the original. Never raises, never logs the prompt."""
        try:
            text = self._ask(prompt)
        except urllib.error.HTTPError as exc:
            return prompt, f"fallback:http_{exc.code}"
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            return prompt, "fallback:timeout" if isinstance(reason, TimeoutError) else "fallback:unreachable"
        except TimeoutError:
            return prompt, "fallback:timeout"
        except (ValueError, TypeError, KeyError, OSError):
            return prompt, "fallback:bad_reply"
        except Exception:  # fail-open is the contract: a translator bug renders the original
            return prompt, "fallback:error"
        cleaned = self._clean(text)
        if not cleaned:
            return prompt, "fallback:empty"
        if not cleaned.isprintable():
            return prompt, "fallback:unprintable"
        if len(cleaned) > max_chars or len(cleaned) > len(prompt) * GROWTH_FACTOR + GROWTH_SLACK:
            return prompt, "fallback:too_long"
        if cleaned == prompt.strip():
            return prompt, "unchanged"
        return cleaned, "translated"

    def _ask(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "think": False,  # qwen3 and friends: no reasoning preamble; older servers ignore the key
            "options": {"temperature": 0, "num_predict": MAX_OUTPUT_TOKENS},
        }).encode("utf-8")
        request = urllib.request.Request(self.url + "/api/generate", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        started = time.monotonic()
        with self._opener(request, timeout=self.timeout_s) as response:
            raw = response.read(1 << 20)  # a translation is small; a megabyte is already wrong
        self.last_duration_s = time.monotonic() - started
        reply = json.loads(raw.decode("utf-8"))
        if not isinstance(reply, dict) or not isinstance(reply.get("response"), str):
            raise ValueError("no response text")
        return reply["response"]

    @staticmethod
    def _clean(text: str) -> str:
        text = _THINK.sub("", text)
        text = _SPACE.sub(" ", text).strip()
        # Models like to quote the answer; the quotes would reach the image model as tokens.
        while len(text) >= 2 and (text[0], text[-1]) in _QUOTE_PAIRS:
            text = text[1:-1].strip()
        return text
