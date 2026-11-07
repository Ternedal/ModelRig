#!/usr/bin/env python3
"""Decide whether a CI job's inputs are touched by the pull request under test.

A job whose inputs live entirely under a few paths (android/, desktop/, the
worker package) cannot produce a different result on a pull request that does
not touch those paths: under required-up-to-date branch protection the PR's
tree for those paths is identical to main's, which the push run on main has
already compiled. Such jobs keep reporting their (required) status, but skip
the expensive steps when the PR diff lies entirely outside their scope.

Only pull_request events are ever narrowed. Pushes to main, tags and manual
dispatches always count as relevant, so main keeps complete evidence.

Usage (from a workflow step):
    python scripts/ci_pr_scope.py --scope android/ --scope .github/workflows/ci.yml

Reads GITHUB_EVENT_NAME, GITHUB_REPOSITORY, GITHUB_TOKEN and the PR base/head
shas from PR_BASE_SHA / PR_HEAD_SHA; writes `relevant=true|false` to
GITHUB_OUTPUT (and stdout). Any failure to determine the diff is relevant=true:
the script fails open towards running the job, never towards skipping it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections.abc import Callable, Iterable


# Paths that make EVERY narrowed job relevant, whatever its own scope: the
# workflow and this decision logic.
ALWAYS_RELEVANT = (".github/workflows/", "scripts/ci_pr_scope.py")


def path_in_scope(path: str, scopes: Iterable[str]) -> bool:
    """True when `path` is the scope entry itself or lies under a scope directory."""
    for scope in tuple(scopes) + ALWAYS_RELEVANT:
        if scope.endswith("/"):
            if path.startswith(scope):
                return True
        elif path == scope:
            return True
    return False


def relevant(changed_paths: Iterable[str], scopes: Iterable[str]) -> bool:
    """A PR is relevant to a job when ANY changed path is in the job's scope.

    An empty diff is relevant (fail open)."""
    paths = list(changed_paths)
    if not paths:
        return True
    return any(path_in_scope(p, scopes) for p in paths)


def _pr_changed_paths(repo: str, base: str, head: str, token: str) -> list[str]:
    url = f"https://api.github.com/repos/{repo}/compare/{base}...{head}?per_page=100"
    paths: list[str] = []
    page = 1
    while True:
        req = urllib.request.Request(
            f"{url}&page={page}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - api.github.com
            data = json.load(resp)
        files = data.get("files") or []
        for entry in files:
            name = entry.get("filename")
            if name:
                paths.append(name)
            previous = entry.get("previous_filename")
            if previous:
                paths.append(previous)
        if len(files) < 100:
            break
        page += 1
    return paths


def decide(event: str, scopes: Iterable[str],
           load_changed_paths: Callable[[], list[str]] | None) -> tuple[bool, str]:
    """The verdict for one job: (relevant, reason).

    Only a pull_request event consults the diff; every other event is relevant
    without the loader being called. A missing loader or a loader failure is
    relevant (fail open)."""
    if event != "pull_request":
        return True, f"event {event or '?'} is never narrowed"
    if load_changed_paths is None:
        return True, "missing repo/base/head/token; running"
    try:
        changed = load_changed_paths()
    except Exception as exc:  # noqa: BLE001 - fail open, say why
        return True, f"could not read the PR diff ({type(exc).__name__}); running"
    verdict = relevant(changed, scopes)
    return verdict, (f"{len(changed)} changed path(s); "
                     + ("at least one in scope" if verdict else "none in scope"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--scope", action="append", required=True,
                        help="path prefix (ending in /) or exact file that is an input of the job")
    args = parser.parse_args(argv)

    event = os.environ.get("GITHUB_EVENT_NAME", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    base = os.environ.get("PR_BASE_SHA", "")
    head = os.environ.get("PR_HEAD_SHA", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    loader = None
    if repo and base and head and token:
        loader = lambda: _pr_changed_paths(repo, base, head, token)  # noqa: E731
    verdict, reason = decide(event, args.scope, loader)

    line = f"relevant={'true' if verdict else 'false'}"
    print(f"{line} ({reason}; scope={' '.join(args.scope)})")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
