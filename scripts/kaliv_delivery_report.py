"""Read-only cross-repository delivery snapshot using GitHub REST API.

No write endpoints. Missing/failed API data is reported as unknown, never green.
Requires GITHUB_TOKEN with read-only metadata, issues, pull requests and actions.
"""
import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request

REPOS = ("ModelRig", "Kaliv", "KalivNexus", "VoiceRig", "VisionRig",
         "BodyRig", "LanguageRig", "KalivHub", "KalivHub-Receiver",
         "SkyPlayer-Engine")
BASE = "https://api.github.com"
MAX_PAGES = 10

class GitHubReadClient:
    def __init__(self, token, opener=None):
        if not token:
            raise ValueError("GITHUB_TOKEN required")
        self.token = token
        self.opener = opener or urllib.request.urlopen

    def get(self, path):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("relative GitHub API path required")
        url = BASE + path
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "kaliv-delivery-report/1.0"})
        with self.opener(request, timeout=15) as response:
            return json.load(response)

    def pages(self, path):
        items = []
        for page in range(1, MAX_PAGES + 1):
            separator = "&" if "?" in path else "?"
            chunk = self.get(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(chunk, list):
                raise ValueError("expected list response")
            items.extend(chunk)
            if len(chunk) < 100:
                return items, False
        return items, True

def summarize_repo(client, owner, repo):
    path = "/repos/{}/{}".format(urllib.parse.quote(owner, safe=""),
                                 urllib.parse.quote(repo, safe=""))
    output = {"repository": owner + "/" + repo, "status": "unknown",
              "open_issues": None, "open_prs": None, "stale_prs": None,
              "workflow": "unknown", "warnings": []}
    try:
        issues, issues_truncated = client.pages(path + "/issues?state=open")
        prs, prs_truncated = client.pages(path + "/pulls?state=open")
        output["open_issues"] = sum("pull_request" not in issue for issue in issues)
        output["open_prs"] = len(prs)
        now = dt.datetime.now(dt.timezone.utc)
        output["stale_prs"] = sum(
            (now - dt.datetime.fromisoformat(p["updated_at"].replace("Z", "+00:00"))).days >= 3
            for p in prs)
        if issues_truncated or prs_truncated:
            output["warnings"].append("pagination_limit_reached")
        runs = client.get(path + "/actions/runs?per_page=1")
        latest = runs.get("workflow_runs", [])
        if latest:
            run = latest[0]
            output["workflow"] = (run.get("conclusion") or run.get("status") or "unknown")
            output["workflow_url"] = run.get("html_url")
        else:
            output["warnings"].append("no_workflow_runs")
        output["status"] = "partial" if output["warnings"] else "collected"
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            ValueError, KeyError, TypeError) as error:
        output["warnings"].append("github_api_error:" + type(error).__name__)
    return output

def report(client, owner="Ternedal", repositories=REPOS):
    return {"schema": "kaliv.delivery-report.v1",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": "github_rest_read_only",
            "note": "Latest workflow is informational, not required-check or release proof.",
            "repositories": [summarize_repo(client, owner, repo) for repo in repositories]}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default="Ternedal")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    result = report(GitHubReadClient(os.getenv("GITHUB_TOKEN")), owner=args.owner)
    serialized = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output == "-":
        print(serialized)
    else:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(serialized + "\n")

if __name__ == "__main__":
    main()
