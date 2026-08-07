"""Import-only compatibility facade for landed non-executing Tier-A identities.

DC-L07 keeps this historical facade limited to lease, environment, path,
materialization, stage-local toolhost and retained v1 launch-plan identities.
Runtime staging, signed closures, v3 planning and result evidence live in their
focused modules. Process launch remains deliberately absent until DC-L08.
"""
from __future__ import annotations

from ._tier_a_lease import (
    LEASE_SCHEMA,
    TierAExecutionError,
    TierAExecutionLease,
    _HEX40,
    _HEX64,
    _TASK_ID,
    _canonical,
    _sha256,
    _task_sha,
)
from ._tier_a_path_authority import (
    _canonical_directory,
    _has_symlink_component,
    _regular_file_hash,
    workspace_root_authority_sha256,
)
from ._tier_a_legacy_toolhost import (
    _TIER_A_BUNDLE_FILES,
    tier_a_toolhost_sha256,
)
from ._tier_a_legacy_plan import (
    PLAN_SCHEMA,
    _COMMAND_ID,
    TierALaunchPlan,
    build_tier_a_launch_plan,
)
from ._tier_a_materialization import (
    _LeaseCapturingVerifier,
    LeasedCommandRegistry,
    LeasedCatalogMaterializer,
)
from ._tier_a_environment import (
    TIER_A_APPLICATION_ENVIRONMENT,
    _validated_application_env,
)

for _forbidden_execution_name in (
    "_run_tier_a_launch_plan",
    "run_verified_tier_a_command",
):
    if _forbidden_execution_name in globals():
        raise TierAExecutionError(
            f"DC-L07 compatibility core exposes forbidden execution authority: "
            f"{_forbidden_execution_name}"
        )
del _forbidden_execution_name
