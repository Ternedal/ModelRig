# DC-L14 exact-head validation

**Status:** final freeze criteria defined. The current PR head is eligible only while all required checks attached to that exact head are successful.

The mergeable head must prove:

- exactly 25 changed paths matching `exact-path-allowlist.json`;
- zero commits behind `main`;
- all 11 source identities recorded in `source-provenance.json`;
- all explicit adaptations recorded in `source-path-disposition.json`;
- all 57 DevControl test modules passing;
- byte-identical wheel and normalized sdist artifacts from two independent source copies;
- physical exclusion of `_compatibility_v1` from source, wheel and sdist;
- the 50-file Tier-A inventory and import-only v10 split contract are exact;
- repository, Windows, Android, desktop, DPAPI, Browser Use and workflow-coverage gates passing;
- `ci`, `codeql`, `agent3-diagnostics` and `agent3-full-diagnostics` successful on one unchanged exact head;
- zero unresolved review threads; and
- no claim of live publication, remote mutation, credentials, merge, release, deployment or activation authority.

Validation is not self-attested by this file. GitHub checks attached to the current PR head are authoritative. Any head change invalidates prior workflow evidence and the review record.
