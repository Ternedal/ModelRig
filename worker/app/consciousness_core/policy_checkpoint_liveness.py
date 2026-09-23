"""C29-C policy-checkpoint to liveness coupling.

This wrapper preserves C27-F as the sole SelfState checkpoint authority and
records one C29-B liveness witness only after an actual COMMITTED checkpoint.
"""
from __future__ import annotations

from .checkpoint_liveness import (
    CommittedCheckpointLivenessReceipt,
    CommittedCheckpointLivenessRecorder,
)
from .checkpoint_pressure import (
    DEFAULT_CHECKPOINT_PRESSURE_POLICY,
    CheckpointPressurePolicy,
)
from .liveness import RuntimeLivenessStore
from .policy_checkpoint import (
    PolicyDrivenCheckpointResult,
    PolicyDrivenSelfStateCheckpointAdapter,
)
from .self_state import SelfStateStore
from .session_lifecycle import ProductionCognitiveSession


class PolicyCheckpointLivenessError(RuntimeError):
    """Post-commit liveness failure with checkpoint replay explicitly denied."""

    def __init__(
        self,
        message: str,
        *,
        checkpoint_result: PolicyDrivenCheckpointResult,
    ) -> None:
        super().__init__(message)
        self.checkpoint_result = checkpoint_result
        self.checkpoint_committed = True
        self.checkpoint_retry_authority = False


class LivenessCoupledPolicyCheckpointAdapter(
    PolicyDrivenSelfStateCheckpointAdapter
):
    """Run C29-B only after the inherited C27-F adapter actually commits."""

    def __init__(
        self,
        *,
        session: ProductionCognitiveSession,
        store: SelfStateStore,
        liveness_store: RuntimeLivenessStore,
        policy: CheckpointPressurePolicy = DEFAULT_CHECKPOINT_PRESSURE_POLICY,
    ) -> None:
        super().__init__(
            session=session,
            store=store,
            policy=policy,
        )
        if not isinstance(liveness_store, RuntimeLivenessStore):
            raise TypeError(
                "liveness_store must be RuntimeLivenessStore"
            )
        self._liveness_recorder = CommittedCheckpointLivenessRecorder(
            session=session,
            store=liveness_store,
        )
        self._last_liveness_receipt: (
            CommittedCheckpointLivenessReceipt | None
        ) = None

    @property
    def last_liveness_receipt(
        self,
    ) -> CommittedCheckpointLivenessReceipt | None:
        """Last successfully recorded witness receipt, never a retry token."""
        return self._last_liveness_receipt

    def maybe_checkpoint_once(self) -> PolicyDrivenCheckpointResult:
        result = super().maybe_checkpoint_once()
        if result.outcome != "COMMITTED":
            return result

        checkpoint = result.checkpoint
        if checkpoint is None:
            raise RuntimeError(
                "COMMITTED policy checkpoint result is missing checkpoint"
            )

        try:
            receipt = self._liveness_recorder.record_once(checkpoint)
        except Exception as exc:
            raise PolicyCheckpointLivenessError(
                "SelfState committed but liveness recording failed; "
                "checkpoint retry authority is false",
                checkpoint_result=result,
            ) from exc

        self._last_liveness_receipt = receipt
        return result
