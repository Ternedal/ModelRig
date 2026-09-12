#!/usr/bin/env python3
"""Build and validate the proposal-only RSI bridge from Agent 3 eval evidence.

This command is intentionally offline.  It does not call a model, start a
DevControl campaign or grant execution authority.  It creates the exact brief
and prompt a model may consume, and can fail-closed validate the model JSON
against that same evidence afterwards.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))

from kaliv_dev_control.improvement_binding import (  # noqa: E402
    canonical_bound_proposal_json,
)
from kaliv_dev_control.improvement_evidence import (  # noqa: E402
    build_verified_agent3_improvement_brief,
)
from kaliv_dev_control.improvement_proposal import (  # noqa: E402
    ImprovementProposalError,
    render_improvement_prompt,
)


def _read_json(path: Path, *, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImprovementProposalError(f"{name} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImprovementProposalError(f"{name} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ImprovementProposalError(f"{name} must contain a JSON object")
    return value


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        temp = Path(handle.name)
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-report", type=Path, required=True)
    parser.add_argument("--repository", default="Ternedal/ModelRig")
    parser.add_argument(
        "--base-sha",
        required=True,
        help=(
            "exact repository Git SHA supplied by repository authority; "
            "the Agent 3 eval itself carries code_sha256, not a Git SHA"
        ),
    )
    parser.add_argument("--brief-out", type=Path)
    parser.add_argument("--prompt-out", type=Path)
    parser.add_argument(
        "--proposal",
        type=Path,
        help="optional model-produced proposal JSON to bind and validate",
    )
    parser.add_argument(
        "--canonical-proposal-out",
        type=Path,
        help="write canonical proposal JSON after successful binding",
    )
    args = parser.parse_args(argv)

    try:
        report = _read_json(args.eval_report, name="eval report")
        brief = build_verified_agent3_improvement_brief(
            report,
            repository=args.repository,
            base_sha=args.base_sha,
        )
        pretty_brief = json.dumps(brief, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.brief_out:
            _write_text_atomic(args.brief_out, pretty_brief)
        else:
            print(pretty_brief, end="")

        if not brief["proposal_required"]:
            if args.prompt_out or args.proposal or args.canonical_proposal_out:
                raise ImprovementProposalError(
                    "eval evidence is clean; no improvement proposal is required"
                )
            print("RSI: ingen observerede Agent 3 eval-gaps; intet forslag oprettet.", file=sys.stderr)
            return 0

        prompt = render_improvement_prompt(brief)
        if args.prompt_out:
            _write_text_atomic(args.prompt_out, prompt + "\n")

        if args.proposal:
            proposal_text = args.proposal.read_text(encoding="utf-8")
            canonical = canonical_bound_proposal_json(proposal_text, brief=brief)
            if args.canonical_proposal_out:
                _write_text_atomic(args.canonical_proposal_out, canonical + "\n")
            else:
                print(canonical)
            print("RSI: proposal er valideret og bundet til eval-evidensen.", file=sys.stderr)
        elif args.canonical_proposal_out:
            raise ImprovementProposalError(
                "--canonical-proposal-out requires --proposal"
            )
        return 0
    except (ImprovementProposalError, OSError, UnicodeError) as exc:
        print(f"RSI FEJL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
