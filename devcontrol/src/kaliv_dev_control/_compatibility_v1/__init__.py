"""Internal-only compatibility package for retained v1 evidence.

Normal consumers must use the public Ed25519/v2 modules. This package exists
only to parse and verify historical v1 artifacts during migration. It is not a
supported issuance API and must never receive production secrets or credentials.
"""

__all__: tuple[str, ...] = ()
