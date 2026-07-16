"""Tier B policy for desktop actions (ISOLATION_DESIGN.md §4.2-4.4).

**Dormant.** No tool declares `desktop` yet; this is the rule layer landing
before the plumbing, so the hard part is settled and tested while it still
costs nothing to change.

Tier B is the honest half of the isolation story: a tool that drives your
desktop cannot be contained FROM your desktop -- a sandbox that stops it also
stops it working. So safety here is not containment, it is:

  * screenshot binding -- an action must reference the screen it was planned
    from, and the screen must still look like that when it runs
  * a target allowlist -- fail-closed; an empty list means no computer-use
  * a rate limit -- a model in a loop cannot machine-gun the desktop
  * the cloud-origin rule -- a screenshot is the worst egress there is

Everything here is pure: it decides, it does not act. Capture, hashing and
input injection are I3/I4 and need Windows. The rules are testable today, and
they are the part that must not be wrong.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch

# A screenshot is only planning material for a short while: desktops move.
DEFAULT_SCREEN_TTL_S = 20.0
# Perceptual-hash distance still considered "the same screen". A blinking
# caret must not invalidate a plan; a new dialog must. THIS NUMBER IS A GUESS
# until it is calibrated on the rig against real apps (ISOLATION_DESIGN §6.2).
DEFAULT_TOLERANCE = 6
DEFAULT_RATE_LIMIT = 12
DEFAULT_RATE_WINDOW_S = 60.0


class DesktopDenied(RuntimeError):
    """A desktop action was refused by policy. Never downgrade this to a warning."""


@dataclass(frozen=True)
class ScreenRef:
    """What a screenshot hands back: an id the model must quote to act on it."""

    screen_id: str
    phash: str
    issued_at: float


def _mk_id(phash: str, issued_at: float) -> str:
    return hashlib.sha256(f"{phash}:{issued_at:.6f}".encode()).hexdigest()[:16]


class ScreenRegistry:
    """Issues screen ids and refuses actions planned against a stale screen.

    This is the gate's immutable-argument invariant applied to pixels: the
    model may not act on a screen it merely remembers. Re-verification is
    against the LIVE screen every time, which is why an id stays usable for a
    whole plan instead of being single-use -- freshness is checked at the
    moment it matters, not rationed in advance.
    """

    def __init__(self, ttl_s: float = DEFAULT_SCREEN_TTL_S,
                 tolerance: int = DEFAULT_TOLERANCE) -> None:
        self.ttl_s = ttl_s
        self.tolerance = tolerance
        self._screens: dict[str, ScreenRef] = {}

    def issue(self, phash: str, now: float | None = None) -> ScreenRef:
        now = time.time() if now is None else now
        ref = ScreenRef(_mk_id(phash, now), phash, now)
        self._screens[ref.screen_id] = ref
        return ref

    def verify(self, screen_id: str, current_phash: str, distance: int,
               now: float | None = None) -> None:
        """Raise DesktopDenied unless the plan still matches the live screen."""
        now = time.time() if now is None else now
        ref = self._screens.get(screen_id)
        if ref is None:
            raise DesktopDenied(
                "handlingen refererer et ukendt screenshot — tag et nyt og planlæg forfra"
            )
        age = now - ref.issued_at
        if age > self.ttl_s:
            raise DesktopDenied(
                f"screenshottet er {age:.0f}s gammelt (grænse {self.ttl_s:.0f}s) — "
                "skærmen kan have flyttet sig; tag et nyt"
            )
        if distance > self.tolerance:
            raise DesktopDenied(
                f"skærmen har ændret sig siden planen blev lagt (afstand {distance} > "
                f"{self.tolerance}) — et vindue eller en dialog er kommet i vejen"
            )


@dataclass
class TargetAllowlist:
    """Which windows may be touched at all. Empty = computer-use is off.

    Fail-closed by construction: this is configured by Anders, never by a
    model, and the default is nothing.
    """

    rules: dict[str, list[str]] = field(default_factory=dict)

    def allows(self, process: str, title: str) -> bool:
        patterns = self.rules.get((process or "").lower())
        if not patterns:
            return False
        return any(fnmatch(title or "", p) for p in patterns)

    def require(self, process: str, title: str) -> None:
        if not self.allows(process, title):
            raise DesktopDenied(
                f"vinduet er ikke på allowlisten: {process or '?'} — "
                f"«{(title or '')[:40]}»"
            )


class RateLimiter:
    """A model in a loop must not be able to machine-gun the desktop."""

    def __init__(self, limit: int = DEFAULT_RATE_LIMIT,
                 window_s: float = DEFAULT_RATE_WINDOW_S) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: list[float] = []

    def require(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._hits = [t for t in self._hits if now - t < self.window_s]
        if len(self._hits) >= self.limit:
            raise DesktopDenied(
                f"for mange skrivebordshandlinger ({self.limit} pr. "
                f"{self.window_s:.0f}s) — stoppet"
            )
        self._hits.append(now)


def require_local_origin(origin: str, consent: bool) -> None:
    """The single most important rule in the whole design.

    A screenshot can contain anything on your screen: passwords, mail, someone
    else's data. Planning a desktop action with a cloud model means sending
    that picture out of the house. So computer-use is local-model-only unless
    Anders explicitly says otherwise for that session -- and 'explicitly' means
    a separate consent, not the RAG one, because this is a different promise.
    """
    if origin == "local":
        return
    if not consent:
        raise DesktopDenied(
            "skrivebordshandlinger planlægges kun med en LOKAL model — "
            "et screenshot kan indeholde hvad som helst på din skærm. "
            "Slå eksplicit cloud-samtykke til for denne session hvis du vil ændre det."
        )
