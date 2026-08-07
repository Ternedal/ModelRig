# DC-L09 mutation results

**Status:** load-bearing mutations encoded; final exact-head execution pending.

## Required red states

The following changes must fail one or more landed contracts:

| Mutation | Detecting contract |
|---|---|
| Remove or alter any of the seventeen locked source blobs | source provenance and exact-path review |
| Remove a trusted-Git, receipt or facade module from the v7 bundle | H10R, Slice 9 and toolhost hash tests |
| Export process-launch symbols from package root, compatibility core, runtime staging or authority | H10R and the DC-L09 workflow boundary |
| Route the final facade to the legacy runner | H10R identity assertions and workflow boundary |
| Restore Windows fail-closed behavior in `bounded_subprocess` | native bounded-subprocess and receipt contracts |
| Replace the Linux subreaper with a weaker generic process-group path | Linux bounded-subprocess tests and source review |
| Keep DC-L09 modules in the foundation future-import denylist | foundation inventory test |
| Admit semantic-review, publisher or activation modules into the landed foundation set | foundation future-import test |
| Permit shell execution or inherited host Git configuration | trusted-Git runtime tests |
| Permit credentials, prompts or non-local protocol transport | trusted-Git runner environment and argument tests |
| Skip runtime-file revalidation before or after Git execution | trusted-Git runtime tamper tests |
| Accept unstaged or untracked workspace state before execution | command-receipt tests |
| Return a passing receipt after workspace mutation or reset | command-receipt model and orchestration tests |
| Allow Git runtime identity to change during orchestration | command-receipt runtime evidence tests |
| Remove bounded subprocess process-tree cleanup | Linux and native Windows bounded-subprocess contracts |
| Bypass AppContainer, Job Object, closure or lifetime checks | native Windows execution and receipt contracts |
| Bypass base physical signature, binding, probe or freshness verification in either Windows fixture projection | leased materializer and verifier base-class execution path |
| Add remote Git, GitHub mutation, publisher or credential imports | source-boundary and future-module gates |
| Omit one of the 31 portable modules or two DC-L09 Windows contracts from CI | workflow coverage contract |

## Observed integration states

The raw seventeen-file source import was intentionally opened before progressive
changes. Existing DC-L08 Windows execution remained green, proving that the new
files did not silently alter the private executor.

Static integration review exposed a real dependency before the first L09 receipt
run: the merged DC-L01 `bounded_subprocess` deliberately failed closed on Windows,
while `TrustedGitRunner` requires bounded Git execution on Windows. The correction
retains the newer Linux subreaper supervisor and adds only PR #338's native Job
Object spawn, termination and close adapter. The path is documented as a
progressive projection and is not claimed source-exact.

The first native receipt run then failed before process launch because its later
fixture used `PYTHONDONTWRITEBYTECODE`, which is outside the landed reviewed
application-environment positive list. CI now projects only that fixture value to
`MODELRIG_DEVCONTROL=1`; production policy remains unchanged and fail-closed.

The same candidate's portable suite exposed two stale DC-L08 source expectations:
`bounded_subprocess` still forbade all Windows Job Object references, and the
foundation inventory still classified the final facade, receipt and trusted-Git
modules as future. The adapter is now late-bound while preserving the Linux
subreaper source contract, and the foundation test moves only DC-L09 modules into
the landed set. All later semantic-review, publisher and activation imports remain
forbidden.

The next native receipt run passed bounded Job Object containment and the full
closure-bound executor, then failed while materializing its physical lease because
the later fixture's file-discovery assumptions do not match the independently
landed DC-L04 verifier boundary. The workflow now uses a test-only
`WindowsPhysicalIsolationVerifier` subclass that supplies the already signed
in-memory report candidate. Base signature, authority binding, mandatory probes
and freshness verification still execute unchanged; production verifier code is
untouched.

Progressive tests moved the signed bundle to v7, recognized the final facade and
activated bounded Git plus command-receipt Windows proof. Further concrete red
states found on the frozen candidate head are appended here before approval.
Green evidence is valid only when all four required workflows finish successfully
on the same exact commit.
