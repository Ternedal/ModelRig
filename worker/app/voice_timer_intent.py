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


# Malformed timer creation attempts must not fall through to a generative model.
_TIMER_ATTEMPT = re.compile(
    r"^(?:sæt|start|lav) (?:en )?timer\b",
    flags=re.IGNORECASE,
)


def unsupported_timer_reply(text: str) -> str | None:
    """Never imply creation of a timer without an authorized timer executor."""
    stripped = text.strip()
    if parse_timer_request(stripped) is not None:
        return "Jeg har forstået din timerkommando, men timeren er ikke startet. Jeg mangler en godkendt timerfunktion."
    if _TIMER_ATTEMPT.match(stripped):
        return "Timeren er ikke startet. Jeg kan ikke oprette en timer med den kommando."
    return None
