# Agent 3 cancellation contract (T-023 dormant server slice)

**Status:** server-authoritative status contract; client controls and physical validation remain outstanding.

A stop request has three distinct scopes: the Agent 3 plan, a model stream and the active tool. The API returns `kaliv-agent3-termination/v1` with a separate status for each scope.

The existing cancel endpoint stops the **plan** and prevents future steps. The synchronous Agent 3 executor exposes no per-call handle, so an executing tool is never presented as directly interruptible. If a tool is already executing, the plan receipt explicitly states `prevent_future_steps_active_tool_continues`.

Tool-family semantics are read from the existing registry:

- `none` → `none`
- `cooperative` → `cooperative`
- `forceable` → API `runtime`

A declaration is not a handle. `pull_model` declares cooperative cancellation for its background JobStore job, but Agent 3 does not bind that job handle to the active step. Consequently `handle_present=false` and `can_request=false` remain the truthful values. Missing tools and unknown declarations fail closed in the receipt.

Late completion remains visible as `completed_after_cancel` with its actual result. The run remains terminally cancelled.

This slice does not activate Agent 3 routing, add a killable runtime, stop model streams, change the existing cancel endpoint, or claim Pixel/desktop coverage. Android and desktop must consume this receipt and replace the generic cancellation control before T-023 can be promoted.
