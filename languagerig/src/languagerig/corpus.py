"""Immutable corpora split by work, with exact content/passages deduplicated."""
from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from .core import LanguageRigError, books, digest, file_digest, jsonl, now, read_json, write_json, write_jsonl

SPLITS = ("train", "validation", "test")


def chunks(text: str, size: int):
    if size < 200:
        raise LanguageRigError("Chunk size must be at least 200 characters.")
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary < 0:
                boundary = text.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            yield piece
        start = end


def grouped_sources(selected: list[dict]) -> list[list[dict]]:
    """Connect both equal work IDs and equal normalized full-book hashes."""
    parents = {book["source_id"]: book["source_id"] for book in selected}
    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key
    seen = {}
    for book in selected:
        for key in (("work", book["work_id"]), ("content", book["content_sha256"])):
            if key in seen:
                parents[root(book["source_id"])] = root(seen[key])
            else:
                seen[key] = book["source_id"]
    groups = defaultdict(list)
    for book in selected:
        groups[root(book["source_id"])].append(book)
    return sorted(groups.values(), key=lambda group: min(b["source_id"] for b in group))


def _instruction_rows(path: Path, split_by_source: dict[str, str]) -> list[dict]:
    result = []
    for number, row in enumerate(jsonl(path), 1):
        if row.get("reviewed") is not True:
            raise LanguageRigError(f"Instruction {number} has not been reviewed.")
        sources = row.get("source_ids")
        if not isinstance(sources, list) or not sources or any(s not in split_by_source for s in sources):
            raise LanguageRigError(f"Instruction {number} must reference eligible source_ids.")
        splits = {split_by_source[source_id] for source_id in sources}
        if len(splits) != 1:
            raise LanguageRigError(f"Instruction {number} crosses corpus splits.")
        messages = row.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            raise LanguageRigError(f"Instruction {number} needs user/assistant messages.")
        roles = []
        for message in messages:
            if (not isinstance(message, dict) or message.get("role") not in ("system", "user", "assistant")
                    or not isinstance(message.get("content"), str) or not message["content"].strip()):
                raise LanguageRigError(f"Instruction {number} has an invalid message.")
            roles.append(message["role"])
        dialogue = roles[1:] if roles[0] == "system" else roles
        if dialogue != ["user" if i % 2 == 0 else "assistant" for i in range(len(dialogue))] or dialogue[-1] != "assistant":
            raise LanguageRigError(f"Instruction {number} must alternate user/assistant and end with assistant.")
        result.append({"source_ids": sources, "messages": messages, "split": splits.pop(), "reviewed": True})
    return result


