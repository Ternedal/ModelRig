"""Physical-evidence capture and leased command materialization."""
from __future__ import annotations

from ._tier_a_environment import TIER_A_APPLICATION_ENVIRONMENT
from ._tier_a_lease import (
    TierAExecutionError,
    TierAExecutionLease,
    _task_sha,
)
from .catalog import (
    IsolationAttestation,
    IsolationBoundary,
    ModelRigCommandCatalog,
    NetworkMode,
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
    """Create a signed, non-executing Tier-A command identity registry."""

    def __init__(
        self,
        catalog: ModelRigCommandCatalog,
        physical_verifier: WindowsPhysicalIsolationVerifier,
        *,
        executable_verifier: object | None = None,
    ) -> None:
        self._capturing = _LeaseCapturingVerifier(physical_verifier)
        if not isinstance(catalog, ModelRigCommandCatalog):
            raise TierAExecutionError(
                "leased materialization requires a ModelRig command catalog"
            )
        if executable_verifier is not None:
            raise TierAExecutionError(
                "executable verification is deferred until process launch"
            )
        self.catalog = catalog.snapshot()

    def materialize(
        self,
        task: DevelopmentTask,
        toolchain: Toolchain,
        attestation: IsolationAttestation,
    ) -> LeasedCommandRegistry:
        if not isinstance(task, DevelopmentTask):
            raise TierAExecutionError(
                "leased materialization requires a development task"
            )
        if not isinstance(toolchain, Toolchain):
            raise TierAExecutionError(
                "leased materialization requires a toolchain"
            )
        if not isinstance(attestation, IsolationAttestation):
            raise TierAExecutionError(
                "leased materialization requires an isolation attestation"
            )
        try:
            task_snapshot = DevelopmentTask.from_mapping(task.to_dict())
            toolchain_snapshot = toolchain.snapshot()
            proof = IsolationAttestation.from_mapping(attestation.to_dict())
        except (AttributeError, TypeError, ValueError) as exc:
            raise TierAExecutionError(
                "leased materialization authority is invalid"
            ) from exc

        expected = {
            "task_id": task_snapshot.task_id,
            "task_sha256": _task_sha(task_snapshot),
            "repository": task_snapshot.repository,
            "base_sha": task_snapshot.base_sha,
            "catalog_sha256": self.catalog.sha256,
            "toolchain_sha256": toolchain_snapshot.sha256,
            "boundary": IsolationBoundary.OS_ISOLATED,
            "network_mode": NetworkMode.DENY,
        }
        actual = {
            "task_id": proof.task_id,
            "task_sha256": proof.task_sha256,
            "repository": proof.repository,
            "base_sha": proof.base_sha,
            "catalog_sha256": proof.catalog_sha256,
            "toolchain_sha256": proof.toolchain_sha256,
            "boundary": proof.boundary,
            "network_mode": proof.network_mode,
        }
        if actual != expected:
            raise TierAExecutionError(
                "isolation attestation is not bound to this exact Tier-A authority"
            )

        self._capturing.verify(proof)
        templates: list[CommandTemplate] = []
        for command_id in task_snapshot.allowed_command_ids:
            specification = self.catalog.resolve(command_id)
            if specification.required_boundary is not IsolationBoundary.OS_ISOLATED:
                raise TierAExecutionError(
                    "Tier-A catalog boundary is not OS isolated"
                )
            if specification.network_mode is not NetworkMode.DENY:
                raise TierAExecutionError(
                    "Tier-A catalog network mode is not deny"
                )
            binding = toolchain_snapshot.resolve(specification.tool_id)
            templates.append(
                CommandTemplate(
                    command_id=specification.command_id,
                    argv=(binding.executable, *specification.args),
                    cwd=specification.cwd,
                    max_timeout_seconds=specification.max_timeout_seconds,
                    env=TIER_A_APPLICATION_ENVIRONMENT,
                )
            )

        return LeasedCommandRegistry(
            CommandRegistry(templates),
            self._capturing.lease,
            task=task_snapshot,
            catalog=self.catalog,
            toolchain=toolchain_snapshot,
            attestation=proof,
        )
