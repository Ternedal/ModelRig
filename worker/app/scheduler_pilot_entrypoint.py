"""Pilot-only ASGI entrypoint for deterministic T-019 observations.

Normal production and Stage A launches continue to use ``app.entrypoint:app``.
This module is selected only by the explicit ``-SchedulerPilot`` launcher mode.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from . import schedule_runner_impl
from .scheduler_pilot_control import install_pilot_hold


def _install_pilot_log() -> None:
    raw = os.environ.get("KALIV_SCHEDULER_PILOT_LOG", "").strip()
    if not raw:
        return
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The wizard stores a file-size offset before restart and slices the appended
    # text afterwards. ASCII + backslashreplace makes one character exactly one
    # byte even when Danish log messages contain non-ASCII letters.
    handler = logging.FileHandler(
        path,
        encoding="ascii",
        errors="backslashreplace",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler._kaliv_scheduler_pilot_file = True  # type: ignore[attr-defined]
    for name in ("app.schedule_service", "app.schedule_runner"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not any(
            getattr(existing, "_kaliv_scheduler_pilot_file", False)
            for existing in logger.handlers
        ):
            logger.addHandler(handler)


_install_pilot_log()
install_pilot_hold(schedule_runner_impl.SchedulerRunner)

from .entrypoint import app  # noqa: E402,F401
