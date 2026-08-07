"""Reviewed builder for the single-file ModelRig version-check runtime closure.

The builder emits an unsigned manifest only. It grants no signing, staging or
process authority and is intentionally limited to one exact catalog command.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from ._runtime_closure_common import (
    _MAX_FILE_BYTES,
    RuntimeClosureError,
    _closure_canonical_directory,
    _closure_canonical_source,
    _closure_file_hash_and_size,
    _closure_inside,
    _closure_is_linkish,
    _closure_relative_path,
    _closure_task_sha,
    trusted_runtime_root_sha256,
)
from ._tier_a_execution_core import (
    LeasedCommandRegistry,
    workspace_root_authority_sha256,
)
from .catalog import ModelRigCommandCatalog, ProjectCommandSpec
from .contract import DevelopmentTask
from .runtime_closure_model import RuntimeClosureFile, RuntimeClosureManifest

VERSION_CHECK_COMMAND_ID = "modelrig.version.check"
VERSION_CHECK_TOOL_ID = "modelrig-version-check"


def modelrig_version_check_closure_catalog() -> ModelRigCommandCatalog:
    """Return the isolated one-command catalog for the standalone checker.

    This does not modify the default ModelRig catalog. Selecting this profile
    therefore requires a new exact catalog hash, toolchain and physical report.
    """

    return ModelRigCommandCatalog(
        (
            ProjectCommandSpec(
                VERSION_CHECK_COMMAND_ID,
                VERSION_CHECK_TOOL_ID,
                (),
                ".",
                120,
                {"CI": "1", "MODELRIG_DEVCONTROL": "1"},
            ),
        )
    )


class ModelRigVersionCheckClosureBuilder:
    """Build the one reviewed, unsigned, single-file version-check closure."""

    def __init__(self, trusted_runtime_root: Path, workspace_root: Path) -> None:
        self.trusted_runtime_root = _closure_canonical_directory(
            Path(trusted_runtime_root), name="trusted runtime root"
        )
        self.workspace_root = _closure_canonical_directory(
            Path(workspace_root), name="workspace root"
        )
        roots_overlap = _closure_inside(
            self.trusted_runtime_root, self.workspace_root
        ) or _closure_inside(self.workspace_root, self.trusted_runtime_root)
        if roots_overlap:
            raise RuntimeClosureError(
                "trusted runtime root and workspace root must be separate trees"
            )

    def _single_file_entrypoint(self, executable: str) -> tuple[str, str, int]:
        source = _closure_canonical_source(
            Path(executable), self.trusted_runtime_root
        )
        relative = _closure_relative_path(
            PurePosixPath(
                *source.relative_to(self.trusted_runtime_root).parts
            ).as_posix(),
            name="version-check entrypoint",
        )

        observed_files: list[Path] = []
        observed_directories: set[str] = set()
        for current, directory_names, file_names in os.walk(
            self.trusted_runtime_root, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            directory_names.sort()
            file_names.sort()
            for name in directory_names:
                candidate = current_path / name
                if _closure_is_linkish(candidate) or not candidate.is_dir():
                    raise RuntimeClosureError(
                        "version-check runtime root contains an unsafe directory"
                    )
                observed_directories.add(
                    PurePosixPath(
                        *candidate.relative_to(self.trusted_runtime_root).parts
                    ).as_posix()
                )
            for name in file_names:
                candidate = current_path / name
                if _closure_is_linkish(candidate) or not candidate.is_file():
                    raise RuntimeClosureError(
                        "version-check runtime root contains an unsafe file"
                    )
                observed_files.append(candidate.resolve())

        expected_directories = {
            parent.as_posix()
            for parent in PurePosixPath(relative).parents
            if parent.as_posix() != "."
        }
        if observed_directories != expected_directories or observed_files != [source]:
            raise RuntimeClosureError(
                "version-check closure must contain exactly its one entrypoint"
            )
        if source.stat().st_nlink != 1:
            raise RuntimeClosureError(
                "version-check entrypoint must have exactly one hardlink"
            )
        sha256, size_bytes = _closure_file_hash_and_size(
            source, maximum=_MAX_FILE_BYTES
        )
        return relative, sha256, size_bytes

    def build(
        self,
        registry: LeasedCommandRegistry,
        task: DevelopmentTask,
        command_id: str = VERSION_CHECK_COMMAND_ID,
    ) -> RuntimeClosureManifest:
        if not isinstance(registry, LeasedCommandRegistry):
            raise RuntimeClosureError(
                "version-check closure builder requires a leased command registry"
            )
        if not isinstance(task, DevelopmentTask):
            raise RuntimeClosureError(
                "version-check closure builder requires a development task"
            )
        if command_id != VERSION_CHECK_COMMAND_ID:
            raise RuntimeClosureError(
                "version-check closure builder refuses every other command"
            )

        template = registry.resolve(task, command_id)
        spec = registry.catalog.resolve(command_id)
        if (
            spec.tool_id != VERSION_CHECK_TOOL_ID
            or spec.args != ()
            or spec.cwd != "."
            or template.argv != (registry.toolchain.resolve(spec.tool_id).executable,)
            or template.cwd != spec.cwd
            or template.max_timeout_seconds != spec.max_timeout_seconds
            or dict(template.env) != dict(spec.env)
        ):
            raise RuntimeClosureError(
                "version-check command authority is not the reviewed "
                "single-file profile"
            )

        binding = registry.toolchain.resolve(VERSION_CHECK_TOOL_ID)
        relative, sha256, size_bytes = self._single_file_entrypoint(
            binding.executable
        )
        if sha256 != binding.executable_sha256:
            raise RuntimeClosureError(
                "version-check entrypoint does not match the operator tool binding"
            )

        lease = registry.lease
        observed_workspace = workspace_root_authority_sha256(self.workspace_root)
        if observed_workspace != lease.workspace_root_sha256:
            raise RuntimeClosureError(
                "version-check workspace does not match the execution lease"
            )
        if (
            lease.task_sha256 != _closure_task_sha(task)
            or lease.catalog_sha256 != registry.catalog.sha256
            or lease.toolchain_sha256 != registry.toolchain.sha256
        ):
            raise RuntimeClosureError(
                "version-check closure authority changed after lease issuance"
            )

        entry = RuntimeClosureFile(relative, sha256, size_bytes)
        return RuntimeClosureManifest(
            task_id=task.task_id,
            task_sha256=lease.task_sha256,
            repository=task.repository,
            base_sha=task.base_sha,
            command_id=command_id,
            tool_id=VERSION_CHECK_TOOL_ID,
            catalog_sha256=registry.catalog.sha256,
            toolchain_sha256=registry.toolchain.sha256,
            lease_sha256=lease.sha256,
            workspace_root_sha256=lease.workspace_root_sha256,
            trusted_runtime_root_sha256=trusted_runtime_root_sha256(
                self.trusted_runtime_root
            ),
            entrypoint_relative_path=relative,
            working_directory=template.cwd,
            files=(entry,),
            total_bytes=size_bytes,
        )
