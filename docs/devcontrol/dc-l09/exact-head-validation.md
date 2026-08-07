# DC-L09 exact-head validation

**Status:** pending final head freeze and workflow completion.

## Required frozen state

- base branch: `main`
- exact base: `70a40a27201ccaa33b1dffe0fff65faa113cd0f7`
- changed paths: exactly 34 and identical to `exact-path-allowlist.json`
- commits behind `main`: 0
- source-exact paths: 17, matching `source-provenance.json`
- progressive paths: 9, including the Linux-preserving Windows containment and
  landed/future foundation-inventory projections
- unresolved review threads: 0

## Required workflows

The following four pull-request workflows must all complete successfully on one
identical head SHA:

- `ci`
- `codeql`
- `agent3-diagnostics`
- `agent3-full-diagnostics`

## Required CI evidence

- backend build, vet and tests;
- Python and PowerShell syntax/lint gates;
- repository test inventory;
- all 31 DevControl test modules through DC-L09;
- final facade and trusted-Git boundary assertions;
- final authority regressions;
- Android and desktop compilation/tests;
- Windows appliance and DPAPI contracts;
- Browser Use controlled-Chromium contract;
- native Job Object, AppContainer, environment and ToolHost contracts;
- native bounded-subprocess process-tree cleanup;
- closure-bound verified Tier-A execution; and
- Git-aware Tier-A command receipt using a staged pinned Git runtime.

Workflow IDs, final head SHA and conclusions are recorded in the PR body only
after the candidate is frozen. Any code or control-artifact change invalidates
this validation and requires a fresh exact-head run.
