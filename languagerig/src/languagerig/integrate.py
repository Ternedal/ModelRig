"""Handoff to the existing paired ModelRig RAG API and local Ollama."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .core import LanguageRigError, books, digest, file_digest, now, read_json, write_json
from .corpus import chunks


def validate_url(url: str, *, loopback=False) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise LanguageRigError("Expected a plain HTTP(S) service URL.")
    if loopback and parsed.hostname.lower() != "localhost":
        try:
            if not ipaddress.ip_address(parsed.hostname).is_loopback:
                raise LanguageRigError("Model evaluation/registration uses a loopback Ollama endpoint.")
        except ValueError as exc:
            raise LanguageRigError("Model evaluation/registration uses a loopback Ollama endpoint.") from exc
    return url.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url: str, body: dict | None = None, *, token=None, timeout=600) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
                                     headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            data = response.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024:
                raise LanguageRigError("Service response exceeds the size limit.")
            result = json.loads(data)
    except urllib.error.HTTPError as exc:
        raise LanguageRigError(f"Service returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LanguageRigError("Service unavailable or returned invalid JSON.") from exc
    if not isinstance(result, dict) or result.get("error"):
        raise LanguageRigError("Service response is not a successful JSON object.")
    return result


def export_rag(workspace: Path, target: Path) -> dict:
    if target.exists():
        raise LanguageRigError("RAG export directory already exists.")
    eligible = [book for book in books(workspace) if book.get("quality_accepted")]
    if not eligible:
        raise LanguageRigError("No quality-accepted books to export.")
    target.mkdir(parents=True)
    files, sources, seen_content = {}, [], set()
    for book in eligible:
        if book["content_sha256"] in seen_content:
            continue
        seen_content.add(book["content_sha256"])
        for section in book["sections"]:
            source = f"languagerig:{book['source_id']}/{section['location']}"
            documents = [{
                "source": source,
                "text": f"Titel: {book['title']}\nAfsnit: {section['title']}\nKilde: {source}\n\n{text}",
            } for text in chunks(section["text"], 20000)]
            name = digest(source) + ".json"
            write_json(target / name, {"documents": documents, "chunk_size": 800, "overlap": 150})
            files[name] = file_digest(target / name)
            sources.append({"source": source, "source_id": book["source_id"],
                            "title": book["title"], "location": section["location"]})
    manifest = {"format": "languagerig-rag-export/v1", "created_at": now(),
                "files": files, "sources": sources, "published": False}
    write_json(target / "manifest.json", manifest)
    return manifest


def publish_rag(target: Path, *, url: str, token: str) -> dict:
    url = validate_url(url)
    if not token:
        raise LanguageRigError("Set the paired ModelRig token environment variable.")
    manifest = read_json(target / "manifest.json")
    if manifest.get("format") != "languagerig-rag-export/v1":
        raise LanguageRigError("Unsupported RAG export.")
    for name, checksum in manifest["files"].items():
        if not re.fullmatch(r"[0-9a-f]{64}\.json", name) or file_digest(target / name) != checksum:
            raise LanguageRigError("RAG export checksum/name mismatch.")
        payload = read_json(target / name)
        if not isinstance(payload.get("documents"), list) or not payload["documents"]:
            raise LanguageRigError("RAG export has no documents.")
    # Each chapter is one request, so replacement of that source remains atomic.
    receipt = {"format": "languagerig-rag-publish/v1", "started_at": now(),
               "completed_files": [], "status": "publishing"}
    write_json(target / "publish.json", receipt)
    try:
        for name in manifest["files"]:
            request_json(url + "/api/v1/rag/ingest", read_json(target / name), token=token)
            receipt["completed_files"].append(name)
            write_json(target / "publish.json", receipt)
        receipt.update(status="published", completed_at=now())
        write_json(target / "publish.json", receipt)
        return receipt
    except BaseException:
        receipt["status"] = "partial"
        write_json(target / "publish.json", receipt)
        raise


def merge_adapter(run_dir: Path, target: Path, *, execute=False) -> dict:
    run = read_json(run_dir / "run.json")
    if run.get("format") != "languagerig-run/v1" or run.get("status") != "trained":
        raise LanguageRigError("Merge requires a completed LanguageRig training run.")
    if target.exists():
        raise LanguageRigError("Merged model directory already exists.")
    plan = {"format": "languagerig-merge-plan/v1", "model_id": run["config"]["model_id"],
            "resolved_revision": run["resolved_revision"], "output": str(target.resolve()),
            "executed": False, "device": "cpu"}
    if not execute:
        return plan
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise LanguageRigError("Merge needs the languagerig[train] dependencies.") from exc
    base = AutoModelForCausalLM.from_pretrained(plan["model_id"], revision=plan["resolved_revision"],
                                               trust_remote_code=False, dtype=torch.float16, device_map="cpu")
    model = PeftModel.from_pretrained(base, run_dir / "adapter").merge_and_unload()
    model.save_pretrained(target, safe_serialization=True)
    tokenizer = AutoTokenizer.from_pretrained(run_dir / "adapter", trust_remote_code=False)
    tokenizer.save_pretrained(target)
    write_json(target / "languagerig-lineage.json", {
        **plan, "executed": True, "dataset_sha256": run["dataset_sha256"], "merged_at": now(),
    })
    return {**plan, "executed": True}


def package_model(workspace: Path, run_dir: Path, gguf: Path, name: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*:[A-Za-z0-9._-]+", name):
        raise LanguageRigError("Use a local versioned model name, e.g. kaliv-dansk:v1.")
    run = read_json(run_dir / "run.json")
    if run.get("format") != "languagerig-run/v1" or run.get("status") != "trained":
        raise LanguageRigError("Packaging requires a completed LanguageRig training run.")
    with gguf.open("rb") as stream:
        if stream.read(4) != b"GGUF" or int.from_bytes(stream.read(4), "little") not in (2, 3):
            raise LanguageRigError("Expected a GGUF v2/v3 file.")
    target = workspace / "exports" / name.replace(":", "-")
    if target.exists():
        raise LanguageRigError("Model package already exists; use a new version tag.")
    target.mkdir(parents=True)
    shutil.copyfile(gguf, target / "model.gguf")
    (target / "Modelfile").write_text("FROM ./model.gguf\nPARAMETER temperature 0.2\n", encoding="utf-8")
    manifest = {"format": "languagerig-model-package/v1", "created_at": now(), "name": name,
                "model_id": run["config"]["model_id"], "resolved_revision": run["resolved_revision"],
                "dataset_sha256": run["dataset_sha256"], "gguf_sha256": file_digest(target / "model.gguf"),
                "modelfile_sha256": file_digest(target / "Modelfile"), "registered": False,
                "conversion_lineage": "operator_supplied_gguf", "quality_improvement": "not_measured",
                "production_activation": False}
    write_json(target / "manifest.json", manifest)
    return manifest


def register_model(target: Path, url: str) -> dict:
    url = validate_url(url, loopback=True)
    manifest = read_json(target / "manifest.json")
    if (manifest.get("format") != "languagerig-model-package/v1"
            or file_digest(target / "model.gguf") != manifest.get("gguf_sha256")
            or file_digest(target / "Modelfile") != manifest.get("modelfile_sha256")
            or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*:[A-Za-z0-9._-]+", manifest.get("name", ""))):
        raise LanguageRigError("Model package checksum/name mismatch.")
    subprocess.run(["ollama", "create", manifest["name"], "-f", "Modelfile"],
                   cwd=target, env={**os.environ, "OLLAMA_HOST": url}, check=True)
    tags = request_json(url + "/api/tags")
    match = next((model for model in tags.get("models", []) if model.get("name") == manifest["name"]), None)
    if not match or not match.get("digest"):
        raise LanguageRigError("Created model not found in Ollama's model list.")
    manifest.update(registered=True, registered_at=now(), ollama_digest=match["digest"])
    write_json(target / "manifest.json", manifest)
    return manifest
