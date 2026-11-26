#!/usr/bin/env python3
"""Behavioural contract for verify-repository-authority.ps1.

The wrapper is the operator's entry point for the repository_authority release
gate. It reads the live GitHub settings with ``gh``, hands them to
``scripts/repository_authority.py`` and prints the verdict. Its evaluator was
tested; the wrapper was not, and it failed on the configuration every Kaliv
repository actually has (classic branch protection, no rulesets).

The test runs the real wrapper in PowerShell against a fake ``gh`` in a
throw-away Git checkout on branch ``main``.

Run: python3 tests/workflow_repository_authority_wrapper.py
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import repository_authority as authority  # noqa: E402

PWSH = shutil.which("pwsh")
assert PWSH, "PowerShell 7 (pwsh) is required for this test"

passed = 0


def check(condition: bool, label: str) -> None:
    global passed
    assert condition, label
    passed += 1


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c", "user.name=contract",
            "-c", "user.email=contract@example.invalid",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


# A fake GitHub CLI. It answers from JSON files in FAKE_GH_DIR and fails, as
# the real one does, for an endpoint that has no file.
FAKE_GH = r'''
import os, sys
from pathlib import Path

root = Path(os.environ["FAKE_GH_DIR"])
args = sys.argv[1:]
if args[:1] == ["auth"]:
    sys.exit(0)
if args[:1] != ["api"] or len(args) < 2:
    sys.exit(1)
path = args[1]
if path.endswith("/branches/main/protection"):
    name = "protection.json"
elif path.endswith("/branches/main"):
    name = "branch.json"
elif path.endswith("/rulesets?includes_parents=true"):
    name = "rulesets.json"
elif "/rulesets/" in path:
    name = "ruleset-" + path.rsplit("/", 1)[1] + ".json"
else:
    print("unexpected endpoint " + path, file=sys.stderr)
    sys.exit(1)
target = root / name
if not target.is_file():
    print('{"message":"Not Found"}', file=sys.stderr)
    sys.exit(1)
sys.stdout.write(target.read_text(encoding="utf-8"))
'''


def install_fake_gh(directory: Path) -> None:
    script = directory / "fake_gh.py"
    script.write_text(FAKE_GH, encoding="utf-8")
    if os.name == "nt":
        (directory / "gh.cmd").write_text(
            f'@"{sys.executable}" "{script}" %*\r\n', encoding="ascii"
        )
    else:
        launcher = directory / "gh"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="ascii")
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)


def classic_protection() -> dict:
    """Classic branch protection that satisfies the evaluator."""
    return {
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "required_status_checks": {
            "strict": True,
            "checks": [
                {"context": name, "app_id": authority.REQUIRED_STATUS_CHECK_APP_ID}
                for name in authority.REQUIRED_STATUS_CHECKS
            ],
        },
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
    }


def inert_ruleset(number: int) -> dict:
    return {
        "id": number,
        "name": f"inert-{number}",
        "target": "branch",
        "enforcement": "disabled",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [],
    }


def passing_ruleset(number: int) -> dict:
    """An active ruleset on main that satisfies the evaluator on its own."""
    return {
        "id": number,
        "name": f"main-authority-{number}",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {"required_review_thread_resolution": True}},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {"context": name, "integration_id": authority.REQUIRED_STATUS_CHECK_APP_ID}
                        for name in authority.REQUIRED_STATUS_CHECKS
                    ],
                },
            },
        ],
    }


class Checkout:
    """A clean checkout on ``main`` holding the wrapper and its evaluator."""

    def __init__(self, base: Path) -> None:
        self.root = base / "checkout"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(ROOT / "verify-repository-authority.ps1", self.root)
        shutil.copy(ROOT / "scripts" / "repository_authority.py", self.root / "scripts")
        git(self.root, "init", "--quiet", "--initial-branch=main")
        git(self.root, "add", ".")
        git(self.root, "commit", "--quiet", "-m", "wrapper contract fixture")
        self.head = git(self.root, "rev-parse", "HEAD")
        self.tools = base / "tools"
        self.tools.mkdir()
        install_fake_gh(self.tools)
        self.github = base / "github"
        self.github.mkdir()

    def github_state(
        self,
        *,
        head: str | None = None,
        protection: dict | None,
        rulesets: list[dict] | None,
    ) -> None:
        for stale in self.github.iterdir():
            stale.unlink()
        branch = {"name": "main", "protected": True, "commit": {"sha": head or self.head}}
        (self.github / "branch.json").write_text(json.dumps(branch), encoding="utf-8")
        if protection is not None:
            (self.github / "protection.json").write_text(json.dumps(protection), encoding="utf-8")
        if rulesets is not None:
            summaries = [{"id": item["id"], "name": item["name"]} for item in rulesets]
            (self.github / "rulesets.json").write_text(json.dumps(summaries), encoding="utf-8")
            for item in rulesets:
                (self.github / f"ruleset-{item['id']}.json").write_text(
                    json.dumps(item), encoding="utf-8"
                )

    def run(self, *extra: str) -> subprocess.CompletedProcess:
        environment = dict(os.environ)
        environment["PATH"] = str(self.tools) + os.pathsep + environment.get("PATH", "")
        environment["FAKE_GH_DIR"] = str(self.github)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [
                PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                str(self.root / "verify-repository-authority.ps1"),
                "-Python", sys.executable,
                *extra,
            ],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            env=environment,
            timeout=300,
        )

    def verdict(self) -> tuple[int, dict]:
        completed = self.run("-Json")
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, (
            f"-Json must print exactly one line; rc={completed.returncode}\n"
            f"stdout={completed.stdout[-600:]}\nstderr={completed.stderr[-600:]}"
        )
        return completed.returncode, json.loads(lines[0])


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="repository-authority-wrapper-"))
    try:
        checkout = Checkout(base)

        # What every Kaliv repository has today: classic protection, no rulesets.
        checkout.github_state(protection=classic_protection(), rulesets=[])
        code, verdict = checkout.verdict()
        check(code == 0 and verdict["passed"] is True, "classic protection with no rulesets passes")
        check(verdict["head_revision"] == checkout.head, "the verdict is bound to the checkout's HEAD")
        check(verdict["authority_mode"] == "classic", "and names the mode that passed")
        check(verdict["format"] == authority.FORMAT, "and is the evaluator's own format")
        check(verdict["production_activation"] is False, "and activates nothing")

        # A single ruleset that carries the authority on its own, with no
        # classic protection. A PowerShell pipeline unrolls a one-element array
        # into a bare object, and the evaluator then sees no ruleset at all.
        checkout.github_state(protection=None, rulesets=[passing_ruleset(100)])
        code, verdict = checkout.verdict()
        check(code == 0 and verdict["passed"] is True, "one ruleset reaches the evaluator as a list of one")
        check(verdict["authority_mode"] == "ruleset", "and is the mode that passed")
        check(verdict["rulesets"]["applicable_ruleset_ids"] == [100], "with its own id")
        checkout.github_state(protection=None, rulesets=[inert_ruleset(100), passing_ruleset(101)])
        code, verdict = checkout.verdict()
        check(code == 0 and verdict["rulesets"]["applicable_ruleset_ids"] == [101],
              "two rulesets reach it as a list of two; only the active one applies")
        for count in (1, 2):
            rulesets = [inert_ruleset(100 + index) for index in range(count)]
            checkout.github_state(protection=classic_protection(), rulesets=rulesets)
            code, verdict = checkout.verdict()
            check(code == 0 and verdict["authority_mode"] == "classic",
                  f"{count} inert ruleset(s) beside classic protection")
        # The rulesets endpoint is unavailable (no rights): still a verdict.
        checkout.github_state(protection=classic_protection(), rulesets=None)
        code, verdict = checkout.verdict()
        check(code == 0 and verdict["passed"] is True, "an unreadable rulesets endpoint is not a crash")

        # A real deficit is a verdict with exit 2, not an exception.
        weak = classic_protection()
        weak["enforce_admins"] = {"enabled": False}
        checkout.github_state(protection=weak, rulesets=[])
        code, verdict = checkout.verdict()
        check(code == 2 and verdict["passed"] is False, "administrator bypass fails with exit 2")
        check(verdict["authority_mode"] is None, "no mode is reported as passing")
        check(
            any("administrators can bypass" in error for error in verdict["classic"]["errors"]),
            "and the classic evaluation names the deficit",
        )
        checkout.github_state(protection=None, rulesets=[])
        code, verdict = checkout.verdict()
        check(code == 2 and verdict["passed"] is False, "no protection at all fails with exit 2")

        # GitHub's main is somewhere else than the checkout.
        checkout.github_state(head="f" * 40, protection=classic_protection(), rulesets=[])
        code, verdict = checkout.verdict()
        check(code == 2 and verdict["passed"] is False, "a main head other than the checkout fails")
        check(
            any("does not match the expected checkout revision" in error for error in verdict["errors"]),
            "and says the head does not match",
        )

        # The human-readable form.
        checkout.github_state(protection=classic_protection(), rulesets=[])
        completed = checkout.run()
        check(completed.returncode == 0, f"without -Json the wrapper exits 0: {completed.stderr[-300:]}")
        check("ModelRig repository authority: PASS" in completed.stdout, "and prints PASS")
        check(checkout.head in completed.stdout, "with the head it verified")

        # The checkout must be exactly what main is.
        (checkout.root / "stray.txt").write_text("x\n", encoding="utf-8")
        completed = checkout.run("-Json")
        check(completed.returncode != 0, "a dirty checkout is refused")
        check("exact clean main checkout" in completed.stderr + completed.stdout, "with the reason")
        (checkout.root / "stray.txt").unlink()
        git(checkout.root, "checkout", "--quiet", "-b", "feature")
        completed = checkout.run("-Json")
        check(completed.returncode != 0, "a branch other than main is refused")
        check("must run from branch main" in completed.stderr + completed.stdout, "with the reason")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print(f"Repository authority wrapper contract: {passed} checks PASS")


if __name__ == "__main__":
    main()
