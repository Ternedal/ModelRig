"""Physical-evidence capture and leased command materialization."""
from __future__ import annotations

from ._tier_a_lease import (
    TierAExecutionError,
    TierAExecutionLease,
    _task_sha,
)
from .catalog import (
    CatalogMaterializer,
    ExecutableVerifier,
    IsolationAttestation,
    ModelRigCommandCatalog,
    Toolchain,
)
from .commands import CommandRegistry, CommandTemplate
from .contract import DevelopmentTask
from .physical_isolation import WindowsPhysicalIsolationVerifier


class _LeaseCapturingVerifier:
    def __init__(self, verifier: WindowsPhysicalIsolationVerifier) -> None:
        if not isinstance(verifier, WindowsPhysicalIsolationVerifier):
            raise TierAExecutionError(
                "leased materialization requires WindowsPhysicalIsolationVerifier"
            )
        self.verifier = verifier
        self._lease: TierAExecutionLease | None = None

    def verify(self, attestation: IsolationAttestation) -> None:
        self._lease = None
        self.verifier.verify(attestation)
        candidates = self.verifier._load_candidates(
            set(attestation.evidence_sha256)
        )
        if len(candidates) != 1:
            raise TierAExecutionError(
                "physical evidence changed while issuing the execution lease"
            )
        signed = candidates[0]
        if signed.sha256 not in attestation.evidence_sha256:
            raise TierAExecutionError(
                "execution lease report is not named by the attestation"
            )
        self._lease = TierAExecutionLease.from_signed_report(
            attestation, signed
        )

    @property
    def lease(self) -> TierAExecutionLease:
        if self._lease is None:
            raise TierAExecutionError("no verified execution lease was issued")
        return self._lease


class LeasedCommandRegistry:
    """A command registry that retains the exact signed execution authority."""

    def __init__(
        self,
        registry: CommandRegistry,
        lease: TierAExecutionLease,
        *,
        task: DevelopmentTask,
        catalog: ModelRigCommandCatalog,
        toolchain: Toolchain,
        attestation: IsolationAttestation,
    ) -> None:
        if not isinstance(registry, CommandRegistry):
            raise TierAExecutionError(
                "leased registry requires a command registry"
            )
        lease.verify_attestation(attestation)
        if (
            lease.task_sha256 != _task_sha(task)
            or lease.catalog_sha256 != catalog.sha256
            or lease.toolchain_sha256 != toolchain.sha256
        ):
            raise TierAExecutionError(
                "leased registry authority does not match task, catalog and toolchain"
            )
        self._registry = registry
        self.lease = lease
        self.catalog = catalog
        self.toolchain = toolchain
        self.attestation = attestation
        self._task_sha256 = _task_sha(task)

    def resolve(
        self, task: DevelopmentTask, command_id: str
    ) -> CommandTemplate:
        if _task_sha(task) != self._task_sha256:
            raise TierAExecutionError(
                "leased command registry cannot be rebound to another task"
            )
        self.lease.verify_attestation(self.attestation)
        return self._registry.resolve(task, command_id)


class LeasedCatalogMaterializer:
    """Materialize fixed commands and retain signed physical evidence."""

    def __init__(
        self,
        catalog: ModelRigCommandCatalog,
        physical_verifier: WindowsPhysicalIsolationVerifier,
        *,
        executable_verifier: ExecutableVerifier | None = None,
    ) -> None:
        self.catalog = catalog
        self._capturing = _LeaseCapturingVerifier(physical_verifier)
        self._materializer = CatalogMaterializer(
            catalog,
            isolation_verifier=self._capturing,
            executable_verifier=executable_verifier,
        )

    def materialize(
        self,
        task: DevelopmentTask,
        toolchain: Toolchain,
        attestation: IsolationAttestation,
    ) -> LeasedCommandRegistry:
        registry = self._materializer.materialize(
            task, toolchain, attestation
        )
        return LeasedCommandRegistry(
            registry,
            self._capturing.lease,
            task=task,
            catalog=self.catalog,
            toolchain=toolchain,
            attestation=attestation,
        )
