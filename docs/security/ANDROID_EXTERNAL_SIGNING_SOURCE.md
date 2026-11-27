# External Android signing source (migration preparation)

The public Git history contains the legacy Android signing identity. Treat it as compromised. This change does **not** rotate the identity, remove the leaked files, or make old releases safe.

## Local build

Supply both environment variables pointing to files **outside the repository**:

- `KALIV_SIGNING_PROPERTIES_FILE`: a Java properties file with `storePassword`, `keyPassword` and `keyAlias` (and optionally `storeFile`).
- `KALIV_SIGNING_KEYSTORE_FILE`: the absolute path to the matching keystore.

Both variables are mandatory together; a missing file fails configuration. The explicit keystore path overrides `storeFile` from the properties file. Keep these files private and never paste their contents into logs, PRs or issue comments.

For now, when **neither** variable is set, the build retains the legacy tracked signing source to avoid breaking the existing release process. That fallback is temporary and must be removed as part of #2269.

## CI and release gates still needed

The release workflow does not yet provision protected secrets. Do not publish a release based on this change alone. Before removing the fallback, require protected CI secret provisioning, a pinned signing certificate fingerprint, safe handling of untrusted PRs, and a physical update/migration test on the installed Android device. Moving the already exposed key into a secret store is **not** key rotation.

See #2269 for the full migration and acceptance gates.

## Release certificate pin activation checklist (PR #2272)

The release gate reads repository variable `KALIV_ANDROID_SIGNING_CERT_SHA256` and refuses to upload an APK when the variable is missing, malformed, or does not match the APK's sole signing certificate. The variable is a **public certificate fingerprint**, not a keystore password or private key. A repository variable is mutable; this check catches wrong-key releases but does **not** replace protected signing credentials or key rotation.

1. Obtain the **trusted** v2.0.18 APK from the published release and verify its provenance independently (do not substitute a random APK). On a trusted machine with Android SDK build-tools run:

   ```bash
   apksigner verify --print-certs modelrig-v2.0.18.apk
   ```

   Record the single `Signer #1 certificate SHA-256 digest` as 64 hexadecimal characters. Do not record passwords, keystore contents, or private-key material.

2. Verify that the currently installed Android app has the **same** signing certificate. An APK signed with a different certificate generally cannot update an existing installation under the same package ID without uninstalling; an uninstall may destroy local app data. Do not rotate the key without an explicit migration/update decision and physical device test.
3. Configure repository **Actions variable** `KALIV_ANDROID_SIGNING_CERT_SHA256` with the independently verified digest. Confirm the value through GitHub's repository settings (the workflow must fail closed when unset).
4. Test the candidate APK against the pin using `python3 scripts/verify_android_apk_certificate.py --apksigner /path/to/apksigner --apk /path/to/app-release.apk --expected-sha256 <verified-64-hex-digest>`. Verify that an intentionally wrong digest fails.
5. Only after the identity, variable, CI, and update-compatibility checks are verified, mark PR #2272 ready and merge. No tag or release should be created as part of this preparation.

**Security limitation:** The historical tracked keystore and credentials remain compromised. Pinning their certificate only confirms continuity of the signing identity; it does not make that identity exclusive to the legitimate publisher. Complete issue #2269 separately.
