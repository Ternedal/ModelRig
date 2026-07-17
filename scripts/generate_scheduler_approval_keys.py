#!/usr/bin/env python3
"""Generate the Ed25519 keypair used for human scheduler approvals.

Prints two modelrig.env-compatible lines. The private seed belongs to the Go
backend only. The worker receives only the public key and can verify tokens but
cannot create them.
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> int:
    private = Ed25519PrivateKey.generate()
    seed = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    print("KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY=" + base64.b64encode(seed).decode("ascii"))
    print("KALIV_SCHEDULER_APPROVAL_PUBLIC_KEY=" + base64.b64encode(public).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
