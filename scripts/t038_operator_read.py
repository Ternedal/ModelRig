#!/usr/bin/env python3
"""Deterministic operator read of ONE Home Assistant entity through T-038.

Until now a T-038 read happened only through the ToolGate tool
``home_assistant_read``, which a model must choose to call, so a consented
live test could not be repeated. This script is the operator entry point for
that test (docs/T038_HOME_ASSISTANT_LIVE_READ.md, KalivNexus #1).

It adds no capability. It runs the same ``HomeRigRuntime.read`` the tool uses,
with the worker's own grant store, audit log and T-032 ledger (same
``data_root()`` / ``KALIV_*_DB`` paths) and the same deployment settings
(``KALIV_HOME_ASSISTANT_ORIGIN``, ``..._TOKEN_FILE``, ``..._ALLOW_INSECURE_HTTP``).
So it needs an exact active grant AND an approved one-use T-032 permission,
both created beforehand on the loopback operator API. It reads exactly one
entity, once. There is no rig, preview, write or service-call path here.

Refuses before any network or credential access unless the default-off pilot
switch (``KALIV_HOME_RIG_PILOT=1``) is set and ``--confirm-live-read`` is given.

Exit codes: 0 observed and fresh, 3 provider unavailable (state ``unknown``),
1 denied or configuration failure, 2 refused or usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SCHEMA = "kaliv-home-rig-live-read/v1"

# Only these receipt fields ever reach the terminal or the evidence file
# (review 5660163195). A field the runtime adds later is dropped and named in
# "omitted_fields" instead of being copied silently.
RECEIPT_FIELDS = (
    "schema", "grant_id", "scope_sha256", "fulfilled_at", "authority_rechecked", "production_activation",
)
OBSERVATION_FIELDS = (
    "schema", "source", "source_id", "capability_id", "target_kind", "target_id", "operation",
    "state", "checked_at", "observed_at", "freshness", "freshness_seconds", "max_freshness_seconds",
    "production_activation",
)


def project_receipt(receipt: dict) -> dict:
    """Return only allowlisted receipt fields, plus the names of any dropped ones."""
    if not isinstance(receipt, dict):
        return {"omitted_fields": ["<receipt is not an object>"]}
    observation = receipt.get("observation")
    observation = observation if isinstance(observation, dict) else {}
    omitted = sorted(k for k in receipt if k not in RECEIPT_FIELDS and k != "observation")
    omitted += sorted(f"observation.{k}" for k in observation if k not in OBSERVATION_FIELDS)
    projected = {k: receipt[k] for k in RECEIPT_FIELDS if k in receipt}
    projected["observation"] = {k: observation[k] for k in OBSERVATION_FIELDS if k in observation}
    projected["omitted_fields"] = omitted
    return projected


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--entity", required=True, help="exact Home Assistant entity id in the active grant")
    parser.add_argument("--permission-id", required=True, help="approved one-use T-032 permission (dsp_...)")
    parser.add_argument("--confirm-live-read", action="store_true",
                        help="required: this contacts the configured Home Assistant once")
    parser.add_argument("--evidence", type=Path, help="write a kaliv-home-rig-live-read/v1 evidence file")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing an existing evidence file")
    args = parser.parse_args(argv)

    if os.getenv("KALIV_HOME_RIG_PILOT", "0").strip().lower() not in {"1", "true", "on"}:
        print("REFUSED: the T-038 pilot is off (KALIV_HOME_RIG_PILOT=1 is required). Nothing was read.")
        return 2
    if not args.confirm_live_read:
        print("REFUSED: pass --confirm-live-read to contact Home Assistant once. Nothing was read.")
        return 2
    if args.evidence is not None and args.evidence.exists() and not args.overwrite:
        # Checked before the read, so a refusal never burns the one-use permission.
        print(f"REFUSED: {args.evidence} already exists; pass --overwrite to replace it. Nothing was read.")
        return 2

    sys.path.insert(0, str(ROOT / "worker"))
    import app.home_rig_tool as runtime_module  # noqa: E402  (paths resolve from this process's env)
    from app import tools  # noqa: E402

    runtime = runtime_module._default_runtime()
    try:
        raw = runtime.read(
            target_kind="entity",
            target_id=args.entity,
            operation="entity_state",
            permission_id=args.permission_id,
        )
    except tools.ToolDenied as exc:
        print(f"DENIED: {exc}")
        return 1
    except tools.ToolError as exc:
        print(f"CONFIGURATION FAILED: {exc}")
        return 1

    projected = project_receipt(json.loads(raw))
    observation = projected["observation"]
    observed = observation.get("state") != "unknown" and observation.get("freshness") == "fresh"
    print(json.dumps(projected, indent=2, sort_keys=True))

    if args.evidence is not None:
        scheme = urlsplit(os.getenv("KALIV_HOME_ASSISTANT_ORIGIN", "")).scheme or None
        evidence = {
            "schema": EVIDENCE_SCHEMA,
            "candidate": {"git_sha": _git_sha()},
            "recorded_at": int(time.time()),
            "origin_scheme": scheme,
            "receipt": projected,
            "result": "observed" if observed else "unavailable",
            "production_activation": False,
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"evidence: {args.evidence}")
    return 0 if observed else 3


if __name__ == "__main__":
    raise SystemExit(main())
