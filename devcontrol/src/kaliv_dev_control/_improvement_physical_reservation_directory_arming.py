"""Race-free Linux arming guard for RSI reservation directory history.

The lower directory-provenance layer retains directory identities and monitors
path history. On Linux, production strengthens setup by arming every protected
ancestry edge *before* directory descriptors become trusted. A rename/delete/
replace racing with identity capture therefore leaves a queued inotify event and
fails the binding even on filesystems whose ctime resolution is too coarse to
serve as unique race evidence.

kqueue needs the target descriptor before its vnode filter can be registered, so
it cannot provide the same watch-before-trust property. Production therefore
fails closed on non-Linux POSIX rather than claiming an exact setup guarantee
from a timestamp sandwich alone.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import _improvement_physical_reservation_directory_provenance as _history


class _PathNode:
    """Minimal path carrier accepted by the private Linux watch installer."""

    __slots__ = ("path",)

    def __init__(self, path: Path) -> None:
        self.path = path


def _close_nodes(nodes: tuple[Any, ...]) -> None:
    for node in nodes:
        descriptor = getattr(node, "descriptor", -1)
        if isinstance(descriptor, int) and descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
            node.descriptor = -1


def _capture_binding_watch_first(
    ledger_path: Path,
    transaction_token: object,
) -> Any:
    if not _history._is_linux():
        raise _history.DirectoryBoundProvenanceError(
            "race-free reservation directory-history arming is unsupported on this POSIX platform"
        )

    ledger = Path(ledger_path).resolve(strict=True)
    paths = _history._directory_chain(ledger)
    history_handle: int | None = None
    nodes: tuple[Any, ...] = ()
    try:
        # Arm every protected ancestry entry before any captured directory
        # identity is accepted as provenance. Relevant races are queued here.
        history_handle, history_expected = _history._start_linux_history(
            tuple(_PathNode(path) for path in paths)
        )
        nodes = _history._capture_nodes(ledger)
        binding = _history._Binding(
            ledger_path=ledger,
            nodes=nodes,
            history_kind="inotify",
            history_handle=history_handle,
            history_expected=history_expected,
            transaction_token=transaction_token,
        )
        if not _history._binding_matches(binding):
            raise _history.DirectoryBoundProvenanceError(
                "reservation directory-chain changed while identities were captured"
            )
        return binding
    except BaseException:
        if history_handle is not None:
            try:
                os.close(history_handle)
            except OSError:
                pass
        _close_nodes(nodes)
        raise


def install_directory_history_arming_guard() -> None:
    """Install Linux watch-before-trust setup on the production POSIX facade."""

    if os.name != "posix":
        return
    if getattr(_history, "_directory_history_arming_guard_installed", False):
        return
    _history._capture_binding = _capture_binding_watch_first
    _history._directory_history_arming_guard_installed = True


__all__: list[str] = []
