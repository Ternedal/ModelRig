#!/usr/bin/env python3
"""Hvad en URL maa blive til (T-034, trin 3a).

Alle valgene her ser ud som detaljer og er det ikke. En hentefunktion skal ikke
traeffe dem senere; de ligger foer netvaerket og er derfor testbare uden det.

Run: PYTHONPATH=worker python3 tests/worker_web_research_intent.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-wri-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from app.web_research_intent import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    WebResearchIntentError,
    build_intent,
    canonical_url,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def denied(url: str, why: str, **kw) -> None:
    try:
        build_intent(url, purpose=kw.pop("purpose", "probe"), **kw)
        check(False, f"{url!r} afvises ({why})")
    except (WebResearchIntentError, ValueError):
        check(True, f"{url!r} afvises ({why})")


# --- kun https ------------------------------------------------------------
denied("http://example.com/a", "http kan aendres undervejs")
denied("ftp://example.com/a", "kun https")
denied("file:///etc/passwd", "ingen file-scheme")
denied("//example.com/a", "ingen scheme")
denied("", "tom url")

# --- ingen credentials, ingen alternativ port -----------------------------
denied("https://user:pw@example.com/a", "credentials i url")
denied("https://example.com:8443/a", "kun standardporten i v1")

# --- vaerten skal vaere et rigtigt offentligt domaene ----------------------
# Disse afvises af normalize_domain_rule. De navngives her, fordi en
# beskyttelse ingen test naevner er en man kan komme til at fjerne.
for host, why in (
    ("127.0.0.1", "IP-literal"),
    ("169.254.169.254", "cloud-metadata som IP"),
    ("localhost", "localhost"),
    ("rig.local", ".local"),
    ("db.internal", ".internal"),
    ("printer.home.arpa", ".home.arpa"),
):
    denied(f"https://{host}/a", why)

# --- purpose og lofter ----------------------------------------------------
denied("https://example.com/a", "purpose mangler", purpose="   ")
denied("https://example.com/a", "max_bytes over loftet",
       max_bytes=MAX_RESPONSE_BYTES + 1)
denied("https://example.com/a", "max_bytes nul", max_bytes=0)

# --- kontrol: en gyldig url SKAL slippe igennem ---------------------------
# Uden den kunne alt ovenfor bestaa fordi funktionen afviste alt.
intent = build_intent("https://example.com/side?q=1", purpose="Slaa noget op")
check(intent.plan.allowed_domains == ("example.com",),
      f"scopet er den PRAECISE vaert, ikke et wildcard "
      f"({intent.plan.allowed_domains})")
check(intent.plan.sensitivity == "public",
      "sensitivity er public -- intet af brugerens gaar udad")
check(intent.plan.max_bytes <= MAX_RESPONSE_BYTES,
      "byte-loftet er under skemaets 10 MB")
# D7 nr. 4: loftet er 2 MB og det AFVISER frem for at afkorte. En afkortet side
# ville naa modellen som om den var hel. Tallet staar her, saa en aendring er en
# beslutning frem for en tastefejl.
check(MAX_RESPONSE_BYTES == 2_000_000,
      f"loftet er 2 MB som besluttet i D7 ({MAX_RESPONSE_BYTES})")

# --- kanonisering ---------------------------------------------------------
check(canonical_url("https://Example.COM/a") == "https://example.com/a",
      "vaerten smaaskrives")
check(canonical_url("https://example.com/a#frag") == "https://example.com/a",
      "fragmentet fjernes -- det sendes aldrig til serveren, og at beholde det "
      "ville give to godkendelser for een handling")
check(canonical_url("https://example.com") == "https://example.com/",
      "tom sti bliver /")

# --- digesten binder den PRAECISE url -------------------------------------
a = build_intent("https://example.com/a", purpose="p")
b = build_intent("https://example.com/b", purpose="p")
check(a.plan.payload_sha256 != b.plan.payload_sha256,
      "to stier paa samme vaert giver forskellige digests -- 'ja til forsiden' "
      "er ikke 'ja til hele sitet'")
check(a.plan.payload_sha256 ==
      hashlib.sha256(b"https://example.com/a").hexdigest(),
      "digesten er af den kanoniske url, ikke af den raa")

# --- og scopet kan ikke udvides bagefter ----------------------------------
sub = build_intent("https://login.example.com/a", purpose="p")
check(a.scoped_destination != sub.scoped_destination,
      "en underdomaene-hentning har et ANDET scoped destination -- en "
      "tilladelse kan ikke afspilles mod en bredere allowlist")

print(f"\nweb research intent: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
