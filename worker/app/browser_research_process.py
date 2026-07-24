"""Compatibility entrypoint for the isolated Browser Use process.

The implementation lives in :mod:`app.browser_research_process_v2`. Importers
receive that module directly so private contract helpers and monkeypatch-based
tests keep normal module-global behaviour. Executing this file still runs the
single-request child-process protocol.
"""
from __future__ import annotations

import sys as _sys

from . import browser_research_process_v2 as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())

_sys.modules[__name__] = _impl
