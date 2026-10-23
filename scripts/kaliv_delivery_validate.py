"""Validate completeness of a Kaliv delivery snapshot without overstating health.

Exit 0 means all expected repositories were queried completely. It does NOT
mean their CI, releases, integrations, or physical tests are healthy.
"""
import argparse
import json
from pathlib import Path

from kaliv_delivery_report import REPOS

def validate(payload, owner="Ternedal"):
    errors = []
    if payload.get("schema") != "kaliv.delivery-report.v1":
        errors.append("invalid_schema")
    repos = payload.get("repositories")
    if not isinstance(repos, list):
        return ["repositories_not_list"]
    expected = {owner + "/" + name for name in REPOS}
    names = [r.get("repository") for r in repos if isinstance(r, dict)]
    if len(names) != len(repos):
        errors.append("malformed_repository_entry")
    if len(names) != len(set(names)):
        errors.append("duplicate_repositories")
    for missing in sorted(expected - set(names)):
        errors.append("missing:" + missing)
    for extra in sorted(set(names) - expected):
        errors.append("unexpected:" + str(extra))
    for r in repos:
        if not isinstance(r, dict):
            continue
        name = str(r.get("repository", "unknown"))
        if r.get("status") != "collected":
            errors.append("incomplete:" + name)
        for key in ("open_issues", "open_prs", "stale_prs"):
            value = r.get(key)
            if type(value) is not int or value < 0:
                errors.append("invalid_" + key + ":" + name)
        if r.get("warnings"):
            errors.append("warnings:" + name)
        if not isinstance(r.get("workflow"), str) or r.get("workflow") == "unknown":
            errors.append("unknown_workflow:" + name)
    return errors

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--owner", default="Ternedal")
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    errors = validate(payload, args.owner)
    if errors:
        print("Snapshot completeness gate FAILED (not a CI/release gate):")
        for error in errors:
            print(" -", error)
        raise SystemExit(1)
    print("Snapshot completeness gate PASS: all expected repositories collected.")
    print("No assertion about required checks, integration, physical testing or release.")

if __name__ == "__main__":
    main()
