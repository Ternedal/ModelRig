"""Deprecated internal proxy for retained local-candidate v1 artifacts."""
from ._compatibility_v1 import local_candidate_materialization as _implementation

globals().update(
    {
        name: getattr(_implementation, name)
        for name in dir(_implementation)
        if not name.startswith("__")
    }
)
del _implementation
