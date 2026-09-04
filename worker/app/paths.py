"""One place that decides WHERE the worker's persistent data lives.

Why this module exists: every persistent file the worker owns -- the RAG index,
the tool audit log, the kill-switch state -- used to default to a RELATIVE path
("./modelrig-rag.db" etc.). Relative to the working directory, that is: start
the worker from a different folder and it reads a *different* (or empty) file.

That is exactly the bug that made a paired phone get 401 (the server's device
token file was relative too, fixed separately): the rig "forgot" its state
purely because it was launched from a different directory. For the RAG index the
same footgun silently empties the knowledge base; for the kill-switch it silently
re-arms tools; for the audit log it splits a security record across files.

The fix, in one place so it cannot drift: anchor every data file under a single
DATA ROOT that does NOT depend on the working directory.

Resolution order for the root:
  1. KALIV_DATA_DIR, if set (an explicit absolute location wins).
  2. %LOCALAPPDATA%\\Kaliv on Windows / ~/.local/share/kaliv elsewhere -- a
     stable per-user location, created if missing.

Each individual file keeps its own env override (MODELRIG_DB, KALIV_AUDIT_DB,
KALIV_TOOLS_STATE) for people who set absolute paths already; those are honoured
untouched. Only the RELATIVE defaults get anchored -- so this is backwards
compatible: anyone already passing an absolute path sees no change.

Control Center read projections are different: observing a stopped/empty rig must
not create the data root merely by asking where a database would live. For that
case ``peek_data_root`` / ``peek_resolve`` compute the exact same path WITHOUT
mkdir or migration side effects. Writer code should keep using ``data_root`` /
``resolve``.
"""
from __future__ import annotations

import os


def peek_data_root() -> str:
    """Return the stable data-root path without creating it."""
    explicit = os.getenv("KALIV_DATA_DIR")
    if explicit:
        return explicit
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "Kaliv")
    base = os.getenv("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "kaliv")


def data_root() -> str:
    """The stable directory all relative data files are anchored under."""
    root = peek_data_root()
    os.makedirs(root, exist_ok=True)
    return root


def peek_resolve(
    path: str,
    *,
    env: str | None = None,
    default_name: str | None = None,
) -> str:
    """Resolve the same persistent path as :func:`resolve`, without mutation.

    Explicit env overrides and absolute paths preserve the existing semantics.
    Only a relative default needs the computed (but uncreated) data root.
    """
    if env:
        value = os.getenv(env)
        if value:
            return value
    if os.path.isabs(path):
        return path
    name = default_name or os.path.basename(path)
    return os.path.join(peek_data_root(), name)


def resolve(path: str, *, env: str | None = None, default_name: str | None = None) -> str:
    """Resolve a data file path so it never depends on the working directory.

    - If `env` is set and holds a value, use it verbatim (absolute or not -- the
      caller asked for it explicitly).
    - Else if `path` is already absolute, use it.
    - Else anchor the file's BASENAME under data_root(). A relative default like
      "./modelrig-rag.db" becomes "<data_root>/modelrig-rag.db".

    default_name lets a caller force the basename under the root regardless of
    the relative default's spelling.
    """
    if env:
        value = os.getenv(env)
        if value:
            return value
    if os.path.isabs(path):
        return path
    name = default_name or os.path.basename(path)
    return os.path.join(data_root(), name)
