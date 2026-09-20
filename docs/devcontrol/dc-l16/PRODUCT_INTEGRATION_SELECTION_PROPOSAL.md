# DC-L16 product integration selection proposal

**Date:** 14/09-2026  
**Status:** proposal only — not human accepted  
**production_activation:** false

## Purpose

Turn the ADR-DC-018 exact-source inventory into one concrete recommendation that can be accepted, rejected, or changed by the human operator without silently creating product or execution authority.

This document is deliberately not an ADR and not a GO decision. It does not satisfy the separate human decision required by issue #423.

## Recommended operator surface

Recommend `desktop.control-center` as the first DC-L16 pilot surface.

Reasons:

- it is already a normal ModelRig operator surface;
- its current interaction model is explicit manual refresh with no automatic polling;
- it keeps the first pilot on the Windows operator host instead of making Android a remote control plane;
- it can reuse the backend's existing Bearer-authenticated route-host pattern;
- it gives the pilot a visible place for status, revoke/stop state and receipts without introducing an unattended agent.

Android Control Center remains a later candidate, not a fallback authority surface.

## Proposed integration identifiers

The proposal reserves names only; it does not implement or mount them:

- feature flag: `KALIV_DEVCONTROL_PILOT`;
- route prefix: `/api/v1/experimental/devcontrol-pilot`;
- runtime observer: `desktop-manual-refresh-only`;
- task registry: explicit allowlist, empty until a separate human GO;
- workspace policy: one canonical explicit root on the loopback host;
- local commits: forbidden until a separate human GO explicitly allows them.

## Default-deny pilot shape

Even after a later acceptance of the surface selection, the first implementation must remain fail-closed:

- flag default off;
- no product import of `kaliv_dev_control` while off;
- no automatic polling or unattended cadence;
- no remote transport or credentials;
- no free-form shell or model-defined command registration;
- no local commit until explicitly authorized by the signed human pilot scope;
- no push, PR mutation, merge, release, deploy or production activation.

The desktop surface must not become an authority source by itself. It may display verified state and submit an explicitly bounded local pilot request only after the existing signed authority chain and runtime preflight are satisfied.

## Human decision still required

The machine-readable proposal keeps all selection booleans false, including `human_selection_accepted=false`. A later artifact must record the actual human choice and bind it to the exact inventory/proposal revision before any product source is changed.

Until then:

- no feature flag is implemented;
- no route is mounted;
- no UI control is added;
- no runtime observer is installed;
- no task type is registered;
- no pilot execution is authorized.

`production_activation=false` remains invariant.
