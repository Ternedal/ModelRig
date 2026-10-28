# Android signing exposure: controlled migration decision

> Security planning only. Do not use this note as authorization to rotate keys, change application ID, sign an APK or publish a release.

## Confirmed audit observation

The repository audit dated 2026-10-16 reports a tracked Android keystore and plaintext signing properties in a public repository. Assume that signing material has been exposed. Do not repeat passwords, private keys or keystore bytes in tickets, CI logs or this document. Publication of credentials does not by itself establish that a malicious APK exists.

`SECURITY.md` D1 (2026-07-13) explicitly accepts this exposure for the documented solo, sideload-only deployment and requires reassessment if distribution, users or app-identity assumptions change. This plan does **not** supersede that owner decision or independently authorize key rotation.

## Proposed inventory and safeguards (non-disruptive)

- Restrict signing/release permissions and audit who can publish distribution artifacts.
- Inventory signing configuration in all Android build variants and workflows, including which identity signed currently installed APKs.
- Record package/application ID, signing certificate fingerprints, install/update channel, Android versions, device data migration requirements and whether any managed app-signing service owns the actual distribution key.
- Preserve existing working app and rollback options until the migration has been tested.
- Scan current and historical build artifacts and logs for accidental key distribution without copying secrets into reports.

## Migration options if D1's accepted-risk assumptions change (requires owner approval)

1. **Managed app signing:** verify whether an official key-upgrade mechanism is supported for the actual distribution channel, and distinguish upload key from app-signing key.
2. **Direct/self-signed APK distribution:** assess Android-supported signing certificate lineage and target device compatibility. Do not assume a newly signed APK can update an existing installation in place.
3. **No safe in-place rotation:** plan a new application ID or controlled reinstall with explicit export/import of user data and a tested recovery path. Obtain informed operator approval before any destructive device action.

## Acceptance before executing migration

- [ ] Exact existing certificate fingerprints and package IDs captured privately from installed app and signed release artifacts.
- [ ] Distribution channel and Android version matrix verified.
- [ ] Update/reinstall proof on a disposable test device, including data preservation and rollback.
- [ ] New key material generated and stored outside Git with least-privilege access, and secret scanning / CI release controls tested.
- [ ] Explicit operator sign-off, publication plan and incident-response procedure.
- [ ] Historical repository exposure evaluated; history rewrite is not mistaken for revocation.
- [ ] Release candidate re-qualified at exact SHA after approved changes.

## Governance boundary

The temporary v2.0.18 merge freeze was lifted on 2026-10-20. This document can be reviewed and merged without authorizing changes to signing files, installed APKs, application ID, worker 8099 or release tags. Any later key migration still requires an explicit risk-owner decision, test-device evidence, a verified upgrade/rollback path and fresh release qualification.

Reference: `docs/audits/MODELRIG_REPOSITORY_AUDIT_2026-10-16.md`.
