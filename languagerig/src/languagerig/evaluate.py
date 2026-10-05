"""Deterministic response checks plus an escaped side-by-side human review."""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from .core import LanguageRigError, file_digest, jsonl, now, write_json
from .corpus import verify_dataset
from .integrate import request_json, validate_url


def check_response(response: str, checks: list[dict]) -> list[dict]:
    result = []
    for check in checks:
        kind = check["kind"]
        value = check["value"]
        if kind == "exact":
            passed = response.strip() == value
        elif kind == "contains":
            passed = value.casefold() in response.casefold()
        elif kind == "json_keys":
            try:
                parsed = json.loads(response)
                passed = isinstance(parsed, dict) and set(parsed) == set(value)
            except json.JSONDecodeError:
                passed = False
        else:
            raise LanguageRigError("Unknown response check.")
        result.append({**check, "passed": passed})
    return result


def evaluate(cases_path: Path, target: Path, *, url: str, baseline: str,
             candidate: str, dataset: Path | None = None) -> dict:
    url = validate_url(url, loopback=True)
    if baseline == candidate or not baseline or not candidate:
        raise LanguageRigError("Choose two different non-empty model names.")
    if target.exists():
        raise LanguageRigError("Evaluation directory already exists.")
    cases = list(jsonl(cases_path))
    if not cases:
        raise LanguageRigError("Evaluation needs at least one case.")
    ids = set()
    manifest = verify_dataset(dataset) if dataset else None
    for case in cases:
        if (not isinstance(case.get("id"), str) or not case["id"] or case["id"] in ids
                or not isinstance(case.get("prompt"), str) or not case["prompt"].strip()):
            raise LanguageRigError("Evaluation cases need unique IDs and non-empty prompts.")
        ids.add(case["id"])
        for check in case.get("checks", []):
            if not isinstance(check, dict) or check.get("kind") not in ("exact", "contains", "json_keys"):
                raise LanguageRigError("Unsupported response check.")
            value = check.get("value")
            if (check["kind"] == "json_keys" and (not isinstance(value, list) or not all(isinstance(v, str) for v in value))
                    or check["kind"] != "json_keys" and (not isinstance(value, str) or not value)):
                raise LanguageRigError("Invalid response check value.")
        if case.get("source_ids"):
            if not manifest or any(manifest["split_by_source"].get(s) != "test" for s in case["source_ids"]):
                raise LanguageRigError("Book-derived evaluation must reference only held-out test sources.")
    tags = request_json(url + "/api/tags")
    model_digests = {model["name"]: model["digest"] for model in tags.get("models", [])}
    if baseline not in model_digests or candidate not in model_digests:
        raise LanguageRigError("Both exact model names must exist in local Ollama.")
    if model_digests[baseline] == model_digests[candidate]:
        raise LanguageRigError("Baseline and candidate have the same Ollama digest.")
    report = {"format": "languagerig-comparison/v1", "started_at": now(), "status": "running",
              "baseline": baseline, "candidate": candidate, "model_digests": {
                  baseline: model_digests[baseline], candidate: model_digests[candidate]},
              "cases_sha256": file_digest(cases_path), "results": [],
              "dataset_sha256": manifest["dataset_sha256"] if manifest else None,
              "quality_improvement": "not_determined", "manual_review_required": True,
              "rag_used": False, "tool_calling_qualified": False}
    target.mkdir(parents=True)
    write_json(target / "comparison.json", report)
    try:
        for case in cases:
            row = {"id": case["id"], "category": case.get("category", "unspecified"),
                   "prompt": case["prompt"], "source_ids": case.get("source_ids", []), "models": {}}
            for name in (baseline, candidate):
                started = time.monotonic()
                result = request_json(url + "/api/chat", {
                    "model": name, "messages": [{"role": "system", "content": "Svar på dansk og følg brugerens instruktion."},
                                              {"role": "user", "content": case["prompt"]}],
                    "stream": False, "options": {"temperature": 0, "seed": 42}, "keep_alive": 0,
                })
                response = result.get("message", {}).get("content")
                if not isinstance(response, str) or not response.strip() or result.get("done") is not True:
                    raise LanguageRigError("Ollama returned an empty/incomplete response.")
                row["models"][name] = {"response": response, "seconds": time.monotonic() - started,
                                       "checks": check_response(response, case.get("checks", []))}
            report["results"].append(row)
            write_json(target / "comparison.json", report)
        # A concurrent model replacement makes this run non-comparable.
        final_tags = request_json(url + "/api/tags")
        final_digests = {m["name"]: m["digest"] for m in final_tags.get("models", [])}
        if any(final_digests.get(name) != report["model_digests"][name] for name in (baseline, candidate)):
            raise LanguageRigError("An Ollama model changed during evaluation.")
        report.update(status="completed", completed_at=now())
        report["automatic_checks"] = {}
        for name in (baseline, candidate):
            checks = [check for row in report["results"] for check in row["models"][name]["checks"]]
            report["automatic_checks"][name] = {"passed": sum(c["passed"] for c in checks), "total": len(checks)}
        write_json(target / "comparison.json", report)
        render_comparison(report, target / "comparison.html")
        return report
    except BaseException:
        report["status"] = "failed"
        write_json(target / "comparison.json", report)
        raise


def render_comparison(report: dict, path: Path) -> None:
    esc = lambda value: html.escape(str(value), quote=True)
    parts = ['<!doctype html><html lang="da"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>LanguageRig · sammenligning</title><style>',
             'body{font:16px system-ui;background:#11151b;color:#ecedf1;max-width:1100px;margin:40px auto;padding:20px}',
             'section{border-top:1px solid #45505c;margin-top:30px;padding-top:16px}',
             '.answers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}',
             'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:#1c232d;padding:18px;border-radius:8px}',
             '@media(max-width:650px){.answers{grid-template-columns:1fr}}</style>',
             '<h1>LanguageRig · sammenligning</h1>',
             '<p>Vurder dansk, faglig korrekthed og instruktioner. Automatiske formatkontroller er ikke en samlet kvalitetsdom.</p>']
    for row in report["results"]:
        parts.append(f'<section><h2>{esc(row["id"])}</h2><p>{esc(row["prompt"])}</p><div class="answers">')
        for name in (report["baseline"], report["candidate"]):
            value = row["models"][name]
            parts.append(f'<div><h3>{esc(name)}</h3><pre>{esc(value["response"])}</pre><p>{value["seconds"]:.1f} sek.</p></div>')
        parts.append("</div></section>")
    parts.append("</html>")
    path.write_text("".join(parts), encoding="utf-8")
