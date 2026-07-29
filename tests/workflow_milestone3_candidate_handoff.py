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
    "authoritative candidate branch is exact",
    module.CANDIDATE_BRANCH == "agent/milestone3-physical-candidate-v1",
)
check(
    "review-only builder branch is separate",
    module.BUILDER_BRANCH == "agent/milestone3-candidate-handoff-v1",
)
check("legacy BRANCH alias still points to candidate", module.BRANCH == module.CANDIDATE_BRANCH)
check("version is exact", module.VERSION == "1.58.146")
check("builder requires current helper branch", 'git("branch", "--show-current")' in source)
check("builder requires clean tree", 'git("status", "--porcelain=v1")' in source)
check(
    "candidate SHA comes from authoritative ref",
    'git("rev-parse", CANDIDATE_BRANCH)' in source,
)
check(
    "builder must descend from candidate",
    '"merge-base", "--is-ancestor"' in source,
)
check(
    "helper diff is allowlisted",
    "_ALLOWED_HELPER_DIFF" in source and "changes candidate runtime files" in source,
)
check(
    "candidate version is read from candidate ref",
    'git("show", f"{CANDIDATE_BRANCH}:VERSION")' in source,
)
check(
    "candidate is built in detached worktree",
    '"worktree", "add", "--detach"' in source
    and "build_artifacts(candidate_root)" in source,
)
check(
    "detached worktree SHA is rechecked",
    'git("rev-parse", "HEAD", cwd=candidate_root)' in source,
)
check(
    "detached worktree is removed",
    '"worktree", "remove", "--force"' in source,
)
check("Android artifact is built", '":app:assembleDebug"' in source)
check(
    "desktop uber jar is built",
    '":composeApp:packageUberJarForCurrentOS"' in source,
)
check(
    "Git bundle is created and verified",
    '"bundle", "create"' in source and '"bundle", "verify"' in source,
)
check("artifacts are SHA-256 hashed", "sha256_file" in source and "SHA256SUMS.txt" in source)
check("artifact sizes are bounded", "MAX_ARTIFACT_BYTES" in source)
check("existing outputs are not overwritten", "handoff destination already exists" in source)
check("ZIP is verified after creation", "archive.testzip()" in source)
check("manifest separates candidate and builder", '"builder": identity["builder"]' in source)
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
    check("bootstrap embeds exact candidate branch", module.CANDIDATE_BRANCH in bootstrap_text)
    check("bootstrap verifies bundle", 'git bundle verify "%BUNDLE_ABS%"' in bootstrap_text)
    check("bootstrap initializes local repository", 'git init "%DEST%"' in bootstrap_text)
    check(
        "bootstrap fetches exact branch from local bundle",
        'git fetch "%BUNDLE_ABS%" "%EXPECTED_BRANCH%:%EXPECTED_BRANCH%"'
        in bootstrap_text,
    )
    init_index = bootstrap_text.index('git init "%DEST%"')
    verify_index = bootstrap_text.index('git bundle verify "%BUNDLE_ABS%"')
    fetch_index = bootstrap_text.index(
        'git fetch "%BUNDLE_ABS%" "%EXPECTED_BRANCH%:%EXPECTED_BRANCH%"'
    )
    check(
        "bootstrap initializes before verifying and fetching bundle",
        init_index < verify_index < fetch_index,
    )
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
