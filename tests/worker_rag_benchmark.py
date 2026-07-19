#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
sys.path.insert(0, str(WORKER))

spec = importlib.util.spec_from_file_location(
    "rag_benchmark",
    ROOT / "scripts" / "rag_benchmark.py",
)
rb = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rb
spec.loader.exec_module(rb)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def run(coro):
    return asyncio.run(coro)


# Dataset generation is frozen, exact-sized and cheap enough to validate at the
# real acceptance scale without contacting Ollama.
d1 = rb.generate_dataset(10_000, 40, 20260718)
d2 = rb.generate_dataset(10_000, 40, 20260718)
check(d1["schema"] == rb.DATASET_SCHEMA, "dataset uses the versioned schema")
check(d1["sha256"] == d2["sha256"], "10k dataset hash is deterministic")
check(d1["documents"] == d2["documents"], "10k document order is deterministic")
check(len(d1["documents"]) == 10_000, "10k scale generates exactly 10,000 documents")
check(len(d1["queries"]) == 40, "default benchmark has 40 known-answer queries")
check(
    len({q["target_marker"] for q in d1["queries"]}) == 40,
    "every quality query has a unique target marker",
)
check(
    all(len(item["text"]) < rb.CHUNK_SIZE for item in d1["documents"]),
    "every generated document is structurally one chunk",
)
check(
    sum("Driftsaftale for Projekt" in item["text"] for item in d1["documents"]) == 40,
    "only known-answer chunks use the target project vocabulary",
)
check(
    all(
        "Fyldsystem-" in item["text"]
        for item in d1["documents"]
        if item["text"].startswith("DISTRACTOR-")
    ),
    "10k distractors have a separate deterministic namespace",
)
canonical = {
    key: d1[key]
    for key in ("schema", "version", "scale", "query_count", "seed", "documents", "queries")
}
expected_hash = hashlib.sha256(
    json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
check(d1["sha256"] == expected_hash, "dataset hash binds corpus and query truth")

for bad in ((0, 1), (10, 0), (10, 11), (500, 201)):
    try:
        rb.generate_dataset(bad[0], bad[1], 1)
    except rb.BenchmarkError:
        ok = True
    else:
        ok = False
    check(ok, f"invalid dataset dimensions fail closed: scale={bad[0]} queries={bad[1]}")

check(rb._percentile([1, 2, 3, 4], 0.50) == 2, "p50 uses nearest-rank semantics")
check(rb._percentile([1, 2, 3, 4], 0.95) == 4, "p95 uses nearest-rank semantics")
check(rb._parse_scales("1000,10000") == [1000, 10000], "scale parser preserves explicit order")


class NoopSampler:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        return self

    def stop(self):
        self.stopped += 1
        return {
            "samples": 2,
            "rss_baseline_bytes": 1000,
            "rss_peak_bytes": 1234,
            "rss_delta_peak_bytes": 234,
            "gpu_used_baseline_bytes": None,
            "gpu_used_peak_bytes": None,
            "gpu_used_delta_peak_bytes": None,
            "gpu_total_bytes": None,
        }


# Drive the production chunk/embed/store/cosine functions with a deterministic
# embedding stub. chat() is a bomb: synthesize=False must make it unreachable.
from app import ollama_client as oc
from app import rag
from app.store import DocStore

old_embed = oc.embed
old_chat = oc.chat


async def fake_embed(text: str, model=None):
    vector = [0.0] * 512
    match = re.search(r"Projekt [A-Za-zÆØÅæøå-]+-(\d{5})", text)
    if match:
        vector[int(match.group(1)) % 440] = 10.0
    lowered = text.lower()
    for index, token in enumerate(
        (
            "backup",
            "logdata",
            "timeout",
            "køen",
            "port",
            "vedligeholdelse",
            "replikaer",
            "batch",
        )
    ):
        if token in lowered:
            vector[450 + index] = 1.0
    if not any(vector):
        vector[511] = 1.0
    return vector


async def forbidden_chat(*_args, **_kwargs):
    raise AssertionError("benchmark must never synthesize an answer")


oc.embed = fake_embed
oc.chat = forbidden_chat
try:
    with tempfile.TemporaryDirectory(prefix="rag-benchmark-test-") as td:
        db = Path(td) / "isolated.db"
        with DocStore(str(db)) as store:
            engine = rb.CoreEngine(store, rag)
            scale_result = run(
                rb.run_scale(
                    engine,
                    scale=120,
                    query_count=12,
                    repetitions=2,
                    seed=20260718,
                    sampler_factory=NoopSampler,
                )
            )
            check(scale_result["error"] is None, "real RAG core completes the fake-embedding benchmark")
            check(scale_result["ingest"]["chunks_added"] == 120, "real ingest adds one chunk per document")
            check(scale_result["quality"]["recall"]["at_1"] == 1.0, "known targets achieve deterministic recall@1")
            check(scale_result["quality"]["recall"]["at_5"] == 1.0, "known targets achieve deterministic recall@5")
            check(scale_result["quality"]["mean_reciprocal_rank"] == 1.0, "MRR scoring uses returned ranks")
            check(len(scale_result["query_runs"]) == 24, "repetitions multiply the query set exactly")
            check(scale_result["latency_ms"]["p50"] is not None, "query latency summary is populated")
            check(scale_result["resources"]["rss_peak_bytes"] == 1234, "resource sampler result reaches the report")
            check(scale_result["resources"]["rss_delta_peak_bytes"] == 234, "resource delta reaches the report")
            check(scale_result["cleanup"]["removed_chunks"] == 120, "benchmark source is deleted after measurement")
            check(scale_result["cleanup"]["remaining_chunks"] == 0, "isolated store is empty after success")
            check(store.count() == 0, "no benchmark chunk survives successful cleanup")
finally:
    oc.embed = old_embed
    oc.chat = old_chat


class FailingEngine:
    def __init__(self) -> None:
        self.chunks = 0
        self.deleted_sources: list[str] = []

    async def ingest(self, documents, *, chunk_size, overlap):
        self.chunks = len(documents)
        return self.chunks, 0

    async def query(self, query, *, top_k, source, min_score):
        raise RuntimeError("simulated retrieval failure")

    def count(self):
        return self.chunks

    def delete_source(self, source):
        self.deleted_sources.append(source)
        removed = self.chunks
        self.chunks = 0
        return removed


failing = FailingEngine()
failure_result = run(
    rb.run_scale(
        failing,
        scale=20,
        query_count=4,
        repetitions=1,
        seed=99,
        sampler_factory=NoopSampler,
    )
)
check(failure_result["quality"]["errors"] == 4, "per-query failures are counted, not hidden")
check(failure_result["cleanup"]["clean"], "query failure still performs clean source removal")
check(len(failing.deleted_sources) == 1, "failure cleanup deletes exactly the benchmark namespace")
check(failing.chunks == 0, "failure cleanup leaves no chunks")
check(
    all("simulated retrieval failure" in item["error"]["message"] for item in failure_result["query_runs"]),
    "bounded query errors remain diagnosable",
)

summary = rb.summarize_benchmark([scale_result, failure_result])
check(summary["errors"] == 1, "aggregate summary marks a scale with query failures")
check(summary["minimum_recall_at_5"] == 0.0, "failed queries count against recall instead of disappearing")

with tempfile.TemporaryDirectory(prefix="rag-report-test-") as td:
    report_path = Path(td) / "nested" / "report.json"
    rb._write_json_atomic(report_path, {"schema": rb.SCHEMA, "value": "blå"})
    parsed = json.loads(report_path.read_text(encoding="utf-8"))
    leftovers = list(report_path.parent.glob(report_path.name + ".*.tmp"))
    check(parsed == {"schema": rb.SCHEMA, "value": "blå"}, "atomic writer preserves UTF-8 JSON")
    check(not leftovers, "atomic writer leaves no temporary report file")

source_text = (ROOT / "scripts" / "rag_benchmark.py").read_text(encoding="utf-8")
check("/api/v1/" not in source_text, "harness bypasses the user-facing index API")
check("Authorization" not in source_text, "harness never needs or handles a device token")
check("TemporaryDirectory" in source_text and "DocStore(str(db_path))" in source_text,
      "entrypoint structurally binds the real core to a temporary database")
check("synthesize=False" in source_text, "production CoreEngine structurally disables synthesis")

# A pre-scale harness crash must still produce a bounded machine-readable report.
old_run = rb._run
old_ollama_url = os.environ.get("MODELRIG_OLLAMA_URL")
old_embed_model = os.environ.get("MODELRIG_EMBED_MODEL")


async def explode(_args):
    raise RuntimeError("simulated top-level harness failure")


rb._run = explode
try:
    with tempfile.TemporaryDirectory(prefix="rag-main-failure-") as td:
        failure_report = Path(td) / "failure.json"
        exit_code = rb.main(
            [
                "--scales",
                "1",
                "--queries",
                "1",
                "--repetitions",
                "1",
                "--report",
                str(failure_report),
            ]
        )
        failure_json = json.loads(failure_report.read_text(encoding="utf-8"))
        check(exit_code == 2, "top-level harness failure uses reserved exit 2")
        check(failure_json["gate"]["passed"] is False, "top-level failure report fails the gate")
        check(
            failure_json["error"]["message"] == "simulated top-level harness failure",
            "top-level failure remains diagnosable in the report",
        )
finally:
    rb._run = old_run
    if old_ollama_url is None:
        os.environ.pop("MODELRIG_OLLAMA_URL", None)
    else:
        os.environ["MODELRIG_OLLAMA_URL"] = old_ollama_url
    if old_embed_model is None:
        os.environ.pop("MODELRIG_EMBED_MODEL", None)
    else:
        os.environ["MODELRIG_EMBED_MODEL"] = old_embed_model

# Warmup/model failures are expected environment failures and must still
# emit the same complete evidence envelope as successful runs.
from app import ollama_client as warmup_oc

old_warmup_embed = warmup_oc.embed


async def fail_warmup(_text, model=None):
    raise RuntimeError("simulated missing embedding model")


warmup_oc.embed = fail_warmup
try:
    warmup_report, warmup_exit = run(
        rb._run(
            SimpleNamespace(
                scales=[1],
                queries=1,
                repetitions=1,
                seed=20260718,
                sample_interval=0.5,
                fail_under_recall_at_5=0.95,
                max_p95_ms=0.0,
            )
        )
    )
    check(warmup_exit == 2, "warmup failure uses reserved environment exit 2")
    check(warmup_report["gate"]["passed"] is False, "warmup failure explicitly fails the gate")
    check(warmup_report["scales"] == [], "warmup failure records that no scale ran")
    check(
        warmup_report["ollama"]["embedding_dimensions"] is None,
        "warmup failure keeps unknown dimensions explicit",
    )
    check(
        warmup_report["error"]["message"] == "simulated missing embedding model",
        "warmup failure remains diagnosable",
    )
    check(
        warmup_report["isolation"]["user_index_opened"] is False,
        "warmup failure still proves the user index was untouched",
    )
finally:
    warmup_oc.embed = old_warmup_embed

print(f"\n===== RAG BENCHMARK: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
