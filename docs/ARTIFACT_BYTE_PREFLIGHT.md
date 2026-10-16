# Artifact byte preflight

This standalone, offline check compares already-retrieved evidence files with
independently obtained SHA-256 values. It checks all ten references in a complete
structural release manifest. Optional producer replay revalidates seven supported
producers with their existing qualifiers. The tool does not collect
physical evidence, establish provenance, approve a release, or activate services.

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
payload verification to a producer-specific verifier, such as the optional
replay described below.

## Optional producer replay

~~~powershell
python scripts/kaliv_release_artifact_preflight.py manifest.json attestations.json artifact-root --replay-producers
~~~

This explicit opt-in invokes the existing qualifier for each of these
seven gates and requires its recomputed release_evidence_ref to match the manifest
exactly:

| Gate | Existing qualifier |
| --- | --- |
| software_exact_green | kaliv_software_exact_green_qualifier.qualify |
| consciousness_live_lifecycle | consciousness_live_lifecycle_qualifier.qualify |
| voicerig_physical_acceptance | kaliv_voicerig_physical_qualifier.qualify |
| bodyrig_photoreal_likeness | kaliv_bodyrig_photoreal_qualifier.qualify |
| bodyrig_digital_twin_m6 | kaliv_bodyrig_digital_twin_m6_qualifier.qualify |
| end_to_end_latency | kaliv_end_to_end_latency_qualifier.qualify_receipts |
| repository_authority | kaliv_repository_authority_qualifier.qualify |

The six data-only artifact paths must point to each qualifier's original source evidence
or authority JSON, not its output verdict wrapper. The supplied file digest must
cover that source file. Files are parsed from the same bytes that were hashed;
the tool does not reopen a verified path to parse it. Source JSON is limited to
1 MiB, 64 nested containers and the same strict JSON rules as the input files.
BodyRig/VoiceRig validators receive the manifest's expected repository revision.
All qualifiers must reproduce the exact canonical reference and return bounded,
nonactivating verdicts. Changing data and recalculating only its byte hash does
not make it match the original producer evidence reference.

For end_to_end_latency, the artifact is the canonical
kaliv-system/end-to-end-latency-verdict/v2 JSON from the existing file qualifier.
Its source_receipts must declare exactly the three phases perception_received,
cognition_completed and outward_started, each with a relative path and SHA-256.
These three files must be present beneath the same artifact root. The preflight
applies its regular-file, path, link/reparse-point, identity, byte-hash and strict
JSON checks to every source. Each source is limited to 1 MiB.

The verified source bytes are copied to a private temporary directory with the
same relative names, then the unchanged file qualifier recomputes the verdict.
The entire declared verdict must equal that recomputed verdict under the
producer's canonical JSON encoding, including Boolean types. The final canonical
reference must also match the release manifest. Original source paths are not
reopened for semantic validation. Temporary snapshots are deleted on success
and failure; original artifact files remain read-only.

This reuses the existing checks for shared candidate, event/correlation ID,
runtime epoch, observer and monotonic phase ordering, completed cognition and
actual outward start. It retains the existing measurement safety cap and
threshold_applied=false; no new latency SLO or fresh measurement is claimed.
The replay record includes verified_source_receipts with phase, relative path,
observed SHA-256 and size. Legacy v1 latency verdicts are rejected.

visionrig_physical_perception, bodyrig_android_live_body and recovery_soak
are not replayed here. Their canonical validation requires further
source artifacts, checkout/runtime authority, or other specialized validation.
The optional producer_replay result always says PARTIAL and complete=false and
lists verified_gates, not_replayed_gates and bounded per-producer verdict records.
The top-level byte-only state and both false authority flags are preserved.
Without the option, byte-only behavior and the existing result shape are kept.

Replay validates only the checks implemented by these existing qualifiers.
Apart from the three local latency source receipts, it does not retrieve or
authenticate nested artifacts/evidence references. It does not contact
live services, rerun physical tests, verify an operator identity, or establish
that any observations actually occurred. A fabricated but internally consistent
payload can still pass. Trusted provenance and human approval remain required.
An activating flag inside a canonical BodyRig source artifact is not inherited
as ModelRig/Kaliv activation authority.

## Results

Exit code 0 means that all ten byte comparisons, plus the seven producer checks
if explicitly requested, passed. The JSON state is
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
Producer replay cases use the existing synthetic producer fixtures and real
qualifiers. They cover failed semantics with a matching file hash, stale/forged
canonical references, wrong revisions, strict source JSON, parsing the original
byte snapshot, the opt-in CLI and explicit reporting of unreplayed gates.
Latency replay cases additionally cover three-source digest binding, correlated
phases, modified report fields and Boolean types, missing sources, nested path
escape/symlinks, bounded strict source JSON, cleanup after success/failure, and
source paths changing after the original verified snapshot was read.
The tests use temporary files and do not contact rig services or create releases.

Linux execution and the path-based fallback can be checked locally. The reparse
attribute test simulates the Windows flag; it does not substitute for running on
Windows. Physical evidence and Windows filesystem acceptance remain separate.
