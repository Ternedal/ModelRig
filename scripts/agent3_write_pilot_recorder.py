#!/usr/bin/env python3
"""CLI for the append-only T-022 negative evidence journal."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from agent3_write_pilot_common import _NEGATIVE_CASES, _atomic_json  # noqa: E402
from agent3_write_pilot_journal_cases import (  # noqa: E402
    RecorderError, _init, begin_case, finish_case, finalize, observe_request,
)


def _cmd_init(args: argparse.Namespace) -> int:
    _init(Path(args.journal), Path(args.manifest))
    print(f"initialized T-022 journal: {args.journal}")
    return 0


def _cmd_begin(args: argparse.Namespace) -> int:
    case_id, marker = begin_case(
        journal=Path(args.journal), manifest_path=Path(args.manifest),
        name=args.case, note_count=args.note_count,
        approval_count=args.approval_count, positive_ordinal=args.positive_ordinal,
    )
    print(json.dumps({"case_id": case_id, "marker": marker}, ensure_ascii=False))
    return 0


def _cmd_observe(args: argparse.Namespace) -> int:
    digest = observe_request(
        journal=Path(args.journal), case_id=args.case_id, status=args.status,
        response_path=Path(args.response_file), run_id=args.run_id,
    )
    print(f"recorded response: {digest}")
    return 0


def _cmd_finish(args: argparse.Namespace) -> int:
    digest = finish_case(
        journal=Path(args.journal), case_id=args.case_id,
        note_count=args.note_count, approval_count=args.approval_count,
    )
    print(f"finished case: {digest}")
    return 0


def _cmd_finalize(args: argparse.Namespace) -> int:
    negative = finalize(Path(args.journal), Path(args.manifest))
    _atomic_json(Path(args.output), negative)
    print(f"wrote strict negative evidence: {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--manifest", required=True); init.add_argument("--journal", required=True)
    init.set_defaults(func=_cmd_init)
    begin = sub.add_parser("begin")
    begin.add_argument("--manifest", required=True); begin.add_argument("--journal", required=True)
    begin.add_argument("--case", choices=_NEGATIVE_CASES, required=True)
    begin.add_argument("--note-count", type=int, required=True)
    begin.add_argument("--approval-count", type=int, required=True)
    begin.add_argument("--positive-ordinal", type=int); begin.set_defaults(func=_cmd_begin)
    observe = sub.add_parser("observe")
    observe.add_argument("--journal", required=True); observe.add_argument("--case-id", required=True)
    observe.add_argument("--status", type=int, required=True)
    observe.add_argument("--response-file", required=True); observe.add_argument("--run-id", required=True)
    observe.set_defaults(func=_cmd_observe)
    finish = sub.add_parser("finish")
    finish.add_argument("--journal", required=True); finish.add_argument("--case-id", required=True)
    finish.add_argument("--note-count", type=int, required=True)
    finish.add_argument("--approval-count", type=int, required=True); finish.set_defaults(func=_cmd_finish)
    final = sub.add_parser("finalize")
    final.add_argument("--manifest", required=True); final.add_argument("--journal", required=True)
    final.add_argument("--output", required=True); final.set_defaults(func=_cmd_finalize)
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (RecorderError, OSError, sqlite3.Error) as exc:
        print(f"T-022 recorder error: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
