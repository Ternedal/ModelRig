# Design: Windows ACL check for credential files

**Status: design only, nothing is implemented.** Tracking: KalivNexus #1
(ChatGPT queue item 3), and the PENDING gap in
`docs/T038_HOME_ASSISTANT_LIVE_READ.md`.

## The gap (verified in code, 2026-10-26)

Three loaders accept a bearer token from a file. Each checks that the path is
a regular file and that its size is bounded. Each rejects a file that other
users can read **only on POSIX**:

| Loader | Line on `main` |
| --- | --- |
| `worker/app/home_assistant_provider_transport.py` `_load_bearer` | 184 `if os.name == "posix" and (info.st_mode & 0o077)` |
| `worker/app/riggate_provider_transport.py` `_load_bearer` | 178, same |
| `worker/app/github_connector_transport.py` | 89 `if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077` |

On Windows, `os.stat().st_mode` reflects only the read-only attribute, so
nothing checks who can read the file. The worker runs on a Windows rig. A
token file in a folder whose inherited ACL grants `Users`, `Authenticated
Users` or `Everyone` read access is accepted silently.

## Goal

On Windows, accept a credential file only if its security descriptor shows
that **nobody except the process's own user, LocalSystem and the
Administrators group** can read it, change its permissions or take ownership.
If that cannot be established, **refuse**. Refusal is already safe, because
every caller turns a credential failure into `unknown` / unavailable.

## Rule

Reading the descriptor and judging it are separate steps.

1. **Read:** `GetNamedSecurityInfoW(path, SE_FILE_OBJECT,
   OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION)`, called through
   `ctypes` on `advapi32`. This avoids a new dependency for the frozen worker.
   Convert each SID with `ConvertSidToStringSidW`. Take the process user from
   `OpenProcessToken` plus `GetTokenInformation(TokenUser)`.
2. **Judge:** a pure function

   ```
   evaluate_credential_acl(owner_sid, dacl, process_sid) -> (ok, reason)
   ```

   - `dacl` is `None` (a NULL DACL grants everyone full access): refuse.
   - The owner is not the process SID, `S-1-5-18` (LocalSystem) or
     `S-1-5-32-544` (Administrators): refuse.
   - Any ACE type other than `ACCESS_ALLOWED` or `ACCESS_DENIED` (object,
     callback or conditional ACEs): refuse, because it is not understood.
   - Any `ACCESS_ALLOWED` ACE for any other SID whose mask contains a read or
     escalation right: refuse. The rights are `FILE_READ_DATA` (0x1),
     `GENERIC_READ`, `GENERIC_ALL`, `WRITE_DAC`, `WRITE_OWNER` and
     `MAXIMUM_ALLOWED`.
   - `ACCESS_DENIED` ACEs never make a file acceptable. They are ignored, and
     only allow ACEs decide who can read. That is conservative by
     construction.
   - Inherited ACEs count exactly like explicit ones.
3. **Default deny:** any `ctypes` or API failure, a non-zero Win32 error, or
   an ACE that cannot be parsed results in a refusal.

The judging function goes into one shared helper (for example
`worker/app/credential_file.py`) that all three loaders call. The POSIX branch
stays as it is.

## How it is tested without secrets or the rig

- **Pure function on every OS:** synthetic `(owner, dacl, process)` inputs.
  - Accepted: only the process user; process user plus SYSTEM plus
    Administrators.
  - Refused:
    - a NULL DACL;
    - a foreign owner;
    - `Users:R`;
    - `Authenticated Users:R` (`S-1-5-11`);
    - `Everyone:R` (`S-1-1-0`);
    - another user with `WRITE_DAC` but no read;
    - an unknown ACE type;
    - an inherited `Users:R`.

  Each refusal is checked with a mutation that removes the corresponding rule.
- **Windows runner, already present in CI:** a temp file holding a dummy
  token, with permissions set by `icacls`.
  - `/inheritance:r /grant:r "<user>:R"` is accepted.
  - Adding `*S-1-5-32-545:R` (Users) or `*S-1-1-0:R` (Everyone) is refused.
  - Restoring inheritance in a world-readable folder is refused.

  No real token is involved, and the Windows job list gets one new contract.
- **Through the transport:** the E2E test in #2289 gains a Windows case: a
  too-broad ACL gives `unknown` and the fixture receives zero requests.

## Operator guidance (once implemented)

Lock the file to the account the worker runs as:

```powershell
icacls C:\Rig\secrets\ha.token /inheritance:r /grant:r "$env:USERNAME`:R"
```

If the worker runs as a different account (a service), grant that account
instead. The check uses the **process** user, not whoever created the file.

## Not verified yet

These come from Windows API knowledge and must be checked during
implementation, on the Windows CI runner:

- the exact `ctypes` signatures;
- the ACE header layout;
- the generic-to-file rights mapping;
- whether `icacls`-made ACLs produce exactly the ACE sets listed above.

## Open questions for review

- Should `Administrators` and `SYSTEM` stay allowed? Allowing them weakens
  nothing that a local admin can't already do.
- Should the check be one helper for all three loaders, as proposed, or start
  with T-038 only? The proposal is one helper, so that the GitHub connector
  does not keep the gap.
