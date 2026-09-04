# BodyRig integration contract authority

These files are the **ModelRig-side consumer contract snapshot** for BodyRig V1. They are not a second BodyRig implementation.

Canonical runtime/build implementation lives in `Ternedal/BodyRig`. This snapshot was reconciled against BodyRig draft PR #1 at exact head:

`5f6c93aef172be503c84af0b5fb1f8554ec9f520`

That BodyRig head is independently green in its own CI. The ModelRig snapshot intentionally remains local and self-contained: ModelRig CI does not fetch or execute BodyRig code.

## Synchronization rule

A BodyRig V1 contract change is not assumed compatible merely because the version number still says `1`. Any change to BodyRig's package/runtime contract must be reviewed against these consumer schemas and land through a new exact-head-qualified ModelRig change.

At minimum, synchronization must preserve:

- the same `.mrbody` required/optional path envelope;
- checksum coverage of payload files only (never `manifest.json` or `checksums.json` itself);
- the BodyCue semantic field envelope and shared `utterance_id` contract;
- fail-closed unknown fields and versions;
- no source-media filenames or private source paths in portable provenance;
- no scripts, plugins, native code or model checkpoints in `.mrbody`.

Stricter ModelRig-side validation is allowed only when it remains compatible with BodyRig output and is documented as a consumer safety constraint.

`production_activation=false`.
