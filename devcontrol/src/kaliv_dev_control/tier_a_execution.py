"""Public compatibility surface for the sole Tier-A v3 implementation."""
from .runtime_closure import (
    HmacRuntimeClosureSigner,
    RuntimeClosureError,
    RuntimeClosureFile,
    RuntimeClosureManifest,
    RuntimeClosureStagingReceipt,
    RuntimeClosureVerifier,
    SignedRuntimeClosureManifest,
    TrustedRuntimeClosureStager,
    trusted_runtime_root_sha256,
)
from .tier_a_authority import (
    PLAN_SCHEMA,
    LeasedCatalogMaterializer,
    LeasedCommandRegistry,
    TIER_A_APPLICATION_ENVIRONMENT,
    TierAExecutionError,
    TierAExecutionLease,
    tier_a_toolhost_sha256,
    working_directory_authority_sha256,
    workspace_root_authority_sha256,
)
from .tier_a_execution_v3 import (
    TierAExecutionTimeout,
    _run_tier_a_launch_plan as _run_tier_a_launch_plan,
    run_verified_tier_a_command,
)
from .tier_a_plan import TierALaunchPlan, build_tier_a_launch_plan

__all__ = [
    "HmacRuntimeClosureSigner",
    "LeasedCatalogMaterializer",
    "LeasedCommandRegistry",
    "PLAN_SCHEMA",
    "RuntimeClosureError",
    "RuntimeClosureFile",
    "RuntimeClosureManifest",
    "RuntimeClosureStagingReceipt",
    "RuntimeClosureVerifier",
    "SignedRuntimeClosureManifest",
    "TIER_A_APPLICATION_ENVIRONMENT",
    "TierAExecutionError",
    "TierAExecutionLease",
    "TierAExecutionTimeout",
    "TierALaunchPlan",
    "TrustedRuntimeClosureStager",
    "build_tier_a_launch_plan",
    "run_verified_tier_a_command",
    "tier_a_toolhost_sha256",
    "trusted_runtime_root_sha256",
    "working_directory_authority_sha256",
    "workspace_root_authority_sha256",
]
