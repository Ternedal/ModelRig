# Kaliv delivery snapshot — operator guide

This workflow is **manual only** (`workflow_dispatch`) and creates a JSON +
Markdown artifact. It never comments, merges, publishes, deploys, or changes a
repository. It is currently isolated on the development branch; GitHub may
require the workflow file to be present on the default branch before manual
dispatch is available.

## Provisioning

Create repository Actions secret `KALIV_REPORT_READ_TOKEN` using a fine-grained
GitHub token with **read-only** access to the ten participating repositories:
metadata, issues, pull requests and Actions. Scope the token to the smallest
repository set and expiry possible. Never paste the token into issues, logs,
chat or committed files. Without the secret, the collector attempts public GitHub API reads only. Private or inaccessible repositories remain unknown and the completeness gate fails; public API rate limits may also apply.
The built-in `GITHUB_TOKEN` is not assumed to read all other repositories.

## Run and interpret

Use GitHub Actions > **Kaliv Delivery Snapshot** > Run workflow when available
on the default branch. Download `kaliv-delivery-snapshot` artifact, containing
`kaliv-delivery.json` and `kaliv-delivery.md`. Artifacts may include
private repository metadata; review who can access workflow artifacts.
The artifact expires after 14 days.

The upload step uses `always()` to preserve any available diagnostics even when an earlier step fails. If collection fails before writing files, there may be no artifact; inspect the workflow logs.\n\nThe report collects open issue/PR counts, PR age, and the latest workflow
conclusion. It does **not** prove required checks, production readiness,
physical acceptance, release status, or that a critical user journey works.
HTTP failures and incomplete pagination must remain visible as warnings.

## Limitations and next gate

- No scheduled automation until permissions, token scope and reporting output
  have been reviewed.
- No cross-repository issue dependency graph or real blocker ownership yet.
- A manual workflow run is not equivalent to a deployed control plane.
- Avoid using these counts as a productivity ranking; prioritize user journeys.
- If any participating repository cannot be read, its status remains unknown.