def build_dataset(workspace: Path, name: str, *, seed=42, validation_fraction=0.15,
                  test_fraction=0.15, chunk_chars=6000, genre=None, topic=None,
                  instructions: Path | None = None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}", name):
        raise LanguageRigError("Dataset name must be a simple filename.")
    if (not math.isfinite(validation_fraction) or not math.isfinite(test_fraction)
            or not 0 < validation_fraction < 1 or not 0 < test_fraction < 1
            or validation_fraction + test_fraction >= 1):
        raise LanguageRigError("Validation/test fractions must be positive and sum to less than one.")
    if chunk_chars < 200:
        raise LanguageRigError("Chunk size must be at least 200 characters.")
    selected, excluded = [], []
    for book in books(workspace):
        reason = None
        if not book.get("training_allowed"):
            reason = "training_not_selected"
        elif not book.get("quality_accepted"):
            reason = "quality_review_required"
        elif book.get("language", "").lower().split("-")[0] != "da":
            reason = "language_not_danish"
        elif genre and book.get("genre") != genre:
            reason = "genre_filter"
        elif topic and topic not in book.get("topics", []):
            reason = "topic_filter"
        if reason:
            excluded.append({"source_id": book["source_id"], "reason": reason})
        else:
            selected.append(book)
    groups = grouped_sources(selected)
    if len(groups) < 3:
        raise LanguageRigError("Need at least three eligible distinct works for train/validation/test.")
    random.Random(seed).shuffle(groups)
    n_test = max(1, int(len(groups) * test_fraction))
    n_validation = max(1, int(len(groups) * validation_fraction))
    if n_test + n_validation >= len(groups):
        raise LanguageRigError("Split fractions leave no training works.")
    split_by_source = {}
    for index, group in enumerate(groups):
        split = "test" if index < n_test else "validation" if index < n_test + n_validation else "train"
        split_by_source.update({book["source_id"]: split for book in group})
    rows = []
    duplicate_books = []
    seen_books = set()
    if instructions:
        rows = _instruction_rows(instructions, split_by_source)
    else:
        for book in selected:
            if book["content_sha256"] in seen_books:
                duplicate_books.append(book["source_id"])
                continue
            seen_books.add(book["content_sha256"])
            for section in book["sections"]:
                for index, text in enumerate(chunks(section["text"], chunk_chars)):
                    rows.append({"source_id": book["source_id"], "work_id": book["work_id"],
                                 "title": book["title"], "location": section["location"],
                                 "genre": book["genre"], "topics": book["topics"], "part": index,
                                 "text": text, "split": split_by_source[book["source_id"]]})
    # Shared boilerplate/repeated passages must not bridge held-out splits.
    row_key = lambda row: digest(" ".join(row["text"].split()) if "text" in row
                                else json.dumps(row["messages"], ensure_ascii=False, sort_keys=True))
    locations = defaultdict(set)
    for row in rows:
        locations[row_key(row)].add(row["split"])
    clean = {split: [] for split in SPLITS}
    seen_rows, removed = set(), 0
    for row in rows:
        key = row_key(row)
        if len(locations[key]) > 1 or key in seen_rows:
            removed += 1
            continue
        seen_rows.add(key)
        clean[row["split"]].append({k: v for k, v in row.items() if k != "split"})
    if any(not clean[split] for split in SPLITS):
        raise LanguageRigError("A split is empty after deduplication; add more varied material/examples.")
    target = workspace / "datasets" / name
    if target.exists():
        raise LanguageRigError("Dataset already exists; create a new named snapshot.")
    temporary = Path(tempfile.mkdtemp(prefix="." + name + "-", dir=workspace / "datasets"))
    try:
        files = {}
        for split in SPLITS:
            path = temporary / f"{split}.jsonl"
            write_jsonl(path, clean[split])
            files[path.name] = file_digest(path)
        manifest = {"format": "languagerig-dataset/v1", "created_at": now(),
                    "mode": "instruction" if instructions else "text", "seed": seed,
                    "validation_fraction": validation_fraction, "test_fraction": test_fraction,
                    "chunk_chars": chunk_chars, "genre_filter": genre, "topic_filter": topic,
                    "split_by_source": split_by_source,
                    "sources": [{"source_id": b["source_id"], "work_id": b["work_id"],
                                 "content_sha256": b["content_sha256"], "title": b["title"],
                                 "genre": b["genre"], "language": b["language"]} for b in selected],
                    "excluded": excluded, "duplicate_books_removed": duplicate_books,
                    "duplicate_passages_removed": removed,
                    "counts": {split: len(clean[split]) for split in SPLITS}, "files": files}
        manifest["dataset_sha256"] = digest(json.dumps(
            {k: v for k, v in manifest.items() if k != "created_at"}, sort_keys=True, ensure_ascii=False))
        write_json(temporary / "manifest.json", manifest)
        os.rename(temporary, target)
        return manifest
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def verify_dataset(path: Path) -> dict:
    manifest = read_json(path / "manifest.json")
    if manifest.get("format") != "languagerig-dataset/v1" or manifest.get("mode") not in ("text", "instruction"):
        raise LanguageRigError("Unsupported dataset format/mode.")
    expected = digest(json.dumps(
        {k: v for k, v in manifest.items() if k not in ("created_at", "dataset_sha256")},
        sort_keys=True, ensure_ascii=False))
    if expected != manifest.get("dataset_sha256"):
        raise LanguageRigError("Dataset manifest checksum mismatch.")
    actual_counts, seen, observed_splits = {}, {}, {}
    for split in SPLITS:
        name = f"{split}.jsonl"
        file = path / name
        if file_digest(file) != manifest.get("files", {}).get(name):
            raise LanguageRigError(f"Dataset changed: {name}.")
        count = 0
        for row in jsonl(file):
            count += 1
            sources = row.get("source_ids", [row.get("source_id")])
            if not sources or any(manifest["split_by_source"].get(s) != split for s in sources):
                raise LanguageRigError("Dataset row crosses source splits.")
            key = digest(" ".join(row["text"].split()) if "text" in row else
                         json.dumps(row["messages"], ensure_ascii=False, sort_keys=True))
            if key in seen:
                raise LanguageRigError("Duplicate passage in dataset.")
            seen[key] = split
            for source in sources:
                observed_splits[source] = split
        if count == 0 or count != manifest["counts"][split]:
            raise LanguageRigError("Dataset row count mismatch/empty split.")
        actual_counts[split] = count
    work_splits, content_splits = defaultdict(set), defaultdict(set)
    for source in manifest["sources"]:
        split = manifest["split_by_source"][source["source_id"]]
        work_splits[source["work_id"]].add(split)
        content_splits[source["content_sha256"]].add(split)
    if any(len(s) != 1 for s in list(work_splits.values()) + list(content_splits.values())):
        raise LanguageRigError("A work or duplicate book crosses source splits.")
    return manifest
