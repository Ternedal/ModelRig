#!/usr/bin/env python3
"""Isolated load and retrieval-quality benchmark for ModelRig RAG.

The benchmark imports the real ``app.rag`` implementation and uses the rig's
configured Ollama embedding model, but writes to a fresh temporary SQLite file.
It never opens the user's RAG database, never synthesizes an answer and removes
each benchmark source before proceeding. The physical rig is only needed for
the later 1k/10k measurement run; dataset generation, scoring and lifecycle are
fully testable in CI.

PowerShell, from the repository root:

    python scripts/rag_benchmark.py `
      --scales 1000,10000 `
      --queries 40 `
      --repetitions 2 `
      --report validation/rag-benchmark-latest.json

The default quality gate is recall@5 >= 95%. Latency is reported but not gated
until the physical baseline establishes a defensible threshold.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

SCHEMA = "kaliv-rag-benchmark/v1"
DATASET_SCHEMA = "kaliv-rag-benchmark-dataset/v1"
DATASET_VERSION = "2026-07-18.2"
DEFAULT_REPORT = Path("validation/rag-benchmark-latest.json")
MAX_TOP_K = 20
CHUNK_SIZE = 4000


class BenchmarkError(RuntimeError):
    """The harness cannot produce a trustworthy result."""


class Engine(Protocol):
    async def ingest(
        self,
        documents: list[dict[str, str]],
        *,
        chunk_size: int,
        overlap: int,
    ) -> tuple[int, int]: ...

    async def query(
        self,
        query: str,
        *,
        top_k: int,
        source: str,
        min_score: float,
    ) -> dict[str, Any]: ...

    def count(self) -> int: ...

    def delete_source(self, source: str) -> int: ...


@dataclass
class CoreEngine:
    """Thin adapter over the production RAG functions and DocStore."""

    store: Any
    rag_module: Any

    async def ingest(
        self,
        documents: list[dict[str, str]],
        *,
        chunk_size: int,
        overlap: int,
    ) -> tuple[int, int]:
        return await self.rag_module.ingest(
            self.store,
            documents,
            chunk_size=chunk_size,
            overlap=overlap,
        )

    async def query(
        self,
        query: str,
        *,
        top_k: int,
        source: str,
        min_score: float,
    ) -> dict[str, Any]:
        return await self.rag_module.query(
            self.store,
            query,
            top_k=top_k,
            synthesize=False,
            source=source,
            min_score=min_score,
        )

    def count(self) -> int:
        return int(self.store.count())

    def delete_source(self, source: str) -> int:
        return int(self.store.delete_source(source))


_FACTS: tuple[tuple[str, str, str], ...] = (
    (
        "backup_interval",
        "Backupjobbet skal køre hvert {value} minut.",
        "Hvor ofte skal backupjobbet køre for {project}?",
    ),
    (
        "retention_days",
        "Logdata skal opbevares i {value} dage.",
        "Hvor mange dage skal logdata gemmes for {project}?",
    ),
    (
        "timeout_seconds",
        "Den godkendte timeout er {value} sekunder.",
        "Hvad er den godkendte timeout for {project}?",
    ),
    (
        "queue_limit",
        "Køen må højst indeholde {value} samtidige elementer.",
        "Hvor mange samtidige elementer må køen indeholde for {project}?",
    ),
    (
        "service_port",
        "Tjenesten lytter på port {value}.",
        "Hvilken port bruger tjenesten i {project}?",
    ),
    (
        "maintenance_hour",
        "Det faste vedligeholdelsesvindue begynder klokken {value}:00.",
        "Hvornår begynder vedligeholdelsesvinduet for {project}?",
    ),
    (
        "replica_count",
        "Driften kræver præcis {value} aktive replikaer.",
        "Hvor mange aktive replikaer kræver {project}?",
    ),
    (
        "batch_size",
        "Den godkendte batchstørrelse er {value} poster.",
        "Hvad er den godkendte batchstørrelse for {project}?",
    ),
)

_PREFIXES = (
    "Aster",
    "Birk",
    "Ceder",
    "Dug",
    "Ege",
    "Fjord",
    "Glimt",
    "Havn",
    "Is",
    "Jern",
    "Klint",
    "Lyn",
    "Mose",
    "Nord",
    "Odin",
    "Pil",
    "Rav",
    "Skov",
    "Tinde",
    "Ugle",
    "Varde",
    "Ymer",
)
_SUFFIXES = (
    "Anker",
    "Bro",
    "Cirkel",
    "Drage",
    "Ekko",
    "Falk",
    "Gran",
    "Horisont",
    "Iris",
    "Jolle",
    "Krone",
    "Lanterne",
    "Mølle",
    "Nøgle",
    "Orkan",
    "Port",
    "Ravn",
    "Stjerne",
    "Tårn",
    "Vinge",
)


def _project_name(index: int) -> str:
    prefix = _PREFIXES[index % len(_PREFIXES)]
    suffix = _SUFFIXES[(index // len(_PREFIXES)) % len(_SUFFIXES)]
    return f"Projekt {prefix}-{suffix}-{index:05d}"


def _fact_value(index: int, kind: str) -> int:
    if kind == "backup_interval":
        return 7 + (index * 11) % 113
    if kind == "retention_days":
        return 14 + (index * 17) % 351
    if kind == "timeout_seconds":
        return 5 + (index * 13) % 296
    if kind == "queue_limit":
        return 20 + (index * 37) % 1981
    if kind == "service_port":
        return 2100 + (index * 97) % 38000
    if kind == "maintenance_hour":
        return index % 24
    if kind == "replica_count":
        return 2 + index % 15
    return 25 + (index * 29) % 1976


def generate_dataset(scale: int, query_count: int, seed: int) -> dict[str, Any]:
    """Generate a stable corpus with known target chunks and distractors."""

    if scale < 1:
        raise BenchmarkError("scale must be positive")
    if query_count < 1:
        raise BenchmarkError("query_count must be positive")
    if query_count > scale:
        raise BenchmarkError("query_count cannot exceed scale")
    if query_count > 200:
        raise BenchmarkError("query_count is capped at 200")

    documents: list[dict[str, str]] = []
    queries: list[dict[str, str]] = []
    for index in range(query_count):
        kind, sentence_template, query_template = _FACTS[index % len(_FACTS)]
        project = _project_name(index)
        value = _fact_value(index, kind)
        marker = f"KALIV-RAG-TARGET-{index:04d}"
        sentence = sentence_template.format(value=value)
        text = (
            f"{marker}. Driftsaftale for {project}. {sentence} "
            "Oplysningen er godkendt og gælder som den autoritative driftsregel."
        )
        documents.append({"text": text})
        queries.append(
            {
                "id": f"q-{index:04d}",
                "category": kind,
                "query": query_template.format(project=project),
                "target_marker": marker,
            }
        )

    for index in range(query_count, scale):
        kind, sentence_template, _ = _FACTS[index % len(_FACTS)]
        # Filler names deliberately use a separate vocabulary. Reusing the
        # target project's human-readable name every 440 documents would turn
        # a 10k benchmark into a test of numeric-token discrimination rather
        # than retrieval under corpus load.
        project = f"Fyldsystem-{index:06d}"
        value = _fact_value(index + seed, kind)
        text = (
            f"DISTRACTOR-{index:06d}. Teknisk driftsnotat for {project}. "
            f"{sentence_template.format(value=value)} "
            "Notatet beskriver alene denne særskilte tjeneste og må ikke blandes "
            "sammen med andre projekters driftsaftaler."
        )
        documents.append({"text": text})

    rng = random.Random(seed + scale * 1009 + query_count * 9176)
    rng.shuffle(documents)
    if any(len(item["text"]) >= CHUNK_SIZE for item in documents):
        raise BenchmarkError("generated document exceeds the one-chunk contract")

    canonical = {
        "schema": DATASET_SCHEMA,
        "version": DATASET_VERSION,
        "scale": scale,
        "query_count": query_count,
        "seed": seed,
        "documents": documents,
        "queries": queries,
    }
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **canonical,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def summarize_numbers(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "min": round(min(values), 3),
        "mean": round(statistics.fmean(values), 3),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": round(max(values), 3),
    }


def _linux_rss_bytes() -> int | None:
    try:
        pages = int(Path("/proc/self/statm").read_text().split()[1])
        return pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def _windows_rss_bytes() -> int | None:
    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
    except (AttributeError, OSError):
        return None
    return int(counters.WorkingSetSize) if ok else None


def process_rss_bytes() -> int | None:
    value = _windows_rss_bytes() or _linux_rss_bytes()
    if value is not None:
        return value
    try:
        import resource

        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return rss if sys.platform == "darwin" else rss * 1024
    except (ImportError, OSError, ValueError):
        return None


def gpu_memory_bytes() -> tuple[int, int] | None:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    try:
        proc = subprocess.run(
            [
                executable,
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    used = total = 0
    try:
        for line in proc.stdout.splitlines():
            left, right = line.split(",", 1)
            used += int(left.strip()) * 1024 * 1024
            total += int(right.strip()) * 1024 * 1024
    except ValueError:
        return None
    return (used, total) if total else None


class ResourceSampler:
    def __init__(self, interval: float = 0.5) -> None:
        self.interval = max(0.1, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.rss_baseline_bytes: int | None = None
        self.rss_peak_bytes: int | None = None
        self.gpu_used_baseline_bytes: int | None = None
        self.gpu_used_peak_bytes: int | None = None
        self.gpu_total_bytes: int | None = None
        self.samples = 0

    def _sample(self) -> None:
        rss = process_rss_bytes()
        if rss is not None:
            if self.rss_baseline_bytes is None:
                self.rss_baseline_bytes = rss
            self.rss_peak_bytes = max(self.rss_peak_bytes or 0, rss)
        gpu = gpu_memory_bytes()
        if gpu is not None:
            used, total = gpu
            if self.gpu_used_baseline_bytes is None:
                self.gpu_used_baseline_bytes = used
            self.gpu_used_peak_bytes = max(self.gpu_used_peak_bytes or 0, used)
            self.gpu_total_bytes = total
        self.samples += 1

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()

    def start(self) -> "ResourceSampler":
        self._sample()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="rag-benchmark-resource-sampler",
        )
        self._thread.start()
        return self

    def stop(self) -> dict[str, int | None]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval * 3))
        self._sample()
        return {
            "samples": self.samples,
            "rss_baseline_bytes": self.rss_baseline_bytes,
            "rss_peak_bytes": self.rss_peak_bytes,
            "rss_delta_peak_bytes": (
                self.rss_peak_bytes - self.rss_baseline_bytes
                if self.rss_peak_bytes is not None
                and self.rss_baseline_bytes is not None
                else None
            ),
            # nvidia-smi reports total device use, not process attribution. The
            # baseline/delta pair makes that limitation explicit and useful.
            "gpu_used_baseline_bytes": self.gpu_used_baseline_bytes,
            "gpu_used_peak_bytes": self.gpu_used_peak_bytes,
            "gpu_used_delta_peak_bytes": (
                self.gpu_used_peak_bytes - self.gpu_used_baseline_bytes
                if self.gpu_used_peak_bytes is not None
                and self.gpu_used_baseline_bytes is not None
                else None
            ),
            "gpu_total_bytes": self.gpu_total_bytes,
        }


SamplerFactory = Callable[[float], ResourceSampler]


def _safe_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
    }


def _evaluate_matches(
    query: dict[str, str],
    matches: Any,
) -> dict[str, Any]:
    if not isinstance(matches, list):
        raise BenchmarkError("RAG response is missing a matches array")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(matches):
        if not isinstance(item, dict):
            raise BenchmarkError(f"matches[{index}] is not an object")
        text = item.get("text")
        score = item.get("score")
        if not isinstance(text, str) or not isinstance(score, (int, float)):
            raise BenchmarkError(f"matches[{index}] has invalid text or score")
        normalized.append({"text": text, "score": float(score)})

    target_marker = query["target_marker"]
    target_rank = next(
        (index + 1 for index, item in enumerate(normalized) if target_marker in item["text"]),
        None,
    )
    target_score = (
        normalized[target_rank - 1]["score"] if target_rank is not None else None
    )
    distractor_scores = [
        item["score"] for item in normalized if target_marker not in item["text"]
    ]
    best_distractor = max(distractor_scores) if distractor_scores else None
    margin = (
        target_score - best_distractor
        if target_score is not None and best_distractor is not None
        else None
    )
    return {
        "target_rank": target_rank,
        "target_score": round(target_score, 6) if target_score is not None else None,
        "best_distractor_score": (
            round(best_distractor, 6) if best_distractor is not None else None
        ),
        "score_margin": round(margin, 6) if margin is not None else None,
        "returned": len(normalized),
    }


def _quality_summary(query_results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in query_results if item.get("error") is None]
    ranks = [item["target_rank"] for item in completed]
    total = len(query_results)
    recall = {
        f"at_{cutoff}": round(
            sum(rank is not None and rank <= cutoff for rank in ranks) / max(1, total),
            6,
        )
        for cutoff in (1, 3, 5, 10, 20)
    }
    reciprocal = [1.0 / rank if rank else 0.0 for rank in ranks]
    margins = [
        float(item["score_margin"])
        for item in completed
        if item.get("score_margin") is not None
    ]
    target_scores = [
        float(item["target_score"])
        for item in completed
        if item.get("target_score") is not None
    ]
    return {
        "queries": total,
        "completed": len(completed),
        "errors": total - len(completed),
        "recall": recall,
        "mean_reciprocal_rank": round(
            sum(reciprocal) / max(1, total),
            6,
        ),
        "target_score": summarize_numbers(target_scores),
        "score_margin": summarize_numbers(margins),
    }


async def run_scale(
    engine: Engine,
    *,
    scale: int,
    query_count: int,
    repetitions: int,
    seed: int,
    sample_interval: float = 0.5,
    sampler_factory: SamplerFactory = ResourceSampler,
) -> dict[str, Any]:
    dataset = generate_dataset(scale, query_count, seed)
    source = f"__kaliv_rag_benchmark_{dataset['sha256'][:20]}"
    documents = [
        {"text": item["text"], "source": source}
        for item in dataset["documents"]
    ]
    result: dict[str, Any] = {
        "scale": scale,
        "dataset": {
            "schema": DATASET_SCHEMA,
            "version": DATASET_VERSION,
            "sha256": dataset["sha256"],
            "seed": seed,
            "queries": query_count,
        },
        "source_namespace": source,
        "ingest": None,
        "query_runs": [],
        "quality": None,
        "latency_ms": None,
        "resources": None,
        "cleanup": None,
        "error": None,
    }
    sampler = sampler_factory(sample_interval).start()
    try:
        before = engine.count()
        if before != 0:
            raise BenchmarkError(
                f"isolated benchmark store is not empty before scale {scale}: {before} chunks"
            )
        started = time.perf_counter()
        added, replaced = await engine.ingest(
            documents,
            chunk_size=CHUNK_SIZE,
            overlap=0,
        )
        ingest_ms = (time.perf_counter() - started) * 1000
        after = engine.count()
        if added != scale or replaced != 0 or after != scale:
            raise BenchmarkError(
                "one-chunk ingest contract failed: "
                f"added={added}, replaced={replaced}, store={after}, expected={scale}"
            )
        result["ingest"] = {
            "duration_ms": round(ingest_ms, 3),
            "chunks_added": added,
            "chunks_replaced": replaced,
            "chunks_per_second": round(scale / max(ingest_ms / 1000, 0.000001), 3),
        }

        query_runs: list[dict[str, Any]] = []
        for repetition in range(repetitions):
            for query in dataset["queries"]:
                started = time.perf_counter()
                item: dict[str, Any] = {
                    "id": query["id"],
                    "category": query["category"],
                    "repetition": repetition + 1,
                    "latency_ms": None,
                    "target_rank": None,
                    "target_score": None,
                    "best_distractor_score": None,
                    "score_margin": None,
                    "returned": 0,
                    "error": None,
                }
                try:
                    response = await engine.query(
                        query["query"],
                        top_k=MAX_TOP_K,
                        source=source,
                        min_score=0.0,
                    )
                    item.update(_evaluate_matches(query, response.get("matches")))
                except Exception as exc:
                    item["error"] = _safe_error(exc)
                item["latency_ms"] = round(
                    (time.perf_counter() - started) * 1000,
                    3,
                )
                query_runs.append(item)
        result["query_runs"] = query_runs
        result["quality"] = _quality_summary(query_runs)
        result["latency_ms"] = summarize_numbers(
            [float(item["latency_ms"]) for item in query_runs]
        )
    except Exception as exc:
        result["error"] = _safe_error(exc)
    finally:
        cleanup_error = None
        try:
            removed = engine.delete_source(source)
            remaining = engine.count()
        except Exception as exc:
            removed = None
            remaining = None
            cleanup_error = _safe_error(exc)
        result["cleanup"] = {
            "removed_chunks": removed,
            "remaining_chunks": remaining,
            "clean": cleanup_error is None and remaining == 0,
            "error": cleanup_error,
        }
        result["resources"] = sampler.stop()
    return result


def summarize_benchmark(scales: list[dict[str, Any]]) -> dict[str, Any]:
    errors = sum(
        item.get("error") is not None
        or not (item.get("cleanup") or {}).get("clean", False)
        or (item.get("quality") or {}).get("errors", 1) > 0
        for item in scales
    )
    recalls = [
        float(item["quality"]["recall"]["at_5"])
        for item in scales
        if item.get("quality") is not None
    ]
    p95s = [
        float(item["latency_ms"]["p95"])
        for item in scales
        if item.get("latency_ms") and item["latency_ms"].get("p95") is not None
    ]
    return {
        "scales": len(scales),
        "errors": errors,
        "minimum_recall_at_5": round(min(recalls), 6) if recalls else None,
        "maximum_query_p95_ms": round(max(p95s), 3) if p95s else None,
    }


def _git_sha(root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else None


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temp = Path(handle.name)
    temp.replace(path)


def _parse_scales(raw: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scales must be comma-separated integers") from exc
    if not values or any(value < 1 for value in values):
        raise argparse.ArgumentTypeError("scales must contain positive integers")
    if len(values) != len(set(values)):
        raise argparse.ArgumentTypeError("scales must not contain duplicates")
    return values


async def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = Path(__file__).resolve().parents[1]
    worker = root / "worker"
    sys.path.insert(0, str(worker))

    with tempfile.TemporaryDirectory(prefix="kaliv-rag-benchmark-") as temp_dir:
        db_path = Path(temp_dir) / "rag-benchmark.db"
        from app import ollama_client as oc
        from app import rag
        from app.store import DocStore

        warmup_started = time.perf_counter()
        try:
            warmup_embedding = await oc.embed("Kaliv RAG benchmark warmup")
        except Exception as exc:
            report = {
                "schema": SCHEMA,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "error": _safe_error(exc),
                "summary": {"scales": 0, "errors": 1},
            }
            return report, 2
        warmup_ms = (time.perf_counter() - warmup_started) * 1000

        scales: list[dict[str, Any]] = []
        with DocStore(str(db_path)) as store:
            engine = CoreEngine(store, rag)
            for scale in args.scales:
                print(f"RAG benchmark: scale={scale} chunks")
                item = await run_scale(
                    engine,
                    scale=scale,
                    query_count=args.queries,
                    repetitions=args.repetitions,
                    seed=args.seed,
                    sample_interval=args.sample_interval,
                )
                scales.append(item)
                quality = item.get("quality") or {}
                recall = (quality.get("recall") or {}).get("at_5")
                p95 = (item.get("latency_ms") or {}).get("p95")
                print(f"  recall@5={recall} query_p95_ms={p95} error={item.get('error')}")

        summary = summarize_benchmark(scales)
        report = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset_schema": DATASET_SCHEMA,
            "dataset_version": DATASET_VERSION,
            "isolation": {
                "temporary_database": True,
                "user_index_opened": False,
                "synthesis_enabled": False,
            },
            "build": {
                "version": (root / "VERSION").read_text(encoding="utf-8").strip(),
                "git_sha": _git_sha(root),
            },
            "host": {
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "ollama": {
                "url": oc.OLLAMA_URL,
                "embedding_model": oc.EMBED_MODEL,
                "embedding_dimensions": len(warmup_embedding),
                "warmup_ms": round(warmup_ms, 3),
            },
            "configuration": {
                "scales": args.scales,
                "queries": args.queries,
                "repetitions": args.repetitions,
                "seed": args.seed,
                "top_k": MAX_TOP_K,
                "min_score": 0.0,
                "chunk_size": CHUNK_SIZE,
                "overlap": 0,
            },
            "scales": scales,
            "summary": summary,
        }
        gate_ok = (
            summary["errors"] == 0
            and summary["minimum_recall_at_5"] is not None
            and summary["minimum_recall_at_5"] >= args.fail_under_recall_at_5
        )
        if args.max_p95_ms > 0:
            gate_ok = gate_ok and (
                summary["maximum_query_p95_ms"] is not None
                and summary["maximum_query_p95_ms"] <= args.max_p95_ms
            )
        report["gate"] = {
            "passed": gate_ok,
            "fail_under_recall_at_5": args.fail_under_recall_at_5,
            "max_p95_ms": args.max_p95_ms if args.max_p95_ms > 0 else None,
        }
        return report, 0 if gate_ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scales", type=_parse_scales, default=_parse_scales("1000,10000"))
    parser.add_argument("--queries", type=int, default=40)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--fail-under-recall-at-5", type=float, default=0.95)
    parser.add_argument(
        "--max-p95-ms",
        type=float,
        default=0.0,
        help="optional query p95 gate; 0 reports latency without gating it",
    )
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("MODELRIG_OLLAMA_URL", "http://127.0.0.1:11434"),
    )
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("MODELRIG_EMBED_MODEL", "nomic-embed-text"),
    )
    args = parser.parse_args(argv)
    if args.queries < 1 or args.queries > 200:
        parser.error("--queries must be between 1 and 200")
    if args.repetitions < 1 or args.repetitions > 20:
        parser.error("--repetitions must be between 1 and 20")
    if any(scale < args.queries for scale in args.scales):
        parser.error("every scale must be at least as large as --queries")
    if not 0.0 <= args.fail_under_recall_at_5 <= 1.0:
        parser.error("--fail-under-recall-at-5 must be between 0 and 1")
    if args.max_p95_ms < 0:
        parser.error("--max-p95-ms cannot be negative")
    if args.sample_interval <= 0:
        parser.error("--sample-interval must be positive")
    if any(scale > 100_000 for scale in args.scales):
        parser.error("scales above 100,000 require an explicit harness revision")
    if not args.ollama_url.strip():
        parser.error("--ollama-url cannot be empty")

    os.environ["MODELRIG_OLLAMA_URL"] = args.ollama_url.strip().rstrip("/")
    os.environ["MODELRIG_EMBED_MODEL"] = args.embedding_model.strip()
    if not os.environ["MODELRIG_EMBED_MODEL"]:
        parser.error("--embedding-model cannot be empty")

    try:
        report, exit_code = asyncio.run(_run(args))
    except Exception as exc:
        # A benchmark that crashes before writing its evidence is impossible to
        # diagnose remotely. Emit the same bounded error shape as scale failures
        # and reserve exit 2 for harness/environment failure.
        report = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "configuration": {
                "scales": args.scales,
                "queries": args.queries,
                "repetitions": args.repetitions,
                "seed": args.seed,
            },
            "error": _safe_error(exc),
            "summary": {"scales": 0, "errors": 1},
            "gate": {
                "passed": False,
                "fail_under_recall_at_5": args.fail_under_recall_at_5,
                "max_p95_ms": args.max_p95_ms if args.max_p95_ms > 0 else None,
            },
        }
        exit_code = 2
    _write_json_atomic(args.report, report)
    print(f"report: {args.report}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
