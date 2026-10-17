"""Conservative Danish voice intent parsing; no side effects and no timer grants."""
from __future__ import annotations
import re

_TIMER = re.compile(
    r"^(?:sæt|start|lav) (?:en )?timer (?:på|til) "
    r"(?P<count>\d{1,3}) (?P<unit>minutter?|sekunder?|timer?)\s*[.!?]?$",
    flags=re.IGNORECASE,
)


def parse_timer_request(text: str) -> int | None:
    match = _TIMER.fullmatch(text.strip())
    if match is None:
        return None
    count = int(match.group("count"))
    unit = match.group("unit").lower()
    seconds = count * (3600 if unit.startswith("time") else 60 if unit.startswith("minut") else 1)
    return seconds if 1 <= seconds <= 3600 else None


def unsupported_timer_reply(text: str) -> str | None:
    """Avoid implying a timer was scheduled; existing scheduler requires consent."""
    if parse_timer_request(text) is None:
        return None
    return "Jeg har forstået din timerkommando, men timeren er ikke startet. Jeg mangler en godkendt timerfunktion."
