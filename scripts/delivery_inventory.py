#!/usr/bin/env python3
"""Read-only GitHub delivery inventory. No branch/PR mutations.

Usage: GH_TOKEN=... python scripts/delivery_inventory.py > delivery-inventory.json
Uses only Python standard library. Requires read access to private repositories.
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REPOS = [
    "ModelRig", "BodyRig", "VoiceRig", "VisionRig",
    "KalivHub-Receiver", "KalivHub", "Kaliv", "KalivNexus",
]
OWNER = os.environ.get("KALIV_GITHUB_OWNER", "Ternedal")
API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def fetch(path):
    req = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "kaliv-delivery-inventory",
            **({"Authorization": "Bearer " + TOKEN} if TOKEN else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response), response.headers


def paginate(path):
    result = []
    while path:
        data, headers = fetch(path)
        if not isinstance(data, list):
            raise ValueError("Expected a GitHub list response")
        result.extend(data)
        next_url = None
        for part in headers.get("Link", "").split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
        if next_url and not next_url.startswith(API + "/"):
            raise ValueError("Unexpected pagination URL")
        path = next_url[len(API):] if next_url else None
    return result


def inspect(repo):
    prefix = "/repos/" + urllib.parse.quote(OWNER) + "/" + urllib.parse.quote(repo)
    meta, _ = fetch(prefix)
    prs = paginate(prefix + "/pulls?state=open&per_page=100")
    branches = paginate(prefix + "/branches?per_page=100")
    ready = [p for p in prs if not p["draft"]]
    return {
        "repository": meta["full_name"],
        "default_branch": meta["default_branch"],
        "open_prs": len(prs),
        "draft_prs": sum(bool(p["draft"]) for p in prs),
        "ready_prs": len(ready),
        "branch_count": len(branches),
        "ready_prs_detail": [
            {"number": p["number"], "title": p["title"], "url": p["html_url"]}
            for p in ready
        ],
        "notes": [
            "Branch count includes merged branches; no merge-status inference.",
            "Ready PRs include non-feature PRs; no feature-WIP inference.",
        ],
    }


def main():
    report = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "owner": OWNER,
        "read_only": True,
        "repositories": [],
        "errors": [],
    }
    for repo in REPOS:
        try:
            report["repositories"].append(inspect(repo))
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError) as exc:
            report["errors"].append({"repository": repo, "error": str(exc)})
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
