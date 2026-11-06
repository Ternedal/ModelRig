"""Android's media job model must match what the worker actually writes.

The job store and the media executor own the job states and error strings; the
Android app (net/MediaJobContract.kt, ui/MediaJobPresentation.kt) mirrors them
for the proposed `kaliv-media-job/v1` read model. A state Android does not know
is a protocol error on the phone, and an error it does not map is shown as a
generic failure, so any drift here is a user-visible regression: the queued-job
expiry (state 'expired', Anders 6 Nov 2026) was one.

Run: PYTHONPATH=worker python3 tests/workflow_media_job_contract.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app import image_job_store, media_executor  # noqa: E402

KOTLIN = ROOT / "android/app/src/main/java/dk/ternedal/modelrig"
CONTRACT = (KOTLIN / "net/MediaJobContract.kt").read_text(encoding="utf-8")
PRESENTATION = (KOTLIN / "ui/MediaJobPresentation.kt").read_text(encoding="utf-8")
STORE_SOURCE = Path(image_job_store.__file__).read_text(encoding="utf-8")

EXECUTOR_SOURCE = Path(media_executor.__file__).read_text(encoding="utf-8")


def kotlin_states() -> dict[str, bool]:
    body = re.search(r"enum class MediaJobState\b.*?\{(.*?)\n\}", CONTRACT, re.S).group(1)
    return {wire: terminal == "true"
            for wire, terminal in re.findall(r'[A-Z]+\("([a-z_]+)", (true|false)\)', body)}


def kotlin_errors() -> set[str]:
    body = re.search(r"val ERRORS: Map<String, MediaJobOutcome> = mapOf\((.*?)\n    \)", PRESENTATION, re.S).group(1)
    return set(re.findall(r'^\s*"([^"]+)" to MediaJobOutcome\(', body, re.M))


def store_states() -> set[str]:
    states = set(re.findall(r"state\s*=\s*'([a-z_]+)'", STORE_SOURCE))
    for group in re.findall(r"state IN \(([^)]*)\)", STORE_SOURCE):
        states |= set(re.findall(r"'([a-z_]+)'", group))
    return states | set(image_job_store._FINISHED)


def executor_errors() -> set[str]:
    """Every module constant the executor hands to store.fail/defer or _record_failure."""
    names: set[str] = set()
    for call in re.findall(r"(?:self\.store\.(?:fail|defer)|self\._record_failure)\(([^)]*)\)", EXECUTOR_SOURCE):
        names |= set(re.findall(r"\b([A-Z][A-Z_]{3,})\b", call))
    constants = dict(re.findall(r'^([A-Z_]+) = "([a-z_]+)"', EXECUTOR_SOURCE, re.M))
    return {constants[n] for n in names if n in constants}


def store_error_literals() -> set[str]:
    """The literal errors the store writes itself (SQL), besides EXPIRED_ERROR."""
    return set(re.findall(r"error\s*=\s*'([^']+)'", STORE_SOURCE))


class MediaJobContractDriftTests(unittest.TestCase):
    def test_states_match_the_store(self):
        self.assertEqual(set(kotlin_states()), store_states())

    def test_terminal_states_are_the_store_finished_states(self):
        terminal = {s for s, t in kotlin_states().items() if t}
        self.assertEqual(terminal, set(image_job_store._FINISHED))

    def test_every_written_error_has_a_presentation(self):
        written = executor_errors() | {image_job_store.EXPIRED_ERROR} | store_error_literals()
        self.assertTrue({"interrupted by restart", "interrupted during publication"} <= written)
        missing = written - kotlin_errors()
        self.assertEqual(missing, set(), f"Android has no text for: {sorted(missing)}")

    def test_error_discovery_is_not_stale(self):
        # If the executor's call shapes change, discovery must still find the known codes.
        self.assertTrue({"generation_failed", "publication_failed", "gpu_busy", "gpu_unavailable",
                         "gpu_memory_retained", "generation_request_rejected"} <= executor_errors(),
                        sorted(executor_errors()))

    def test_expired_error_is_shared(self):
        self.assertEqual(image_job_store.EXPIRED_ERROR,
                         re.search(r'EXPIRED_UNCLAIMED = "([a-z_]+)"', CONTRACT).group(1))

    def test_queued_expiry_matches_the_24_hours_shown(self):
        self.assertEqual(image_job_store.QUEUED_MAX_AGE_S, 24 * 3600)
        self.assertIn("24 timer", PRESENTATION)


if __name__ == "__main__":
    unittest.main()
