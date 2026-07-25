from __future__ import annotations

from fastapi import FastAPI

from ..build_identity import code_fingerprint
from .api import mount_agent3 as mount_agent3_runtime
from .task_readiness import (
    build_task_readiness_router,
    evaluate_configured_task_readiness,
)


def mount_agent3(app: FastAPI) -> bool:
    """Mount the complete production Agent 3 surface exactly once.

    The runtime router remains owned by ``api.mount_agent3``. This wrapper adds
    the evidence-only task-readiness route used by the normal task UI. Both are
    guarded by ``KALIV_AGENT3_ENABLED`` through the runtime mount; neither can
    alter normal chat or activate production.
    """
    if not mount_agent3_runtime(app):
        return False
    if getattr(app.state, "agent3_task_readiness_mounted", False):
        return True

    worker_version = getattr(app, "version", None)

    def readiness_provider() -> dict:
        return evaluate_configured_task_readiness(
            current_version=worker_version,
            current_code=code_fingerprint(),
        )

    app.include_router(build_task_readiness_router(readiness_provider))
    app.state.agent3_task_readiness_mounted = True
    return True
