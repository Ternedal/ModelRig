# Design: Windows ACL check for credential files

**Status: implemented in three steps; step 3 wires it into the loaders.**
Tracking: KalivNexus #1 (ChatGPT queue item 3).

| Step | What | Where |
| --- | --- | --- |
| 1 | Pure judgment `evaluate_credential_acl` | `worker/app/credential_acl.py` (#2291) |
| 2 | Windows reader: owner + DACL from the opened handle | `worker/app/credential_acl_windows.py` (#2294) |
| 3 | Shared loader `read_private_credential`; all three loaders use it | `worker/app/credential_file.py` (this step) |

Step 3 changes behaviour **on Windows only**: a token file that other users
can read is now refused, and so is a symlinked or junctioned token file.
POSIX accepts and refuses exactly what it did before.

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
   - Any `ACCESS_ALLOWED` ACE for any other SID that holds **anything
     beyond** `SYNCHRONIZE | FILE_READ_ATTRIBUTES | READ_CONTROL`: refuse.
     This is an allowlist, not a denylist. It covers reading, tampering
     (`FILE_WRITE_DATA`, `FILE_APPEND_DATA`, `GENERIC_WRITE`, `DELETE`),
     execution and mapping (`FILE_EXECUTE`, `GENERIC_EXECUTE`), changing
     permissions or ownership (`WRITE_DAC`, `WRITE_OWNER`), and any unknown
     bit. The allowlist was adopted after review 5660140985 and is
     implemented in #2291.
   - SIDs are parsed canonically: `S-1-`, ASCII decimal digits, no leading
     zeros, a 48-bit identifier authority, and 1–15 subauthorities of 32
     bits each. Anything else refuses (Codex P2 on #2291).
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

## Operator guidance

Lock the file to **the account the worker runs as**. The check uses the
process user, not whoever created the file. On the rig the worker is a child
of the `KalivSupervisor` scheduled task, so read the account from there and
from the running worker rather than assuming it is `$env:USERNAME` (review
5673456488):

```powershell
(Get-ScheduledTask -TaskName KalivSupervisor).Principal.UserId
Get-CimInstance Win32_Process -Filter "Name='modelrig-worker-windows-x64.exe'" | Invoke-CimMethod -MethodName GetOwner
icacls C:\Rig\secrets\ha.token /inheritance:r /grant:r "<account>:R"
```

The full steps are in `docs/T038_HOME_ASSISTANT_LIVE_READ.md`, step 1.

## Step 3: one handle for the judgment and the read

`read_private_credential(path, *, max_bytes)` in `worker/app/credential_file.py`
is the only way the three loaders read a token file. Each loader keeps its own
error messages; a refusal carries a `kind` (`unavailable`, `not_regular`,
`size`, `permissions`, `unverifiable`, `read`) that maps onto them.

- **Windows:** `read_private_credential_windows` opens **one** handle with
  `FILE_READ_DATA | READ_CONTROL | FILE_READ_ATTRIBUTES`, share mode
  `FILE_SHARE_READ` only and `FILE_FLAG_OPEN_REPARSE_POINT`. On that handle it
  checks the attributes (no reparse point, no directory), the size and the
  DACL, and only then reads the bytes with `ReadFile`. Nothing can be swapped
  in between, and nobody can write, rename or delete the file while it is
  open. A file someone else holds open for writing is refused (`read`).
- **POSIX:** the same checks as before (regular file, bounded size, no
  group/other bits, symlinks followed), but run with `fstat` on the open
  descriptor instead of `stat` on the name. That closes the gap between the
  check and the read. A name check still refuses a device or FIFO before it
  is opened, and `O_NONBLOCK` keeps one swapped in afterwards from hanging the
  loader.
- **Any other platform:** refused (`unverifiable`).

## Verified, and what is not

Verified on the Windows CI runner with dummy files
(`tests/support/windows_credential_acl_contract.py`):

- the `ctypes` signatures and the ACE layout (step 2);
- that `icacls`-made ACLs judge as listed above;
- that the runner's inherited temp-folder ACL is accepted;
- that each loader refuses `Users:R` with its existing message.

**Not verified:** the real rig. The worker's account and the folder holding
the token there have not been checked. Run the `icacls` command above before
the first live read.

## Open questions for review

- Should `Administrators` and `SYSTEM` stay allowed? Allowing them weakens
  nothing that a local admin can't already do.
- Should the check be one helper for all three loaders, as proposed, or start
  with T-038 only? **Step 3 implements one helper for all three**, so that the
  GitHub connector does not keep the gap. Reviewers can still ask for the
  GitHub loader to be split out.
