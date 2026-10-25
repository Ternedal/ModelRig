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
