# Kaliv software exact-green qualification

`scripts/kaliv_software_exact_green_qualifier.py` produces the canonical
cross-repository evidence for the `software_exact_green` system-release gate.

It does **not** run CI itself and it does not infer physical readiness. It
validates reviewed exact-head software evidence for the four core repositories:

- `Ternedal/ModelRig`
- `Ternedal/BodyRig`
- `Ternedal/VisionRig`
- `Ternedal/VoiceRig`

Each repository entry must carry an immutable 40-hex Git SHA, an explicit
`exact_head_qualified=true`, `software_green=true`, and a distinct bounded
software-evidence reference. Mutable names such as `main`, tags or branch names
are rejected as revision identity.

A successful verdict emits:

```text
kaliv-software-exact-green:<modelrig-sha>:<bodyrig-sha>:<visionrig-sha>:<voicerig-sha>:<sha256>
```

The final system-release gate compares all four embedded SHAs with the release
manifest pins. A PASS therefore cannot be reused for a different BodyRig,
VisionRig or VoiceRig revision merely because ModelRig stayed unchanged.

The qualifier is software-only. Its verdict always keeps:

```json
{
  "software_exact_green_gate_satisfied": true,
  "release_gate_satisfied": false,
  "production_activation": false
}
```

It does not satisfy lifecycle, physical perception, Photoreal likeness, M6
digital-twin, Android live-body, latency, soak, repository-authority, or final
production activation.

## Assemble it from GitHub Actions

Do not type the input by hand. `scripts/kaliv_software_exact_green_assembler.py`
reads it from GitHub for the four pins (read-only `gh api`, with the operator's
`gh` login):

```powershell
python scripts/kaliv_software_exact_green_assembler.py `
  --pin-modelrig <sha> --pin-bodyrig <sha> --pin-visionrig <sha> --pin-voicerig <sha> `
  --out .\validation\software-exact-green\<date>
```

Per repository it requires:
- the newest `exact-head-qualification` run on exactly that `head_sha`,
  completed with success;
- the newest run of each required workflow, completed with success;
- every check run on the commit completed with success, skipped or neutral.

The required workflows per repository:

| Repository | Required workflows |
|---|---|
| ModelRig | `ci`, `codeql`, `agent3-full-diagnostics`, `exact-head-qualification` |
| BodyRig | `ci`, `codeql`, `exact-head-qualification` |
| VisionRig | `tests`, `exact-head-qualification` |
| VoiceRig | `tests`, `CodeQL`, `windows-lifecycle`, `exact-head-qualification` |

**VisionRig runs `exact-head-qualification` only on `workflow_dispatch`.**
Dispatch it for the pin before assembling; without it the assembler refuses.
Measured 16/11 on VisionRig `main` `efe0c15c`: only `tests` ran.

**Dispatch while the pin is still the head of the branch you dispatch on.** A
dispatched run, and its check runs, carry the branch head as `head_sha`, not
the `head_sha` input. If VisionRig `main` has moved past the pin, the run is
not visible on the pin, and the assembler refuses. In that case pin the new
head, or dispatch from a branch whose head is the pin:

    gh workflow run exact-head-qualification.yml -R Ternedal/VisionRig --ref main -f head_sha=<pin>

It writes a new directory holding:
- one capture file per repository, with the runs and check runs it judged;
- the evidence file;
- an assembly record with the qualifier's verdict.

Each `evidence_ref` names the exact-head run and binds the SHA-256 of its
capture file. The qualifier runs before anything is written; a refusal writes
nothing.

**Limits:**
- It sees GitHub's answer at assembly time.
- The workflow list is the assembler's own, not read from branch protection.

## Input shape

```json
{
  "schema": "kaliv-system/software-exact-green-evidence/v1",
  "repositories": [
    {
      "repository": "Ternedal/ModelRig",
      "git_sha": "<40-hex>",
      "exact_head_qualified": true,
      "software_green": true,
      "evidence_ref": "github-actions:<immutable-ref>"
    }
  ],
  "production_activation": false
}
```

All four required repositories must appear exactly once.

## Run

```powershell
python scripts/kaliv_software_exact_green_qualifier.py .\software-evidence.json `
  --report .\validation\kaliv-software-exact-green-latest.json
```

Exit code 0 means the supplied software evidence is structurally qualified.
Exit code 2 means it is malformed, incomplete, not exact-head green, or
overclaims authority.
