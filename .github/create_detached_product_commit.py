from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
PARENT = "2225ff371c764451499613a94d3540dfe1f0b742"
API = f"https://api.github.com/repos/{REPO}"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def api(method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "modelrig-detached-product-builder",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} failed: HTTP {exc.code}: {body}") from exc


subprocess.check_call(["git", "add", "-A"])
changed = git("diff", "--cached", "--name-status", PARENT).splitlines()
if not changed:
    raise SystemExit("no staged product changes")

base_commit = api("GET", f"/git/commits/{PARENT}")
base_tree = base_commit["tree"]["sha"]
entries: list[dict] = []
paths: list[str] = []

for line in changed:
    fields = line.split("\t")
    status = fields[0]
    path = fields[-1]
    paths.append(path)
    if status.startswith("D"):
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        continue

    staged = subprocess.check_output(["git", "show", f":{path}"])
    blob = api(
        "POST",
        "/git/blobs",
        {
            "content": base64.b64encode(staged).decode("ascii"),
            "encoding": "base64",
        },
    )
    index_line = git("ls-files", "-s", "--", path)
    if not index_line:
        raise SystemExit(f"missing index mode for {path}")
    mode = index_line.split()[0]
    entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob["sha"]})

tree = api("POST", "/git/trees", {"base_tree": base_tree, "tree": entries})
commit = api(
    "POST",
    "/git/commits",
    {
        "message": "feat(agent3): add one-command physical validation",
        "tree": tree["sha"],
        "parents": [PARENT],
    },
)

result = Path("/tmp/agent3-validation-command-result.txt")
result.write_text(
    "\n".join(
        [
            f"commit={commit['sha']}",
            f"base={PARENT}",
            "version=1.58.83",
            f"files={len(paths)}",
            *sorted(paths),
            "",
        ]
    ),
    encoding="utf-8",
)
print(result.read_text(encoding="utf-8"))
