"""Independent verifier for Agent 3 workflow completion receipts."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .workflow_completion import RECEIPT_SCHEMA, WorkflowCompletionError

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_KEYS = {
    "schema",
    "scenario_id",
    "candidate",
    "run_id",
    "passed",
    "checks",
    "scenario_sha256",
    "observation_sha256",
    "production_activation",
    "receipt_sha256",
}


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_workflow_completion_receipt(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate structure, verdict consistency and content digest fail-closed."""

    if not isinstance(raw, Mapping):
        raise WorkflowCompletionError("receipt must be an object")
    if set(raw) != _RECEIPT_KEYS:
        raise WorkflowCompletionError("receipt fields do not match the v1 schema")
    receipt = dict(raw)
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise WorkflowCompletionError("unsupported workflow completion receipt schema")
    if not isinstance(receipt.get("scenario_id"), str) or not receipt["scenario_id"]:
        raise WorkflowCompletionError("receipt scenario_id is invalid")
    if not isinstance(receipt.get("run_id"), str) or not receipt["run_id"]:
        raise WorkflowCompletionError("receipt run_id is invalid")
    if receipt.get("production_activation") is not False:
        raise WorkflowCompletionError("workflow receipt may not activate production")
    if not _SHA64.fullmatch(str(receipt.get("scenario_sha256", ""))):
        raise WorkflowCompletionError("receipt scenario_sha256 is invalid")
    if not _SHA64.fullmatch(str(receipt.get("observation_sha256", ""))):
        raise WorkflowCompletionError("receipt observation_sha256 is invalid")
    if not _SHA64.fullmatch(str(receipt.get("receipt_sha256", ""))):
        raise WorkflowCompletionError("receipt_sha256 is invalid")

    candidate = receipt.get("candidate")
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "git_sha",
        "worker_code_sha256",
        "model",
        "model_digest",
    }:
        raise WorkflowCompletionError("receipt candidate binding is invalid")
    if not _SHA40.fullmatch(str(candidate.get("git_sha", ""))):
        raise WorkflowCompletionError("receipt git_sha is invalid")
    if not _SHA64.fullmatch(str(candidate.get("worker_code_sha256", ""))):
        raise WorkflowCompletionError("receipt worker_code_sha256 is invalid")
    if not isinstance(candidate.get("model"), str) or not candidate["model"].strip():
        raise WorkflowCompletionError("receipt model is invalid")
    if not _SHA64.fullmatch(str(candidate.get("model_digest", ""))):
        raise WorkflowCompletionError("receipt model_digest is invalid")

    checks = receipt.get("checks")
    if not isinstance(checks, list) or not checks:
        raise WorkflowCompletionError("receipt checks must be a non-empty list")
    check_ids: set[str] = set()
    verdicts: list[bool] = []
    for index, check in enumerate(checks):
        if not isinstance(check, Mapping) or set(check) != {"id", "passed", "detail"}:
            raise WorkflowCompletionError(f"receipt check {index} is invalid")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id or check_id in check_ids:
            raise WorkflowCompletionError(f"receipt check {index} id is invalid or duplicated")
        check_ids.add(check_id)
        if not isinstance(check.get("passed"), bool):
            raise WorkflowCompletionError(f"receipt check {index} verdict is invalid")
        if not isinstance(check.get("detail"), str):
            raise WorkflowCompletionError(f"receipt check {index} detail is invalid")
        verdicts.append(check["passed"])

    if not isinstance(receipt.get("passed"), bool):
        raise WorkflowCompletionError("receipt passed must be boolean")
    if receipt["passed"] != all(verdicts):
        raise WorkflowCompletionError("receipt verdict does not match its checks")

    expected_digest = receipt.pop("receipt_sha256")
    actual_digest = _canonical_sha256(receipt)
    if expected_digest != actual_digest:
        raise WorkflowCompletionError("receipt content digest does not match")
    receipt["receipt_sha256"] = expected_digest
    return receipt
