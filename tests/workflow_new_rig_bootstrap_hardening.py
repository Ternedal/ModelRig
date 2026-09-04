from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "bootstrap-new-rig.ps1").read_text(encoding="utf-8")


def between(start: str, end: str) -> str:
    left = SCRIPT.index(start)
    right = SCRIPT.index(end, left)
    return SCRIPT[left:right]


def test_release_provenance_is_release_and_workflow_bound() -> None:
    provenance = between("function Assert-ReleaseAttestation", "function Install-FileAtomically")
    for token in (
        "https://api.github.com/repos/Ternedal/ModelRig/attestations/sha256:",
        "https://slsa.dev/provenance/v1",
        "refs/tags/",
        "ternedal/modelrig",
        ".github/workflows/build-and-release.yml",
        "subject.digest.sha256",
    ):
        assert token in provenance, token


def test_checksum_manifest_is_attested_before_it_is_trusted() -> None:
    runtime = between("function Ensure-ModelRigRuntime", "function Test-Http")
    attest = runtime.index('Assert-ReleaseAttestation -Digest $sumDigest -Tag $tag -AssetName "SHA256SUMS.txt"')
    parse = runtime.index("$sums = Read-Sha256Sums -Path $sumPath")
    assert attest < parse


def test_active_runtime_uses_transactional_updater_not_direct_live_copy() -> None:
    runtime = between("function Ensure-ModelRigRuntime", "function Test-Http")
    assert 'Invoke-Native -FilePath $updaterPath -Arguments $updateArgs -Step "ModelRig transactional updater"' in runtime
    assert "refusing direct executable replacement" in runtime
    assert "refusing a partial direct repair" in runtime
    assert "Copy-Item -LiteralPath $download -Destination $dest -Force" not in runtime


def test_bodyrig_phase_always_reasserts_pinned_checkout() -> None:
    body = between("    if ($runBody) {", "    if ($runValidate) {")
    pin = 'Ensure-GitCheckout -Name "BodyRig" -Url "https://github.com/Ternedal/BodyRig.git" -Path $BodyRigSource -Ref $BodyRigRef -Pinned'
    setup = "Ensure-BodyRig -SourcePath $BodyRigSource"
    assert pin in body
    assert body.index(pin) < body.index(setup)
    assert 'if (-not (Test-Path -LiteralPath (Join-Path $BodyRigSource ".git")' not in body


if __name__ == "__main__":
    test_release_provenance_is_release_and_workflow_bound()
    test_checksum_manifest_is_attested_before_it_is_trusted()
    test_active_runtime_uses_transactional_updater_not_direct_live_copy()
    test_bodyrig_phase_always_reasserts_pinned_checkout()
    print("new-rig bootstrap hardening contract: OK")
