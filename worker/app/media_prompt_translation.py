"""Prompt translation for the media executor: Danish (any language) -> English, locally, fail-open.

The first rig run (17 Nov 2026, #2275) showed that SDXL and the Wan video models only really
understand English: a Danish prompt produced visibly worse, often absurd images; the same subject
in English did not. Kaliv is Danish-first, so the translation belongs in the rig, not in the user.

Rules:
- **Local only, enforced in transport.** The translator talks to one Ollama at a NUMERIC loopback URL
  (127.x or ::1, plain http, no path). Anything else is refused at construction. Its HTTP client is its
  own: proxies are never consulted whatever HTTP_PROXY/http_proxy say, redirects are refused, so the
  bytes of a prompt can only go to the literal address that was accepted (D4: nothing of a media job
  leaves the rig; this is not the chat path, so the cloud policy's "current message" exception does
  not apply).
- **Local model only, checked before every prompt.** A local Ollama daemon also runs cloud models
  (Ollama Cloud, tags like `gpt-oss:120b-cloud`) by forwarding the prompt upstream, past every
  transport guarantee above (#2418 review, P2). So a cloud-tagged model name is refused at
  construction, and before each `/api/generate` the translator asks the daemon about the model
  (`/api/show`): the answer must be local model metadata (a `details` object) with no `remote_*`
  field, or the job renders the original prompt and nothing is sent (`fallback:model_not_local`,
  `fallback:model_unverified`). Limitation, kept honest: which fields mark a remote model is
  Ollama's contract, not ours; docs/MEDIA_PROMPT_TRANSLATION.md says how to check it on the rig.
- **Fail-open.** Whatever goes wrong (Ollama down, timeout, bad JSON, an answer that is empty,
  too long, not printable or not one line), the job renders with the user's original prompt.
  A translation problem never fails a job.
- **Bounded.** The answer must fit the profile's prompt limit and may not be much longer than the
  input, so a chatty or runaway model cannot replace the prompt with an essay.
- **Private, but accountable.** Prompt text is never logged here; the caller records an outcome code
  and a duration, and when the translation changed the prompt it stores the rendered text on the job
  (`effective_prompt`, same retention as the original) so the owner can see what was rendered.

Nothing here imports torch; the executor runs it inside the media venv with the standard library.
"""
from __future__ import annotations

import ipaddress
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .netguard import is_loopback

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


class _ModelNotLocal(Exception):
    """The daemon did not show the model as local; the outcome code says why. Not a ValueError, so
    it is never mistaken for a bad generate reply."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _is_cloud_tagged(model: str) -> bool:
    """Ollama Cloud models carry a `cloud` tag (`name:cloud`) or a `-cloud` suffix on the tag."""
    tag = model.rsplit(":", 1)[-1].lower() if ":" in model else ""
    return tag == "cloud" or tag.endswith("-cloud") or model.lower().endswith("-cloud")


def _is_local_ollama_url(url: str) -> bool:
    """Plain http, nothing but a NUMERIC host and port, and the host is loopback by the worker's ONE
    loopback predicate (app/netguard.py, kept single on purpose by tests/workflow_worker_entrypoints.py).
    Numeric only: a name ("localhost", anything in the hosts file or DNS) is resolved by someone else
    at connect time; a literal 127.x / ::1 cannot point off the machine."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "http" or parts.username or parts.password or parts.path not in ("", "/"):
        return False
    if parts.query or parts.fragment:
        return False
    host = parts.hostname or ""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return is_loopback(host)


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect is an instruction to send the prompt somewhere else. It is refused as the HTTP error
    it arrived as, so the caller falls back to the original prompt; nothing is followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"redirect refused: {msg}", headers, fp)


def local_only_opener() -> Callable[..., object]:
    """The translator's own HTTP client: no proxies whatever the environment says (an empty
    ProxyHandler replaces the environment-derived one, so HTTP_PROXY/http_proxy/HTTPS_PROXY are
    never consulted), no redirects, nothing else. Connects only to the numeric loopback literal the
    constructor accepted."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirects()).open


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
                 opener: Opener | None = None):
        if not isinstance(url, str) or not _is_local_ollama_url(url):
            raise PromptTranslationConfigError(f"{URL_ENV} must be a plain http URL on loopback (media never leaves the rig)")
        if not isinstance(model, str) or not _MODEL.fullmatch(model):
            raise PromptTranslationConfigError(f"{MODEL_ENV} is malformed")
        if _is_cloud_tagged(model):
            raise PromptTranslationConfigError(f"{MODEL_ENV} names a cloud model (media never leaves the rig)")
        if type(timeout_s) not in (int, float) or not 1 <= timeout_s <= MAX_TIMEOUT_S:
            raise PromptTranslationConfigError(f"{TIMEOUT_ENV} must be 1..{int(MAX_TIMEOUT_S)} seconds")
        self.url = url.rstrip("/")
        self.model = model
        self.timeout_s = float(timeout_s)
        self._opener = opener if opener is not None else local_only_opener()
        self.last_duration_s = 0.0

    def rewrite(self, prompt: str, *, max_chars: int) -> tuple[str, str]:
        """Return (prompt to render, outcome). outcome is 'translated', 'unchanged' or 'fallback:<code>';
        on any fallback the prompt is the original. Never raises, never logs the prompt."""
        try:
            self._require_local_model()
            text = self._ask(prompt)
        except _ModelNotLocal as exc:
            return prompt, f"fallback:{exc.code}"
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

    def _post(self, path: str, payload: dict) -> bytes:
        request = urllib.request.Request(self.url + path, data=json.dumps(payload).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json"})
        with self._opener(request, timeout=self.timeout_s) as response:
            return response.read(1 << 20)  # model metadata and a translation are small; a megabyte is already wrong

    def _require_local_model(self) -> None:
        """Ask the daemon about the model before any prompt is sent. Local model metadata has a
        `details` object; a model the daemon forwards upstream reports `remote_host`/`remote_model`.
        Anything else (unknown model -> HTTP 404, not JSON, no details) is not proof of local
        execution and refuses. Only the model name is sent here, never the prompt."""
        try:
            info = json.loads(self._post("/api/show", {"model": self.model}).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise _ModelNotLocal("model_unverified") from None
        if not isinstance(info, dict) or not isinstance(info.get("details"), dict):
            raise _ModelNotLocal("model_unverified")
        if any(key.startswith("remote") and value for key, value in info.items()):
            raise _ModelNotLocal("model_not_local")

    def _ask(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": prompt,
            "stream": False,
            "think": False,  # qwen3 and friends: no reasoning preamble; older servers ignore the key
            "options": {"temperature": 0, "num_predict": MAX_OUTPUT_TOKENS},
        }
        started = time.monotonic()
        raw = self._post("/api/generate", payload)
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
