"""Gate: PR-scoped CI jobs (android-compile, desktop-compile,
windows-worker-package) only skip their heavy steps when the PR diff lies
entirely outside the job's inputs, never on main, and fail open.

Run: PYTHONPATH=worker python3 tests/workflow_ci_pr_scope.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_pr_scope  # noqa: E402

passed = failed = 0


def check(message: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


# --- path matching -----------------------------------------------------------
check("a file under a scope directory is in scope",
      ci_pr_scope.path_in_scope("android/app/build.gradle.kts", ["android/"]))
check("a sibling directory with the same prefix is NOT in scope",
      not ci_pr_scope.path_in_scope("android-docs/x.md", ["android/"]))
check("an exact-file scope matches only that file",
      ci_pr_scope.path_in_scope("VERSION", ["VERSION"]) and not ci_pr_scope.path_in_scope("VERSION.md", ["VERSION"]))
check("the workflow itself is always in scope",
      ci_pr_scope.path_in_scope(".github/workflows/ci.yml", ["desktop/"]))
check("the decision script itself is always in scope",
      ci_pr_scope.path_in_scope("scripts/ci_pr_scope.py", ["desktop/"]))
check("a docs-only diff is out of scope for android",
      not ci_pr_scope.relevant(["HANDOFF.md", "docs/x.md"], ["android/"]))
check("one in-scope path makes the whole diff relevant",
      ci_pr_scope.relevant(["HANDOFF.md", "android/app/src/Main.kt"], ["android/"]))
check("an empty diff fails open (relevant)", ci_pr_scope.relevant([], ["android/"]))
check("a rename out of android counts via previous_filename semantics",
      ci_pr_scope.relevant(["docs/new.md", "android/old.kt"], ["android/"]))


# --- decide(): only pull_request consults the diff; everything else runs ----
calls: list[int] = []


def docs_only_loader() -> list[str]:
    calls.append(1)
    return ["HANDOFF.md"]


for event in ("push", "workflow_dispatch", "schedule", ""):
    verdict, reason = ci_pr_scope.decide(event, ["android/"], docs_only_loader)
    check(f"{event or 'empty'} event is relevant even with a docs-only diff available", verdict)
check("the diff loader is never called outside pull_request", calls == [])
verdict, reason = ci_pr_scope.decide("pull_request", ["android/"], docs_only_loader)
check("pull_request with a docs-only diff is NOT relevant for android", not verdict and calls == [1])
verdict, _ = ci_pr_scope.decide("pull_request", ["android/"], lambda: ["android/x.kt", "docs/a.md"])
check("pull_request touching android is relevant", verdict)


def boom() -> list[str]:
    raise RuntimeError("api down")


verdict, reason = ci_pr_scope.decide("pull_request", ["android/"], boom)
check("a failing diff loader fails open", verdict and "could not read" in reason)
verdict, reason = ci_pr_scope.decide("pull_request", ["android/"], None)
check("no loader (missing token/shas) fails open", verdict and "missing" in reason)

# --- the CLI: events other than pull_request are never narrowed -------------
def run_cli(env: dict[str, str], *scopes: str) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        full_env = {**os.environ, **env, "GITHUB_OUTPUT": str(out)}
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ci_pr_scope.py")]
            + [a for s in scopes for a in ("--scope", s)],
            env=full_env, capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        check(f"cli exits 0 for {env.get('GITHUB_EVENT_NAME')}", proc.returncode == 0)
        return proc.stdout.strip(), out.read_text() if out.exists() else ""


stdout, output = run_cli({"GITHUB_EVENT_NAME": "push"}, "android/")
check("push event is relevant", output.strip() == "relevant=true" and stdout.startswith("relevant=true"))
stdout, output = run_cli({"GITHUB_EVENT_NAME": "workflow_dispatch"}, "android/")
check("workflow_dispatch is relevant", output.strip() == "relevant=true")
stdout, output = run_cli(
    {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REPOSITORY": "", "PR_BASE_SHA": "", "PR_HEAD_SHA": "", "GITHUB_TOKEN": ""},
    "android/",
)
check("a pull_request without diff inputs fails open (relevant)", output.strip() == "relevant=true")
check("the fail-open reason is stated", "missing" in stdout)

# --- the workflow: every heavy step after the scope step is gated ----------
wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
for job, expected_scopes in {
    "android-compile": ["android/"],
    "desktop-compile": ["desktop/"],
    "windows-worker-package": ["worker/", "scripts/", "deploy/", "VERSION", "backend/"],
}.items():
    steps = wf["jobs"][job]["steps"]
    scope_steps = [s for s in steps if s.get("id") == "scope"]
    check(f"{job} has exactly one scope step", len(scope_steps) == 1)
    if not scope_steps:
        continue
    run = scope_steps[0].get("run", "")
    check(f"{job} scope step runs the decision script", "scripts/ci_pr_scope.py" in run)
    check(f"{job} scope covers {expected_scopes}",
          all(f"--scope {s}" in run for s in expected_scopes))
    after = steps[steps.index(scope_steps[0]) + 1:]
    check(f"{job} has heavy steps after the scope step", len(after) >= 1)
    check(f"{job}: every step after the scope step is gated on relevant == 'true'",
          all("steps.scope.outputs.relevant == 'true'" in str(s.get("if", "")) for s in after))
    before = steps[: steps.index(scope_steps[0])]
    check(f"{job}: the checkout and exact-sha assertion stay ungated",
          any("checkout" in str(s.get("uses", "")) for s in before)
          and not any("relevant" in str(s.get("if", "")) for s in before))

print(f"\n===== CI PR SCOPE: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
