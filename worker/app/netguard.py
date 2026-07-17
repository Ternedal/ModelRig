"""One definition of "may this process bind here".

The worker has no authentication of its own. It trusts whoever reaches it,
which is fine while "whoever" is the backend on the same machine and a
catastrophe the moment it is the coffee shop's wifi: every document in the RAG
store, every tool, no password.

So the bind guard is the single most consequential line in the launchers -- and
until now each launcher carried its OWN copy of it. Two copies of a safety
check are not redundancy; they are a race to see which one gets the next fix.
The prefix that identifies encrypted tokens taught the same lesson this
morning, in the same repo.

The decision is pure (refusal_reason) so it can be driven at its edges, and the
process-killing wrapper is three lines on top. Nothing here reads the
environment except through an argument: a guard you cannot call from a test is
a guard nobody has tested.
"""
from __future__ import annotations

import ipaddress
import os

ALLOW_LAN_ENV = "KALIV_WORKER_ALLOW_LAN"


def is_loopback(host: str) -> bool:
    """True only for addresses that cannot leave this machine.

    Fail-closed on anything unparseable: a hostname we cannot resolve to a
    loopback literal is not loopback. "localhost" is the one name allowed
    through, because refusing it would make the guard unusable in practice and
    it cannot point anywhere else in a sane setup.
    """
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    # ::ffff:127.0.0.1 IS a loopback connection -- it is IPv4 arriving on a
    # dual-stack socket, which is what Windows does. ipaddress says False for
    # it because the IPv6 loopback is only ::1, so both copies of this check
    # would have refused the backend's own local connection with a 403 and left
    # Anders debugging the rig. Latent today (the worker binds 127.0.0.1), live
    # the moment anyone binds to localhost or :: on a dual-stack box.
    mapped = getattr(addr, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def refusal_reason(host: str, allow_lan: bool) -> str | None:
    """Why this process must not bind to `host`, or None if it may.

    Pure on purpose: the launchers' job is to exit, this function's job is to
    be right.
    """
    if is_loopback(host) or allow_lan:
        return None
    return (
        f"refusing to bind the worker to non-loopback host {host!r}: it has no "
        f"auth of its own and should only be reached by the backend on the same "
        f"machine. Set {ALLOW_LAN_ENV}=1 if you really mean to expose it."
    )


def allow_lan_requested(env: dict | None = None) -> bool:
    src = os.environ if env is None else env
    return str(src.get(ALLOW_LAN_ENV, "0")).strip().lower() in ("1", "true", "on")


def enforce_loopback(host: str, *, env: dict | None = None) -> None:
    """Exit the process unless `host` is safe to bind. Called by every launcher."""
    why = refusal_reason(host, allow_lan_requested(env))
    if why:
        import sys

        sys.stderr.write(why + "\n")
        raise SystemExit(1)
