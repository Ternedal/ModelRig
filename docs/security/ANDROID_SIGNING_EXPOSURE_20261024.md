# Android signing exposure: containment and migration decision

Status: **OPEN / potentially compromised** (2026-10-24). Tracking: #2267.

## Verified repository facts

The public `main` tree contains `android/signing/modelrig.keystore` and `android/signing/keystore.properties`. The latter contains populated signing password fields. `android/app/build.gradle.kts` reads that properties file and applies the same signing configuration to debug and release builds. The existing Gradle comment calls the repository private, but GitHub reports it as public.

**Do not print, paste, or attach any signing passwords or private key material.** The presence of the key and passwords in a public Git tree means this identity cannot be treated as secret, regardless of future deletion. The new ignore rules only prevent accidental *new* additions; they do not remove tracked files or rewrite Git history.

## Immediate operational safeguards

1. Restrict release publication permissions and inspect who can upload or replace Android APK assets. Verify provenance of already published APKs using a trusted independently retained digest/signing certificate fingerprint.
2. Record the signing certificate fingerprint and currently installed app package/version from a trusted device **without exposing the private key**. Preserve a safe copy of the existing installation and APK for migration testing.
3. Confirm distribution model (sideloaded APK versus Play App Signing) and Android platform support before choosing the key transition. A new signing key normally cannot update an existing sideloaded package in place without an applicable Android-supported key-rotation lineage; do not assume that lineage is supported for all installed versions.
4. Prepare and physically test the chosen transition: verified in-place update where supported, otherwise explicit backup/export, uninstall/reinstall and re-pairing. Document data-loss and rollback consequences. Do not ship a new key silently.
5. Move future signing credentials to a restricted secret store or protected signing service; provision them only during approved release jobs. Never log or publish them.
6. Add a CI check that fails on tracked keystore/private signing files and likely signing credentials. **Initially run in audit-only mode** until existing tracked material is migrated, so the guard does not masquerade as remediation or unexpectedly block unrelated changes.
7. Determine the exposure window and assess whether previously distributed APKs or update channels require user notification. Treat the old key as compromised for trust decisions.

## Release gate

No Android signing identity change is accepted without: approved migration decision, test on the real installed app, verified update path, and an operator-reviewed rollback/data preservation plan. A passing Gradle build is insufficient.

## Scope of this PR

Only preventive `.gitignore` rules and this incident playbook. **No private keys are read into output, removed, rotated, or replaced here.** No changes to build/release behavior or the running rig.
