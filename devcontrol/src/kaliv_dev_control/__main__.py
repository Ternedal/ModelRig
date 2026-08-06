"""Administrative CLI for the dependency-minimal DC-L01 foundation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contract import ContractError, DevelopmentTask
from .evidence import build_scope_receipt
from .policy import PathPolicy


def _task(path: str) -> DevelopmentTask:
    return DevelopmentTask.from_json(Path(path).read_text(encoding="utf-8"))


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

    args = parser.parse_args()
    try:
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
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
