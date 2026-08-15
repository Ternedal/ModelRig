#!/usr/bin/env python3
"""Render the Stage A phone pairing link as a local QR code.

This helper is convenience-only: it never claims the pairing code and never
carries a device token. The QR contains exactly the same LAN URL + short-lived,
one-use pairing code that the operator could type by hand.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


def load_state(path: Path) -> tuple[str, str]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError("phone-test state is not a JSON object")
    url = str(value.get("lan_url") or "").strip().rstrip("/")
    code = str(value.get("pairing_code") or "").strip().upper()
    if not url.startswith(("http://", "https://")) or not code:
        raise RuntimeError("phone-test state has no usable LAN URL/pairing code")
    return url, code


def ensure_qrcode():
    try:
        import qrcode  # type: ignore
        return qrcode
    except ImportError:
        print("  QR-helper: installerer den lille lokale qrcode-afhængighed én gang...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "qrcode[pil]>=7,<9"],
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("qrcode kunne ikke installeres; brug den viste URL + parringskode manuelt")
        import qrcode  # type: ignore
        return qrcode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    url, code = load_state(args.state)
    link = f"kaliv://pair?url={quote(url, safe='')}&code={quote(code, safe='')}"
    output = args.output or args.state.with_name("PAIRING_QR.png")
    output.parent.mkdir(parents=True, exist_ok=True)

    qrcode = ensure_qrcode()
    image = qrcode.make(link)
    image.save(output)
    print(f"  QR klar: {output}")
    print("  QR indeholder kun LAN-adresse + kortlivet engangskode; aldrig device-token.")

    if args.open and os.name == "nt":
        os.startfile(output)  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"QR-HJÆLPER: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
