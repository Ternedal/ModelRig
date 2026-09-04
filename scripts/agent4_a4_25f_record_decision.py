#!/usr/bin/env python3
"""Record a human GO/NO-GO for A4-25f physical qualification evidence.

A GO here accepts the physical qualification campaign only. It never authorizes
or performs production activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import agent4_a4_25f_audit as audit
import agent4_a4_25f_finalize_evidence as finalizer

SCHEMA = "modelrig-agent4/a4-25f-human-decision/v1"


def _safe_human_text(value: str, label: str, max_length: int) -> str:
    text = value.strip()
    if not text or len(text) > max_length or "\r" in text or "\n" in text:
        raise ValueError(f"{label} is missing or unsafe")
    return text


def record_decision(
    output_root: Path,
    *,
    expected_sha: str,
    decision: str,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    audit._require_exact_clean_head(expected_sha)
    output = audit._resolve_output(output_root)
    target = output / "a4-25f-human-decision.json"
    if target.exists():
        raise RuntimeError("A4-25f human decision is immutable; do not rewrite an existing decision receipt")

    evidence_path = output / "a4-25f-qualification-evidence.json"
    evidence = audit._load_json(evidence_path)
    if evidence.get("schema") != finalizer.SCHEMA or evidence.get("repository_sha") != expected_sha:
        raise RuntimeError("qualification evidence authority mismatch")
    audit._verify_self_digest(evidence, "qualification_evidence_sha256", "qualification_evidence")
    audit._require_bool(
        evidence.get("physical_qualification_evidence_complete"),
        True,
        "qualification_evidence.physical_qualification_evidence_complete",
    )
    audit._require_bool(evidence.get("human_go_recorded"), False, "qualification_evidence.human_go_recorded")
    audit._require_bool(evidence.get("human_go_authorized"), False, "qualification_evidence.human_go_authorized")
    audit._require_bool(evidence.get("production_activation"), False, "qualification_evidence.production_activation")
    audit._assert_no_secrets(evidence, "qualification_evidence")

    normalized_decision = decision.strip().upper()
    if normalized_decision not in {"GO", "NO-GO"}:
        raise ValueError("decision must be GO or NO-GO")
    reviewer_text = _safe_human_text(reviewer, "reviewer", 120)
    reason_text = _safe_human_text(reason, "reason", 1000)

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository_sha": expected_sha,
        "qualification_evidence_file_sha256": audit._sha256_file(evidence_path),
        "qualification_evidence_sha256": evidence.get("qualification_evidence_sha256"),
        "reviewer": reviewer_text,
        "decision": normalized_decision,
        "reason": reason_text,
        "human_decision_recorded": True,
        "physical_qualification_human_go": normalized_decision == "GO",
        "production_activation_authorized": False,
        "production_activation": False,
    }
    audit._assert_no_secrets(receipt, "human_decision")
    receipt["decision_sha256"] = "sha256:" + hashlib.sha256(audit._canonical_json(receipt)).hexdigest()
    target.write_text(
        json.dumps(receipt, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--decision", required=True, choices=("GO", "NO-GO"))
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    record_decision(
        args.output_root,
        expected_sha=args.expected_sha,
        decision=args.decision,
        reviewer=args.reviewer,
        reason=args.reason,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
