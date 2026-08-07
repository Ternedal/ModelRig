"""Import-only compatibility facade for the DC-L06 Tier-A identities.

The facade re-exports only lease, environment, path, materialization, retained
toolhost and retained v1 launch-plan identities that have landed by DC-L06.
Process launch remains deliberately absent until DC-L08.
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
