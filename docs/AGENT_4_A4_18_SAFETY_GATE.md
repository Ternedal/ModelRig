# A4-18 physical safety gate

`agent4-physical-read-operator.ps1` routes every stable launcher through
`agent4-physical-read-safety-gate.ps1` before the existing process, observation
or finalizer entrypoint is allowed to run.

## Why this layer exists

The first repository-green A4-18 harness still had four physical-proof gaps:

1. the generated backend command used `0.0.0.0`;
2. “one ADB device” did not prove physical Google Pixel hardware;
3. reset/enable/stop could continue after uncertain cleanup;
4. the finalizer could hash logs before the owned processes were stopped.

Repository CI cannot excuse any of those gaps. The safety gate therefore turns
them into executable, fail-closed preconditions.

## Enforced network boundary

During `PrepareOff` and `Enable`, an explicit temporary inbound block on port
8080 is installed **before** the legacy target starts. This prevents the
temporary wildcard listener from being reachable.

The gate then:

- verifies that the selected address is RFC1918;
- rejects Public, Tailscale, WSL, Hyper-V, Docker, VMware, VirtualBox and other
  virtual interfaces;
- stops the recorded backend by PID and executable identity;
- rewrites the generated command from `0.0.0.0` to the exact private LAN IP;
- replaces the firewall rule with exact `LocalAddress`, `LocalSubnet` and
  Private/Domain profiles;
- restarts and verifies exactly one backend listener on that IP;
- verifies exactly one worker listener on `127.0.0.1:8099`.

The grant CLI still expects loopback. For grant/revoke/regrant only, the gate
creates a short-lived Windows portproxy from `127.0.0.1:8080` to the already
verified private backend address. It is removed in `finally` and is never used
for Pixel traffic.

## Enforced device boundary

Before preparation, and again for grant/revoke/regrant/finalization, the gate
requires:

- exactly one authorized ADB device;
- serial not beginning with `emulator-`;
- `ro.kernel.qemu != 1`;
- `ro.boot.qemu != 1`;
- manufacturer `Google`;
- model beginning with `Pixel`;
- the same serial, manufacturer and model throughout the campaign.

Only a SHA-256 of the serial enters the final receipt.

## Enforced cleanup and receipt boundary

Transitions stop the recorded stack first and refuse to proceed when:

- a listener remains on port 8080 or 8099;
- a listener does not match the recorded executable/PID;
- firewall cleanup fails;
- an unknown process would need to be killed.

Before `Finalize`, the gate pre-stops the complete stack. The existing
finalizer therefore hashes closed, stable files. It then augments the receipt
with:

- physical Pixel evidence;
- serial hash;
- exact LAN/interface/profile evidence;
- backend and worker bind addresses;
- exact firewall local/remote scope;
- `wildcard_binding=false`;
- `artifacts_hashed_after_prestop=true`;
- `public_network=false`;
- `production_activation=false`.

The receipt digest is recalculated after the safety evidence is inserted.

## Operational rule

The safety gate is not optional. Running the lower-level process or finalizer
scripts directly is not a valid A4-18 physical campaign. Only the stable CMD
launchers through `agent4-physical-read-operator.ps1` may produce accepted
evidence.
