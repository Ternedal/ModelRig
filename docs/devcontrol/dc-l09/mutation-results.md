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
| Permit shell execution or inherited host Git configuration | trusted-Git runtime tests |
| Permit credentials, prompts or non-local protocol transport | trusted-Git runner environment and argument tests |
| Skip runtime-file revalidation before or after Git execution | trusted-Git runtime tamper tests |
| Accept unstaged or untracked workspace state before execution | command-receipt tests |
| Return a passing receipt after workspace mutation or reset | command-receipt model and orchestration tests |
| Allow Git runtime identity to change during orchestration | command-receipt runtime evidence tests |
| Remove bounded subprocess process-tree cleanup | Linux and native Windows bounded-subprocess contracts |
| Bypass AppContainer, Job Object, closure or lifetime checks | native Windows execution and receipt contracts |
| Add remote Git, GitHub mutation, publisher or credential imports | source-boundary and future-module gates |
| Omit one of the 31 portable modules or two DC-L09 Windows contracts from CI | workflow coverage contract |

## Observed integration states

The raw seventeen-file source import was intentionally opened before progressive
changes. Existing DC-L08 Windows execution remained green, proving that the new
files did not silently alter the private executor.

Static integration review then exposed a real dependency before the first L09
receipt run: the merged DC-L01 `bounded_subprocess` deliberately failed closed on
Windows, while `TrustedGitRunner` requires bounded Git execution on Windows. The
correction retains the newer Linux subreaper supervisor and adds only PR #338's
native Job Object spawn, termination and close adapter. The path is documented as
a progressive projection and is not claimed source-exact.

Progressive tests moved the signed bundle to v7, recognized the final facade and
activated bounded Git plus command-receipt Windows proof. Further concrete red
states found on the frozen candidate head are appended here before approval.
Green evidence is valid only when all four required workflows finish successfully
on the same exact commit.
