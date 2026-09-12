#!/usr/bin/env python3
"""Run exactly one local model turn to propose an RSI improvement.

The model is proposal-only: its JSON is accepted only after strict binding to
the exact eval brief.  This command never creates DevelopmentTask, starts
DevControl execution, writes Git state or retries the model autonomously.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))
sys.path.insert(0, str(ROOT / "worker"))

from app import ollama_client as oc  # noqa: E402
from kaliv_dev_control.improvement_model import (  # noqa: E402
    generate_bound_improvement_proposal,
)
from kaliv_dev_control.improvement_proposal import (  # noqa: E402
    ImprovementProposalError,
    build_agent3_improvement_brief,
)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImprovementProposalError(f"eval report does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImprovementProposalError(f"eval report is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ImprovementProposalError("eval report must contain a JSON object")
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


def _require_loopback_ollama(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ImprovementProposalError("RSI model runner requires http(s) Ollama")
    host = parsed.hostname
    if not host:
        raise ImprovementProposalError("Ollama URL has no host")
    if host.lower() == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ImprovementProposalError(
            "RSI model runner is local-only; Ollama host must be localhost or loopback IP"
        ) from exc
    if not address.is_loopback:
        raise ImprovementProposalError(
            "RSI model runner is local-only; non-loopback Ollama is refused"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-report", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--repository", default="Ternedal/ModelRig")
    parser.add_argument("--model", required=True)
    parser.add_argument("--brief-out", type=Path)
    parser.add_argument("--raw-out", type=Path)
    parser.add_argument("--proposal-out", type=Path, required=True)
    args = parser.parse_args(argv)

    raw_seen: dict[str, str] = {}
    try:
        report = _read_json(args.eval_report)
        brief = build_agent3_improvement_brief(
            report,
            repository=args.repository,
            base_sha=args.base_sha,
        )
        if args.brief_out:
            _write_text_atomic(
                args.brief_out,
                json.dumps(brief, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
        if not brief["proposal_required"]:
            print("RSI: eval er ren; modellen kaldes ikke, og intet forslag oprettes.", file=sys.stderr)
            return 0

        _require_loopback_ollama(oc.OLLAMA_URL)

        async def chat(messages: list[dict[str, str]], model: str) -> str:
            raw = await oc.chat(messages, model=model)
            raw_seen["value"] = raw
            return raw

        result = asyncio.run(
            generate_bound_improvement_proposal(
                brief,
                model=args.model,
                chat=chat,
            )
        )
        if args.raw_out:
            _write_text_atomic(args.raw_out, result.raw_response + "\n")
        _write_text_atomic(args.proposal_out, result.proposal.canonical_json() + "\n")
        print(
            "RSI: modelproposal accepteret som proposal-only; "
            f"raw_sha256={result.raw_response_sha256}",
            file=sys.stderr,
        )
        return 0
    except (ImprovementProposalError, oc.OllamaError, OSError, UnicodeError) as exc:
        if args.raw_out and raw_seen.get("value") is not None:
            try:
                _write_text_atomic(args.raw_out, raw_seen["value"] + "\n")
            except OSError:
                pass
        print(f"RSI FEJL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
