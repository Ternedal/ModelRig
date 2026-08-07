"""Administrative CLI for contracts and operator-owned physical evidence."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from .catalog import IsolationAttestation
from .contract import ContractError, DevelopmentTask
from .evidence import build_scope_receipt
from .physical_isolation import (
    HmacIsolationReportSigner,
    PhysicalIsolationError,
    WindowsPhysicalIsolationVerifier,
    load_signing_secret,
    load_unsigned_report,
    write_signed_report,
)
from .policy import PathPolicy


def _absolute(value: str) -> Path:
    path = Path(value).absolute()
    if not path.is_absolute():
        raise PhysicalIsolationError("operator path must be absolute")
    return path


def _task(path: str) -> DevelopmentTask:
    return DevelopmentTask.from_json(_absolute(path).read_text(encoding="utf-8"))


def _attestation(path: str) -> IsolationAttestation:
    candidate = _absolute(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise PhysicalIsolationError("isolation attestation must be a regular non-symlink file")
    try:
        raw = candidate.read_bytes()
        if len(raw) > 2_000_000:
            raise PhysicalIsolationError("isolation attestation is too large")
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhysicalIsolationError("isolation attestation JSON is invalid") from exc
    attestation = IsolationAttestation.from_mapping(value)
    if raw != attestation.canonical_json().encode("utf-8"):
        raise PhysicalIsolationError("isolation attestation is not canonical JSON")
    return attestation


def main() -> int:
    parser = argparse.ArgumentParser(prog="kaliv-dev-control")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-task")
    validate.add_argument("task")

    check = subparsers.add_parser("check-paths")
    check.add_argument("task")
    check.add_argument("paths", nargs="+")
    check.add_argument("--added-lines", type=int, required=True)
    check.add_argument("--deleted-lines", type=int, required=True)

    sign = subparsers.add_parser("sign-physical-report")
    sign.add_argument("unsigned_report")
    sign.add_argument("output")
    sign.add_argument("--key-file", required=True)
    sign.add_argument("--key-id", required=True)

    verify = subparsers.add_parser("verify-physical-report")
    verify.add_argument("attestation")
    verify.add_argument("--evidence-root", required=True)
    verify.add_argument("--key-file", required=True)
    verify.add_argument("--key-id", required=True)
    verify.add_argument("--max-age-days", type=int, default=30)

    args = parser.parse_args()
    try:
        if args.command == "sign-physical-report":
            report = load_unsigned_report(_absolute(args.unsigned_report))
            secret = load_signing_secret(_absolute(args.key_file))
            signed = HmacIsolationReportSigner(args.key_id, secret).sign(report)
            digest = write_signed_report(_absolute(args.output), signed)
            print(digest)
            return 0

        if args.command == "verify-physical-report":
            if not 1 <= args.max_age_days <= 366:
                raise PhysicalIsolationError("max-age-days must be in 1..366")
            isolation = _attestation(args.attestation)
            secret = load_signing_secret(_absolute(args.key_file))
            verifier = WindowsPhysicalIsolationVerifier(
                _absolute(args.evidence_root),
                {args.key_id: secret},
                max_age=timedelta(days=args.max_age_days),
            )
            verifier.verify(isolation)
            print("verified")
            return 0

        task = _task(args.task)
        if args.command == "validate-task":
            print(task.canonical_json())
            return 0
        decision = PathPolicy(task).evaluate(
            args.paths,
            added_lines=args.added_lines,
            deleted_lines=args.deleted_lines,
        )
        receipt = build_scope_receipt(
            task,
            decision,
            added_lines=args.added_lines,
            deleted_lines=args.deleted_lines,
        )
        print(json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if decision.passed else 2
    except (ContractError, PhysicalIsolationError, OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
