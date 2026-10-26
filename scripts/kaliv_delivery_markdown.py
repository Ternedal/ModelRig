"""Render an auditable Markdown delivery report from collector JSON.

Input is untrusted: escape Markdown table separators and keep missing data
explicitly unknown. No API calls, writes to GitHub, or automatic decisions.
"""
import argparse
import json
from pathlib import Path

def cell(value):
    if value is None or value == "":
        return "unknown"
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")

def render(payload):
    if payload.get("schema") != "kaliv.delivery-report.v1":
        raise ValueError("unsupported delivery report schema")
    repositories = payload.get("repositories")
    if not isinstance(repositories, list):
        raise ValueError("repositories must be a list")
    lines = [
        "# Kaliv delivery status",
        "",
        "**Generated:** " + cell(payload.get("generated_at")),
        "",
        "**Source:** GitHub REST read-only snapshot. Latest workflow is not a required-check gate.",
        "",
        "| Repository | Data status | Open issues | Open PRs | Draft PRs | Ready PRs | Stale PRs (3+ days) | Latest workflow | Warnings |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for repo in repositories:
        warnings = repo.get("warnings") or []
        if not isinstance(warnings, list):
            warnings = ["invalid_warnings"]
        lines.append("| " + " | ".join(cell(v) for v in (
            repo.get("repository"), repo.get("status"), repo.get("open_issues"),
            repo.get("open_prs"), repo.get("draft_prs"), repo.get("ready_prs"),
            repo.get("stale_prs"), repo.get("workflow"),
            ", ".join(map(str, warnings)) or "none")) + " |")
    lines.extend(["", "## Attention required", ""])
    flagged = [repo for repo in repositories
               if repo.get("status") != "collected"
               or repo.get("workflow") in ("failure", "cancelled", "timed_out", "unknown")
               or (isinstance(repo.get("stale_prs"), int) and repo["stale_prs"] > 0)]
    if not flagged:
        lines.append("No warning conditions detected in the fields collected. "
                     "This is **not** evidence of integration, physical testing or release readiness.")
    else:
        for repo in flagged:
            reasons = []
            if repo.get("status") != "collected":
                reasons.append("incomplete or unavailable data")
            if repo.get("workflow") in ("failure", "cancelled", "timed_out", "unknown"):
                reasons.append("latest workflow: " + cell(repo.get("workflow")))
            if isinstance(repo.get("stale_prs"), int) and repo["stale_prs"] > 0:
                reasons.append(str(repo["stale_prs"]) + " stale PR(s)")
            lines.append("- **" + cell(repo.get("repository")) + "**: " + "; ".join(reasons))
    lines.extend(["", "## Next actions", "",
                  "1. Inspect failed or unknown workflow results before merging dependent changes.",
                  "2. Review stale PRs and record their blockers or next actions in tracking issues.",
                  "3. Confirm critical end-to-end and physical tests separately; these are **not** measured by this snapshot.",
                  "4. Reconcile priorities with the Kaliv master tracking issue (#2264).",
                  "", "## Data limitations", "",
                  "- Open issues and PRs are counts, not completion or velocity metrics.",
                  "- Latest workflow is not a rollup of all required checks.",
                  "- No evidence of release readiness, user journeys, physical acceptance or blockers is inferred.",
                  "- Truncated pagination and API errors must remain visible as warnings.",
                  ""])
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = render(payload)
    if args.output == "-":
        print(result)
    else:
        Path(args.output).write_text(result, encoding="utf-8")

if __name__ == "__main__":
    main()
