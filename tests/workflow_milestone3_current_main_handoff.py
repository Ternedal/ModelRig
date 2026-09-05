#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import zipfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "milestone3_current_main_handoff.py"
CORE = ROOT / "scripts" / "milestone3_candidate_handoff_core.py"
LAUNCHER = ROOT / "BUILD_MILESTONE3_CURRENT_MAIN_HANDOFF.cmd"
RUNBOOK = ROOT / "MILESTONE3_CURRENT_MAIN_HANDOFF.md"

spec = importlib.util.spec_from_file_location("milestone3_current_main_handoff", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

source = code_of(SCRIPT)
core_source = code_of(CORE)
launcher = code_of(LAUNCHER)
runbook = code_of(RUNBOOK)
checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


check("schema is current-main versioned", module.SCHEMA == "kaliv-milestone3-current-main-handoff/v1")
check(
    "authoritative candidate branch is exact",
    module.CANDIDATE_BRANCH == "agent/milestone3-current-main-v2",
)
check(
    "review-only builder branch is separate",
    module.BUILDER_BRANCH == "agent/milestone3-current-main-handoff-v2",
)
check("BRANCH alias points to candidate", module.BRANCH == module.CANDIDATE_BRANCH)
check("version is exact", module.VERSION == "1.58.147")
check(
    "offline bootstrap is rebound to current-main launcher",
    module.PHYSICAL_LAUNCHER == "START_MILESTONE3_CURRENT_MAIN.cmd",
)
check(
    "core received exact wrapper binding before entrypoints are exposed",
    module.core.CANDIDATE_BRANCH == module.CANDIDATE_BRANCH
    and module.core.BUILDER_BRANCH == module.BUILDER_BRANCH
    and module.core.VERSION == module.VERSION
    and module.core.SCHEMA == module.SCHEMA,
)
check(
    "helper diff contains only current-main handoff files",
    module.core._ALLOWED_HELPER_DIFF == module._ALLOWED_HELPER_DIFF
    and module._ALLOWED_HELPER_DIFF
    == {
        "BUILD_MILESTONE3_CURRENT_MAIN_HANDOFF.cmd",
        "CURRENT_STATE.md",
        "MILESTONE3_CURRENT_MAIN_HANDOFF.md",
        "scripts/milestone3_candidate_handoff_core.py",
        "scripts/milestone3_current_main_handoff.py",
        "tests/workflow_milestone3_current_main_handoff.py",
    },
)

check("builder requires current helper branch", 'git("branch", "--show-current")' in core_source)
check("builder requires clean tree", 'git("status", "--porcelain=v1")' in core_source)
check(
    "candidate SHA comes from authoritative ref",
    'git("rev-parse", CANDIDATE_BRANCH)' in core_source,
)
check(
    "builder must descend from candidate",
    '"merge-base", "--is-ancestor"' in core_source,
)
check(
    "candidate version is read from candidate ref",
    'git("show", f"{CANDIDATE_BRANCH}:VERSION")' in core_source,
)
check(
    "candidate is built in detached worktree",
    '"worktree", "add", "--detach"' in core_source
    and "build_artifacts(candidate_root)" in core_source,
)
check(
    "detached worktree SHA is rechecked and removed",
    'git("rev-parse", "HEAD", cwd=candidate_root)' in core_source
    and '"worktree", "remove", "--force"' in core_source,
)
check("Android artifact is built", '":app:assembleDebug"' in core_source)
check(
    "desktop uber jar is built",
    '":composeApp:packageUberJarForCurrentOS"' in core_source,
)
check(
    "Git bundle is created and verified",
    '"bundle", "create"' in core_source and '"bundle", "verify"' in core_source,
)
check("artifacts are hashed and bounded", "sha256_file" in core_source and "MAX_ARTIFACT_BYTES" in core_source)
check("existing outputs are never overwritten", "handoff destination already exists" in core_source)
check("ZIP is verified after creation", "archive.testzip()" in core_source)
check("manifest separates candidate and builder", '"builder": identity["builder"]' in core_source)
check("manifest denies physical evidence", '"physical_evidence_collected": False' in core_source)
check("manifest denies publication", '"published": False' in core_source)
check("manifest denies activation", '"production_activation": False' in core_source)
check("root launcher calls only current-main wrapper", "milestone3_current_main_handoff.py" in launcher)
check("runbook names exact physical launcher", module.PHYSICAL_LAUNCHER in runbook)

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
    check(
        f"no forbidden implementation: {forbidden}",
        forbidden not in core_source and forbidden not in source,
    )

with tempfile.TemporaryDirectory(prefix="kaliv-m3-current-handoff-") as tmp:
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
        'git fetch "%BUNDLE_ABS%" "%EXPECTED_BRANCH%:%EXPECTED_BRANCH%"' in bootstrap_text,
    )
    init_index = bootstrap_text.index('git init "%DEST%"')
    verify_index = bootstrap_text.index('git bundle verify "%BUNDLE_ABS%"')
    fetch_index = bootstrap_text.index(
        'git fetch "%BUNDLE_ABS%" "%EXPECTED_BRANCH%:%EXPECTED_BRANCH%"'
    )
    check("bootstrap order is init then verify then fetch", init_index < verify_index < fetch_index)
    check("bootstrap checks exact HEAD", "git rev-parse HEAD" in bootstrap_text)
    check("bootstrap checks clean clone", "git status --porcelain" in bootstrap_text)
    check("bootstrap starts current-main physical operator", f"call {module.PHYSICAL_LAUNCHER}" in bootstrap_text)
    check("bootstrap contains no obsolete physical launcher", "START_MILESTONE3_PHYSICAL.cmd" not in bootstrap_text)
    check("bootstrap refuses destination overwrite", "findes allerede" in bootstrap_text)

    readme = root / "README.txt"
    module.write_readme(
        readme,
        identity={
            "version": module.VERSION,
            "branch": module.CANDIDATE_BRANCH,
            "git_sha": expected_sha,
            "git_tree_sha": "b" * 40,
        },
    )
    readme_text = readme.read_text(encoding="utf-8")
    check("README starts current-main launcher", module.PHYSICAL_LAUNCHER in readme_text)
    check("README contains no obsolete physical launcher", "START_MILESTONE3_PHYSICAL.cmd" not in readme_text)

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

    # Real, no-network Git bundle round trip.
    mini = root / "mini-source"
    mini.mkdir()
    module.run(["git", "init"], cwd=mini)
    module.run(["git", "config", "user.name", "Kaliv CI"], cwd=mini)
    module.run(["git", "config", "user.email", "kaliv-ci@example.invalid"], cwd=mini)
    (mini / "candidate.txt").write_text("exact candidate\n", encoding="utf-8")
    module.run(["git", "add", "candidate.txt"], cwd=mini)
    module.run(["git", "commit", "-m", "candidate"], cwd=mini)
    module.run(["git", "branch", "candidate"], cwd=mini)
    candidate_sha = module.run(
        ["git", "rev-parse", "candidate"], cwd=mini, capture=True
    ).stdout.strip()

    bundle = root / "candidate.bundle"
    module.run(["git", "bundle", "create", str(bundle), "candidate"], cwd=mini)
    destination = root / "mini-destination"
    destination.mkdir()
    module.run(["git", "init"], cwd=destination)
    module.run(["git", "bundle", "verify", str(bundle)], cwd=destination, capture=True)
    module.run(
        ["git", "fetch", str(bundle), "candidate:refs/heads/candidate"],
        cwd=destination,
    )
    fetched_sha = module.run(
        ["git", "rev-parse", "refs/heads/candidate"],
        cwd=destination,
        capture=True,
    ).stdout.strip()
    check("real offline bundle round trip preserves exact SHA", fetched_sha == candidate_sha)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== MILESTONE 3 CURRENT-MAIN HANDOFF: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
