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

## Producing the evidence

`scripts/kaliv_repository_authority_assembler.py` builds the evidence file from
the verdicts that the four repositories' own
`verify-repository-authority.ps1 -Json` print. A file typed by hand is not
evidence.

### When each verdict can be taken

A verifier passes only from a clean `main` checkout whose commit is the one
GitHub's `main` stands on. A verdict for a release pin can therefore be taken
only **while that repository's `main` is still on the pin**. After the next
merge the pin can no longer be verified.

- **ModelRig:** directly after the version bump is merged, before anything else
  merges. Announce the pause on the coordination issue first.
- **BodyRig, VisionRig, VoiceRig:** as soon as their pins are chosen.

### What you need

- **`gh` signed in as an account with admin rights on the four repositories.**
  GitHub refuses to show branch protection to other accounts, and the verdict
  then fails.
- **PowerShell 7 (`pwsh`).** ModelRig's and BodyRig's verifiers require it.
- **One directory for the verdicts, outside all four checkouts.** A file inside
  a checkout makes it dirty, and the verifier refuses a dirty checkout.
- **A clean `main` checkout of each repository.** The rig's candidate checkout
  of ModelRig is not one: it is on a `physical-proof/*` branch and holds
  evidence under `validation/`.

### Capture

In each repository's `main` checkout, with its own file name:

```powershell
$E = "C:\Rig\evidence\repository-authority"
New-Item -ItemType Directory -Force $E | Out-Null

git switch main
git pull --ff-only
git status --short                      # must print nothing
.\verify-repository-authority.ps1 -Json > "$E\modelrig.json"
$LASTEXITCODE                           # must be 0
git rev-parse HEAD                      # this is the pin
```

Use `bodyrig.json`, `visionrig.json` and `voicerig.json` for the other three.
Exit code 2 means the verdict is a failing one; the file then says why in
`errors`.

### Assemble

From any ModelRig checkout that has the assembler. It does not have to be the
pinned one.

```powershell
python scripts\kaliv_repository_authority_assembler.py `
  --modelrig  "$E\modelrig.json"  --pin-modelrig  <modelrig-sha> `
  --bodyrig   "$E\bodyrig.json"   --pin-bodyrig   <bodyrig-sha> `
  --visionrig "$E\visionrig.json" --pin-visionrig <visionrig-sha> `
  --voicerig  "$E\voicerig.json"  --pin-voicerig  <voicerig-sha> `
  --output "$E\repository-authority-evidence.json" `
  --report "$E\kaliv-repository-authority-latest.json"
```

The four pins are the revisions of the release manifest.

Exit code 0 writes three files:

| File | What it is |
|---|---|
| `repository-authority-evidence.json` | The qualifier's input. |
| `repository-authority-evidence-assembly.json` | The record: each verdict file's name, SHA-256, size and encoding, the pins, and the release reference. |
| `kaliv-repository-authority-latest.json` | The qualifier's latest verdict on that evidence. **The next run replaces it. It is not immutable release evidence;** refer to the evidence file and the record. |

`release_evidence_ref` in the record and in the report is the value for
`--repository-authority-ref` in the release manifest.

Exit code 2 names the reason. The assembler refuses a verdict that:

- is not that repository's format, version 1, for `main`;
- is not a PASS, lists errors, or reports `main` as unprotected;
- claims production activation or any other authority;
- is for another commit than the pin;
- says GitHub's `main` was on another commit than the verified checkout.

It also refuses to replace an evidence file or record that already exists with
other content. Assembling the same verdicts again changes nothing.

### What a failed run leaves behind

- **A refusal writes nothing.** That covers everything above, the pins, and the
  qualifier's answer. All of it is decided before the first output file is
  created.
- **An I/O failure while publishing can leave the set incomplete:** the
  evidence file without its record, or both without the report.
  - The files are published in that order.
  - Each is complete or absent, and none replaces a file with other content.
  - A published evidence file has already been accepted by the qualifier.
  - The message names what was published. **Run the same command again to
    complete the set.**
- **Two runs at once cannot mix their results.** Each output is first written
  to its own `.<name>.<random>.staged` file and then published without
  replacing anything. If the two runs differ, one is refused.
- A run that is killed can leave a `.staged` file. Nothing reads it; delete it.

On a file system without hard links, publication is still exclusive, but a
second run started in the same instant can see a half-written file and be
refused. Run it again.

**Keep the four verdict files.** Each evidence reference is the SHA-256 of one
of them:

```text
repository-authority-verdict:<owner>/<repo>:<git-sha>:sha256:<sha256 of the verdict file>
```

A redirected verdict may be UTF-8 or, from Windows PowerShell 5.1, UTF-16. The
assembler reads both when the file starts with a byte-order mark or is plain
UTF-8. The hash is of the file as it was written.

### What the assembler does not prove

- It reads files. It reads no GitHub setting and runs no verifier.
- It cannot tell which copy of a verifier wrote a verdict, or when.
- A verdict is a reading of the settings at one moment. It says nothing about
  the settings before or after.
- The qualifier sees the evidence file only. A reviewer checks the verdict
  files against the hashes in the record.
- The rule that any field ending in `_authority` or `_activation` must be
  `false` is a naming convention. A verifier that named an authority field
  differently would not be caught by it. What bounds the schema is the format
  and version check: a new verdict format has to be added to the assembler on
  purpose.

## Run

```powershell
python scripts/kaliv_repository_authority_qualifier.py .\repository-authority-evidence.json `
  --report .\validation\kaliv-repository-authority-latest.json
```

Exit code 0 means all four exact repository-authority reports were accepted.
Exit code 2 means the evidence is malformed, incomplete, mutable, non-PASS, or
overclaims authority.
