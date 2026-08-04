"""Deprecated internal proxy for retained publisher-authorization v1 artifacts.

The implementation lives in ``kaliv_dev_control._compatibility_v1``. This proxy
preserves private parser helpers for internal v2 adapters; the public
``publisher_authorization`` module imports only an explicit safe subset.
"""
from ._compatibility_v1 import publisher_authorization as _implementation

globals().update(
    {
        name: getattr(_implementation, name)
        for name in dir(_implementation)
        if not name.startswith("__")
    }
)
del _implementation
