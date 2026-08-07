# DC-L03 independent review verdict

Status: **pending fresh review of the resulting exact evidence head**

Validated runtime and regression candidate:
`fe415f0562f2e3d57d600c80e33673b92b58bfde`.

Its complete base diff remains exactly the 16 paths declared by
`exact-path-allowlist.json`, it is 0 commits behind
`main @ c9bda459f10e682ec200fdfea8484d726c6c0057`, and all repository workflows
passed:

- `ci` `31156740333`;
- `codeql` `31156738980`;
- `agent3-diagnostics` `31156739176`;
- `agent3-full-diagnostics` `31156738930`.

Latest independent review sequence:

1. Review of `5c7a969f55f763e37f95aa6f75332c1a9146705c` found that the
   Landlock/seccomp bootstrap still used ambient `sys.executable` and that locale
   and timezone values could be inherited from the launch environment.
2. `b52e42728fed447981a24b64554a22a0abea175f` closed those findings with an
   immutable bootstrap resolved through the attested toolchain and descriptor
   verifier, plus fixed `PATH`, `LANG`, `LC_ALL`, `LC_CTYPE` and `TZ` values.
3. All four workflows passed on that head, but its fresh review found one P1:
   the pinned top-level Go driver could still execute mutable compiler, vet,
   assembler and linker helpers from its compiled-in GOROOT.
4. `fe415f0562f2e3d57d600c80e33673b92b58bfde` closes that finding fail-closed:
   the default catalog no longer exposes `modelrig.backend.vet` or
   `modelrig.backend.tests`, every `ProjectCommandSpec` with `tool_id="go"` is
   rejected before materialization, and `GOTOOLCHAIN` is no longer accepted.
5. The executable regression proves the two Go IDs are absent, direct Go specs
   fail with the helper-attestation error, and a task granting a removed Go
   command cannot materialize it.

Review focus for the resulting evidence head:

1. exact task, catalog, toolchain and attestation snapshots;
2. one private execution task across sandbox, budgets, verification and receipt;
3. sealed executable and sandbox-bootstrap objects;
4. fixed process environment with no ambient loader, interpreter, PATH, locale,
   timezone or Go-toolchain authority;
5. fail-closed absence of Go command execution until the complete helper chain
   can be attested and pinned;
6. fixed GET-only GitHub host/method/ref authority;
7. explicit TLS trust roots and disabled environment proxies/redirects;
8. one monotonic deadline across setup, request, framing and body with no
   post-timeout send or reconnect;
9. bounded response handling, Git-blob identity and strict receipts;
10. absence of GitHub write, remote Git, generic launch, publication, merge,
    deployment or activation authority.

This evidence update changes the branch head without changing runtime code or
the 16-path set. No final independent verdict is claimed until the resulting
exact head passes all four workflows and receives a fresh review with no
remaining actionable thread.