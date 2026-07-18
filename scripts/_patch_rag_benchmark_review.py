#!/usr/bin/env python3
from pathlib import Path


def exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one target, found {count}")
    return text.replace(old, new)


script_path = Path("scripts/rag_benchmark.py")
text = script_path.read_text(encoding="utf-8")
text = exact(
    text,
    'DATASET_VERSION = "2026-07-18.1"',
    'DATASET_VERSION = "2026-07-18.2"',
    "dataset version",
)
text = exact(
    text,
    '''    for index in range(query_count, scale):
        kind, sentence_template, _ = _FACTS[index % len(_FACTS)]
        project = _project_name(index)
        value = _fact_value(index + seed, kind)''',
    '''    for index in range(query_count, scale):
        kind, sentence_template, _ = _FACTS[index % len(_FACTS)]
        # Filler names deliberately use a separate vocabulary. Reusing the
        # target project's human-readable name every 440 documents would turn
        # a 10k benchmark into a test of numeric-token discrimination rather
        # than retrieval under corpus load.
        project = f"Fyldsystem-{index:06d}"
        value = _fact_value(index + seed, kind)''',
    "filler namespace",
)
text = exact(
    text,
    '''        self.rss_peak_bytes: int | None = None
        self.gpu_used_peak_bytes: int | None = None
        self.gpu_total_bytes: int | None = None''',
    '''        self.rss_baseline_bytes: int | None = None
        self.rss_peak_bytes: int | None = None
        self.gpu_used_baseline_bytes: int | None = None
        self.gpu_used_peak_bytes: int | None = None
        self.gpu_total_bytes: int | None = None''',
    "resource baseline fields",
)
text = exact(
    text,
    '''        rss = process_rss_bytes()
        if rss is not None:
            self.rss_peak_bytes = max(self.rss_peak_bytes or 0, rss)
        gpu = gpu_memory_bytes()
        if gpu is not None:
            used, total = gpu
            self.gpu_used_peak_bytes = max(self.gpu_used_peak_bytes or 0, used)
            self.gpu_total_bytes = total''',
    '''        rss = process_rss_bytes()
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
            self.gpu_total_bytes = total''',
    "resource baseline sampling",
)
text = exact(
    text,
    '''        return {
            "samples": self.samples,
            "rss_peak_bytes": self.rss_peak_bytes,
            "gpu_used_peak_bytes": self.gpu_used_peak_bytes,
            "gpu_total_bytes": self.gpu_total_bytes,
        }''',
    '''        return {
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
        }''',
    "resource report",
)
text = exact(
    text,
    '''    if args.sample_interval <= 0:
        parser.error("--sample-interval must be positive")

    os.environ["MODELRIG_OLLAMA_URL"] = args.ollama_url.strip().rstrip("/")''',
    '''    if args.sample_interval <= 0:
        parser.error("--sample-interval must be positive")
    if any(scale > 100_000 for scale in args.scales):
        parser.error("scales above 100,000 require an explicit harness revision")
    if not args.ollama_url.strip():
        parser.error("--ollama-url cannot be empty")

    os.environ["MODELRIG_OLLAMA_URL"] = args.ollama_url.strip().rstrip("/")''',
    "CLI validation",
)
text = exact(
    text,
    '''    report, exit_code = asyncio.run(_run(args))
    _write_json_atomic(args.report, report)
    print(f"report: {args.report}")
    return exit_code''',
    '''    try:
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
    return exit_code''',
    "top-level failure report",
)
script_path.write_text(text, encoding="utf-8")


test_path = Path("tests/worker_rag_benchmark.py")
test = test_path.read_text(encoding="utf-8")
test = exact(
    test,
    '''check(
    all(len(item["text"]) < rb.CHUNK_SIZE for item in d1["documents"]),
    "every generated document is structurally one chunk",
)''',
    '''check(
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
)''',
    "dataset namespace tests",
)
test = exact(
    test,
    '''    def stop(self):
        self.stopped += 1
        return {
            "samples": 2,
            "rss_peak_bytes": 1234,
            "gpu_used_peak_bytes": None,
            "gpu_total_bytes": None,
        }''',
    '''    def stop(self):
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
        }''',
    "noop resource report",
)
test = exact(
    test,
    '''    check(scale_result["resources"]["rss_peak_bytes"] == 1234, "resource sampler result reaches the report")''',
    '''    check(scale_result["resources"]["rss_peak_bytes"] == 1234, "resource sampler result reaches the report")
    check(scale_result["resources"]["rss_delta_peak_bytes"] == 234, "resource delta reaches the report")''',
    "resource delta assertion",
)
anchor = '''check("synthesize=False" in source_text, "production CoreEngine structurally disables synthesis")

print(f"\\n===== RAG BENCHMARK: {passed} passed, {failed} failed =====")'''
insert = '''check("synthesize=False" in source_text, "production CoreEngine structurally disables synthesis")

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

print(f"\\n===== RAG BENCHMARK: {passed} passed, {failed} failed =====")'''
test = exact(test, anchor, insert, "top-level failure regression")
test_path.write_text(test, encoding="utf-8")

Path("scripts/_patch_rag_benchmark_review.py").unlink()
print("patched final RAG benchmark review findings")
