#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "milestone3_candidate_handoff.py"
LAUNCHER = ROOT / "BUILD_MILESTONE3_HANDOFF.cmd"
RUNBOOK = ROOT / "MILESTONE3_HANDOFF.md"

spec = importlib.util.spec_from_file_location("milestone3_candidate_handoff", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

source = SCRIPT.read_text(encoding="utf-8")
launcher = LAUNCHER.read_text(encoding="utf-8")
runbook = RUNBOOK.read_text(encoding="utf-8")
checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


check("schema is versioned", module.SCHEMA == "kaliv-milestone3-candidate-handoff/v1")
check(
    "authoritative branch is exact",
    module.BRANCH == "agent/milestone3-physical-candidate-v1",
)
check("version is exact", module.VERSION == "1.58.146")
check("candidate requires current branch", 'git("branch", "--show-current")' in source)
check("candidate requires clean tree", 'git("status", "--porcelain=v1")' in source)
check("version sites are checked", '"version_tool.py"' in source and '"check"' in source)
check("Android artifact is built", '"' + ':app:assembleDebug' + '"' in source)
check(
    "desktop uber jar is built",
    '"' + ':composeApp:packageUberJarForCurrentOS' + '"' in source,
)
check(
    "Git bundle is created and verified",
    '"bundle", "create"' in source and '"bundle", "verify"' in source,
)
check("artifacts are SHA-256 hashed", "sha256_file" in source and "SHA256SUMS.txt" in source)
check("artifact sizes are bounded", "MAX_ARTIFACT_BYTES" in source)
check("existing outputs are not overwritten", "handoff destination already exists" in source)
check("ZIP is verified after creation", "archive.testzip()" in source)
check("manifest denies physical evidence", '"physical_evidence_collected": False' in source)
check("manifest denies publication", '"published": False' in source)
check("manifest denies activation", '"production_activation": False' in source)
check("launcher calls only the local builder", "milestone3_candidate_handoff.py" in launcher)
check("runbook names the exact physical launcher", "START_MILESTONE3_PHYSICAL.cmd" in runbook)

for forbidden in (
    "urllib.request",
    "requests.",
    "http.client",
    "gh release",
    "git push",
    "git merge",
    "git tag",
    "Invoke-WebRequest",
    "curl ",
    "subprocess.Popen",
):
    check(f"no forbidden implementation: {forbidden}", forbidden not in source)

with tempfile.TemporaryDirectory(prefix="kaliv-m3-handoff-test-") as tmp:
    root = Path(tmp)
    bootstrap = root / "START_HERE.cmd"
    expected_sha = "a" * 40
    module.write_bootstrap(
        bootstrap,
        sha=expected_sha,
        bundle_name="candidate.bundle",
    )
    bootstrap_text = bootstrap.read_text(encoding="utf-8")
    check("bootstrap embeds exact SHA", expected_sha in bootstrap_text)
    check("bootstrap embeds exact branch", module.BRANCH in bootstrap_text)
    check("bootstrap verifies bundle", 'git bundle verify "%BUNDLE%"' in bootstrap_text)
    check("bootstrap clones local bundle", 'git clone "%BUNDLE%" "%DEST%"' in bootstrap_text)
    check("bootstrap checks exact HEAD", "git rev-parse HEAD" in bootstrap_text)
    check("bootstrap checks clean clone", "git status --porcelain" in bootstrap_text)
    check(
        "bootstrap starts unified physical operator",
        "call START_MILESTONE3_PHYSICAL.cmd" in bootstrap_text,
    )
    check("bootstrap refuses destination overwrite", "findes allerede" in bootstrap_text)

    artifact = root / "artifact.bin"
    artifact.write_bytes(b"candidate-artifact")
    metadata = module.checked_artifact(artifact, Path("artifact.bin"))
    check("artifact metadata records size", metadata["bytes"] == len(b"candidate-artifact"))
    check("artifact metadata records SHA-256", len(metadata["sha256"]) == 64)

    source_dir = root / "kit"
    source_dir.mkdir()
    (source_dir / "one.txt").write_text("one", encoding="utf-8")
    (source_dir / "two.txt").write_text("two", encoding="utf-8")
    archive = root / "kit.zip"
    module.zip_directory(source_dir, archive)
    with zipfile.ZipFile(archive, "r") as handle:
        names = sorted(handle.namelist())
        bad = handle.testzip()
    check("ZIP helper includes every file", names == ["kit/one.txt", "kit/two.txt"])
    check("ZIP helper produces valid archive", bad is None)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== MILESTONE 3 CANDIDATE HANDOFF: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
