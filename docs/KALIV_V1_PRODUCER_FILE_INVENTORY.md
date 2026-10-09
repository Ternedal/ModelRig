# Kaliv V1 producer-file inventory — read-only, never release authority

This is an **optional operator-side file-accounting aid**, developed only on
the isolated draft branch for [ModelRig #2111](https://github.com/Ternedal/ModelRig/issues/2111).
It does **not** change the final release gate or permit a new software freeze,
tag, promotion, or production activation.

The existing `kaliv_system_release_gate.py` verifies canonical evidence-ref
syntax, ten gate statuses and SHA bindings, but does not retrieve the producer
reports. This tool closes **one narrower bookkeeping gap**: it checks that
each gate declared PASS has a specific non-symlink local report whose exact
bytes SHA-256 match the indexed hash, and that the report's evidence ref
agrees with the manifest. An absent report is rejected. PASS and PENDING
gates must match the index exactly: no made-up extra entries.

## Important limitation

The presence of an internally consistent JSON file **does not prove**
that the file came from an actual physical device, model, authenticated
source or human reviewer. An operator who can rewrite both the report
and its index can still construct mutually consistent text. The tool
**never** returns `release_ready=true`,
`release_gate_satisfied=true` or `production_activation=true`,
even when every local file matches. It never marks a V1 gate PASS or
creates a canonical release ref. Independent producer revalidation and
human inspection are required as tracked in #2111 and campaign #2025.

## Inputs (operator-supplied, local only)

The existing release manifest schema remains
`kaliv-system-release-manifest/v1`. A separate index has this shape:

```json
{
  "schema": "kaliv-system/producer-file-index/v1",
  "entries": [
    {
      "gate": "software_exact_green",
      "report_path": "software-exact-green-verdict.json",
      "sha256": "<64 lowercase hexadecimal characters>"
    }
  ]
}
```

The example is a **format illustration only**. It does not assert that the
file or SHA exists. `entries` must contain **exactly** the gates declared
`PASS` by the input manifest. For the current V1 state, only the software
gate is qualified; the nine others must remain PENDING and have no index
entry. Do not create fake reports or fill in made-up hashes to satisfy the
tool.

`report_path` is relative to the `--evidence-root` directory. Escapes,
absolute paths, symlinks, malformed or duplicate JSON keys, oversized files,
wrong SHA-256s, missing refs, ref mismatches, explicit failure and false
production/system authority claims fail closed. The inventory includes
report byte digests and schema names for human review, not raw audio,
video, tokens, or other private content.

## Execute on a separately checked-out candidate branch

```powershell
python scripts/kaliv_release_producer_file_inventory.py `
  --manifest .\validation\kaliv-release-manifest.json `
  --index .\validation\producer-file-index.json `
  --evidence-root .\validation\producer-reports

python tests/workflow_kaliv_release_producer_file_inventory.py
```

Do not change the operator's clean frozen V1 checkout just to run this draft
code. The script's output state is `SOURCE_FILES_ACCOUNTED_FOR` and its
`release_ready` field is **always false**, by design.

A full release process must additionally re-run or independently authenticate
the appropriate *producer* validators and physical/human evidence for all
ten gates, and must establish the exact four-repo freeze and repository
authority. This inventory is not that final proof.

## Software-freeze

ModelRig `0b2ff455116f4f28a1a41704d9cb81503f17d2df`,
BodyRig `8a85597637d0b59947bd179366e27be1bb847c16`,
VisionRig `66ea9bfce1c4d219e4bac1d85324a0e6e3f042e5`,
VoiceRig `9f3e594996db7eb2c6e035247ecb168bf17c1dae`.

`software_exact_green=QUALIFIED`. The remaining nine independent physical
or administrative gates are PENDING. `release_ready=false`;
`production_activation=false`.
