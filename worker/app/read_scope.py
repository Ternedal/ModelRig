"""Path scoping for file-read tools (ISOLATION_DESIGN.md I1).

**Dormant.** No file-read tool exists yet; this is the containment DECISION
landing before the tool, because a path check is exactly the kind of thing that
looks right and is wrong -- symlinks, `..`, drive-relative Windows paths, UNC
shares, NUL bytes. Getting it wrong is an arbitrary-file-read.

The honest boundary (ISOLATION_DESIGN §4.1): the REAL enforcement of a read
root is the OS's -- a restricted token or a low-integrity child that simply
cannot open files outside the root (that is I0b, and it needs Windows). THIS is
the belt to that suspenders: a pure, testable pre-check that refuses an
out-of-root path before anything is opened, so a bug in the plumbing is caught
here first and the OS never even gets asked. Two independent layers, neither
trusted alone.

Pure: it resolves and compares strings. It does not read, and deliberately does
not follow symlinks on disk (that is the caller's job under the real sandbox) --
it reasons about the path it was given, normalised.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass


class PathDenied(RuntimeError):
    """A requested path is outside the allowed root. Never downgrade to a warning."""


# Shapes that POSIX treats as harmless relative strings but Windows treats as
# absolute (drive-relative "C:foo", drive-absolute "C:\\", UNC "\\\\server").
# On a Linux dev box os.path.isabs() says False for these and they would be
# joined INTO the root and slip through -- yet production is Windows, where they
# escape. Reject them explicitly, on every OS, so the check does not depend on
# where the tests happen to run.
_WINDOWS_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:|\\\\|//)")


def _normalise(p: str) -> str:
    # Collapse ../, ./, doubled separators and case (Windows is case-insensitive
    # and mixes / and \). normpath does the separator + dot-segment work;
    # normcase handles the case/altsep folding. No disk access, so a symlink is
    # NOT resolved here -- that is the OS layer's job.
    return os.path.normcase(os.path.normpath(p))


@dataclass(frozen=True)
class ReadScope:
    """A single directory a read tool may see, and nothing above it."""

    root: str

    def resolve(self, requested: str) -> str:
        """Return the absolute in-root path, or raise PathDenied.

        Every failure mode is a refusal, never a silent clamp: silently
        rewriting ../../etc/passwd to something inside the root would be its own
        surprise. The caller gets a clear no.
        """
        if not requested or not requested.strip():
            raise PathDenied("tom sti")
        if "\x00" in requested:
            raise PathDenied("sti indeholder et NUL-byte")
        if _WINDOWS_ABSOLUTE.match(requested):
            # Absolute on Windows regardless of this host's os.sep. Only allow
            # it if it genuinely normalises under the root (it almost never
            # will); otherwise it is an escape wearing a relative-looking coat.
            probe = os.path.normcase(os.path.normpath(requested))
            root_probe = os.path.normcase(os.path.normpath(os.path.abspath(self.root)))
            if probe != root_probe and not probe.startswith(root_probe + os.sep):
                raise PathDenied(
                    f"sti er absolut (Windows drev/UNC) og uden for roden: {requested}"
                )

        root_abs = os.path.abspath(self.root)

        # An absolute request must sit under the root; a relative one is joined
        # TO the root (not to the working directory -- that would defeat the
        # point). A Windows drive-relative path like "C:foo" or a UNC path
        # "\\\\server\\share" is absolute-ish and must be rejected unless it
        # actually resolves under the root.
        candidate = requested if os.path.isabs(requested) else os.path.join(root_abs, requested)
        candidate_abs = os.path.abspath(candidate)

        root_n = _normalise(root_abs)
        cand_n = _normalise(candidate_abs)

        # The root itself is allowed; anything under it is allowed. The
        # separator on the prefix check stops "/data/rig-secrets" from being
        # accepted for root "/data/rig".
        if cand_n != root_n and not cand_n.startswith(root_n + os.sep):
            raise PathDenied(
                f"sti er uden for det tilladte rod-katalog: {requested}"
            )
        return candidate_abs

    def contains(self, requested: str) -> bool:
        try:
            self.resolve(requested)
            return True
        except PathDenied:
            return False
