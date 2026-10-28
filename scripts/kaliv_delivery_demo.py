"""Produce a deterministic, clearly synthetic Kaliv report for CI smoke tests.

Never use this fixture as evidence of actual GitHub status.
"""
import json
from pathlib import Path

from kaliv_delivery_markdown import render

def main():
    root = Path("kaliv-report-demo")
    root.mkdir(exist_ok=True)
    payload = {
        "schema": "kaliv.delivery-report.v1",
        "generated_at": "SYNTHETIC_FIXTURE_NOT_LIVE",
        "source": "offline_fixture",
        "repositories": [
            {"repository": "fixture/green", "status": "collected", "open_issues": 1,
             "open_prs": 0, "stale_prs": 0, "workflow": "success", "warnings": []},
            {"repository": "fixture/failed", "status": "collected", "open_issues": 3,
             "open_prs": 2, "stale_prs": 1, "workflow": "failure", "warnings": []},
            {"repository": "fixture/unavailable", "status": "unknown",
             "open_issues": None, "open_prs": None, "stale_prs": None,
             "workflow": "unknown", "warnings": ["github_api_error:HTTPError"]},
        ],
    }
    markdown = render(payload)
    header = "> **SYNTHETIC TEST DATA — NOT LIVE GITHUB STATUS**\n\n"
    (root / "report.md").write_text(header + markdown, encoding="utf-8")
    (root / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert "fixture/failed" in markdown
    assert "unknown" in markdown
    assert "SYNTHETIC" in (root / "report.md").read_text(encoding="utf-8")

if __name__ == "__main__":
    main()
