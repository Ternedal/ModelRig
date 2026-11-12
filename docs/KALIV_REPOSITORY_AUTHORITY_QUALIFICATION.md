# Kaliv repository authority qualification

`scripts/kaliv_repository_authority_qualifier.py` produces canonical
cross-repository evidence for the `repository_authority` system-release gate.

It consumes reviewed PASS outputs from the live repository-authority verifiers
in the four core repositories:

- `Ternedal/ModelRig`
- `Ternedal/BodyRig`
- `Ternedal/VisionRig`
- `Ternedal/VoiceRig`

The qualifier itself is read-only. It does not change branch protection,
rulesets, checks, permissions, merge policy, or production activation.

Each input entry must bind one exact 40-hex Git SHA to
`live_repository_authority_passed=true` and a distinct immutable evidence
reference. Mutable branch or tag identity is rejected.

A successful verdict emits:

```text
kaliv-repository-authority:<modelrig-sha>:<bodyrig-sha>:<visionrig-sha>:<voicerig-sha>:<sha256>
```

The system release gate compares all four embedded revisions against the
release-manifest repository pins. Repository-authority evidence cannot therefore
be reused across a different core-repository revision set.

The verdict keeps:

```json
{
  "repository_authority_gate_satisfied": true,
  "release_gate_satisfied": false,
  "production_activation": false
}
```

A PASS here proves only the reviewed repository-settings authority reports for
the exact pinned repositories. It does not prove physical validation, lifecycle,
Photoreal likeness, M6, latency, soak, Android live body, or final production
activation.

## Assemble the input from the four verifiers

Run each repository's verifier from a clean `main` checkout at the pinned revision
and save its one-line verdict, then assemble:

```powershell
pwsh -File .\verify-repository-authority.ps1 -Json > ..\authority-modelrig.json   # likewise in BodyRig, VisionRig, VoiceRig
python scripts/kaliv_repository_authority_assembler.py `
  --modelrig .\authority-modelrig.json --bodyrig .\authority-bodyrig.json `
  --visionrig .\authority-visionrig.json --voicerig .\authority-voicerig.json `
  --expect Ternedal/ModelRig=<pin> --output .\repository-authority-evidence.json
```

`scripts/kaliv_repository_authority_assembler.py` accepts a verdict only when it is
that repository's own format, version 1, `passed` with no errors, bound to one exact
40-hex `head_revision` (and to GitHub's `main` on the same revision where the verifier
reports it), and claims no production, physical or Agent 3 authority. Each entry's
`evidence_ref` is `sha256:<hex of the exact bytes read>:<format>`. `--expect
OWNER/REPO=<sha>` refuses any other head. It runs the qualifier on the result before
writing, so exit 0 means the file below will be accepted; exit 2 writes nothing.
UTF-16 files (Windows PowerShell 5.1's `>`) and a UTF-8 BOM are read.

## Run

```powershell
python scripts/kaliv_repository_authority_qualifier.py .\repository-authority-evidence.json `
  --report .\validation\kaliv-repository-authority-latest.json
```

Exit code 0 means all four exact repository-authority reports were accepted.
Exit code 2 means the evidence is malformed, incomplete, mutable, non-PASS, or
overclaims authority.
