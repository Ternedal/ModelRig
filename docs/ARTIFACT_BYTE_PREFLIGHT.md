# Artifact byte preflight

This standalone, offline check compares already-retrieved evidence files with
independently obtained SHA-256 values. It checks all ten references in a complete
structural release manifest. It does not collect physical evidence, replay
producer semantics, establish provenance, approve a release, or activate services.

It is intentionally not integrated into release workflows. Development of this
tool must leave the active release candidate, tags, assets and workers unchanged.

## Invocation

Run from a checkout containing this script and the existing release gate:

~~~powershell
python scripts/kaliv_release_artifact_preflight.py manifest.json attestations.json artifact-root
~~~

The manifest must satisfy the real kaliv_system_release_gate evaluator, including
canonical references and all four pinned repository revisions. The check never
substitutes a mocked structural verdict.

The attestation JSON object must have exactly the ten required gate names as
keys. Each value must contain exactly these fields:

| Field | Meaning |
| --- | --- |
| reference | Exact canonical evidence reference in that gate's manifest entry. |
| path | Relative artifact path using forward slashes, such as vision/physical.json. |
| sha256 | Independently obtained lowercase 64-hex SHA-256 of the entire downloaded file. |
| repository | Repository whose tested revision the gate reference identifies; see below. |
| git_sha | That repository's lowercase 40-hex revision from the release manifest. |

The repository identifies the tested revision. It does not identify the server
or repository from which a copy of the file happened to be downloaded.

| Gate | Revision binding |
| --- | --- |
| software_exact_green | Ternedal/ModelRig; the canonical reference also binds all four repositories. |
| consciousness_live_lifecycle | Ternedal/ModelRig |
| visionrig_physical_perception | Ternedal/VisionRig |
| voicerig_physical_acceptance | Ternedal/VoiceRig |
| bodyrig_photoreal_likeness | Ternedal/BodyRig |
| bodyrig_digital_twin_m6 | Ternedal/BodyRig |
| bodyrig_android_live_body | Ternedal/ModelRig |
| end_to_end_latency | Ternedal/ModelRig |
| recovery_soak | Ternedal/ModelRig |
| repository_authority | Ternedal/ModelRig; the canonical reference also binds all four repositories. |

A valid pin for another repository is rejected. The existing structural evaluator
remains responsible for reference-to-revision binding, including its existing
ModelRig ancestry/tree equivalence rules. The attestation pins the manifest's
tested release revision; it does not assert that the artifact was produced there.

A reference's final digest can cover a producer-specific canonical payload.
That digest need not equal the hash of the serialized artifact file. This tool
checks the separate sha256 field against the actual bytes and leaves canonical
payload verification to a future producer-specific verifier.

## Results

Exit code 0 means only that all ten byte comparisons passed. The JSON state is
BYTE_HASHES_VERIFIED_ONLY. Both release_ready and production_activation remain
false. The result includes release_id, all pinned_repositories, checked_gates,
and one verified_artifacts record per gate with its reference, relative path,
repository, Git SHA, byte hash and observed size.

Malformed inputs, incomplete coverage, wrong repositories/revisions/references,
unsafe paths, oversized files and hash mismatches produce exit code 2 and an
INVALID JSON object. Both authority flags are false on errors as well. No
partial verification result is emitted as success.

Each input JSON file is limited to 1 MiB and 64 nested containers. Inputs must be
UTF-8 JSON objects with unique field names; NaN and infinities are rejected.
Each artifact is a regular file of at most 16 MiB, hashed in bounded chunks.
Absolute and drive-relative paths, parent traversal, alternate streams, Windows
device names, ambiguous trailing spaces/dots and platform-specific separators
are rejected. Symlinks and Windows reparse points are rejected in every artifact
path component. Ordinary replacement or mutation during hashing is rejected.

## Filesystem assumptions and authority limits

Use an operator-owned, quiescent local artifact directory. On platforms with
descriptor-relative directory opens and O_NOFOLLOW, directory traversal is
anchored to open descriptors so replacing a parent with a symlink cannot redirect
the file open. Other platforms, including Windows, use before/after path and
descriptor checks; that fallback is not a security boundary against a concurrently
hostile filesystem. The caller must control the directory and its ancestors.

A user can supply a fabricated file together with its matching digest. A byte
match therefore does not establish authenticity or prove the physical test ran.
Trusted retrieval/provenance, producer-specific semantic replay, and human
approval remain required. The output must not be used as release authorization.

## Local regression verification

~~~powershell
python tests/worker_kaliv_release_artifact_preflight.py
python tests/worker_kaliv_release_artifact_negative.py
python tests/worker_kaliv_release_manifest_assembler.py
python tests/support/kaliv_system_release_gate_contract.py
~~~

The two artifact suites exercise complete synthetic manifests through the real
assembler and structural evaluator, including subprocess CLI success/error
paths, every gate's wrong-repository rejection, tampered bytes, metadata and path
validation, file size/growth, replacement, symlinks, and read-only operation.
The tests use temporary files and do not contact rig services or create releases.

Linux execution and the path-based fallback can be checked locally. The reparse
attribute test simulates the Windows flag; it does not substitute for running on
Windows. Physical evidence and Windows filesystem acceptance remain separate.
