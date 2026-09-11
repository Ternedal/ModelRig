#!/usr/bin/env python3
"""Deterministic tracked-source LOC metrics for Rig repositories.

Primary metric: nonblank lines in tracked source/config files after explicit
vendor/build/generated/documentation exclusions. Comments are intentionally
included so the metric stays language-agnostic and reproducible without
third-party parsers.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

SOURCE_EXTENSIONS = {
    ".py": "Python",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C/C++ Header",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C/C++ Header",
    ".cs": "C#",
    ".fs": "F#",
    ".fsx": "F#",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".swift": "Swift",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".psd1": "PowerShell",
    ".cmd": "Batch",
    ".bat": "Batch",
    ".sql": "SQL",
    ".proto": "Protocol Buffers",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".vue": "Vue",
    ".svelte": "Svelte",
}

CONFIG_EXTENSIONS = {
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "Config",
    ".conf": "Config",
    ".xml": "XML",
    ".gradle": "Gradle",
    ".properties": "Properties",
    ".csproj": "MSBuild",
    ".fsproj": "MSBuild",
    ".props": "MSBuild",
    ".targets": "MSBuild",
}

SPECIAL_SOURCE_FILES = {
    "dockerfile": "Dockerfile",
    "makefile": "Makefile",
    "rakefile": "Ruby",
}

EXCLUDED_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "docs",
    "documentation",
    "external",
    "generated",
    "node_modules",
    "out",
    "site-packages",
    "third_party",
    "vendor",
    "venv",
}

TEST_DIRS = {"test", "tests", "androidtest", "testdata", "fixtures"}
SCRIPT_DIRS = {"scripts", "tools", "devtools", "ops", "automation"}
SCRIPT_EXTENSIONS = {".sh", ".bash", ".zsh", ".ps1", ".psm1", ".psd1", ".cmd", ".bat"}
EXCLUDED_FILENAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "cargo.lock",
}


def git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return completed.stdout.decode("utf-8", errors="strict")


def tracked_files(root: Path) -> list[PurePosixPath]:
    raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return [PurePosixPath(p.decode("utf-8")) for p in raw.split(b"\0") if p]


def is_excluded(path: PurePosixPath) -> bool:
    lowered_parts = {part.lower() for part in path.parts[:-1]}
    name = path.name.lower()
    if lowered_parts & EXCLUDED_DIRS:
        return True
    if name in EXCLUDED_FILENAMES:
        return True
    if name.endswith((".min.js", ".min.css", ".map")):
        return True
    return False


def language_for(path: PurePosixPath) -> str | None:
    name = path.name.lower()
    if name in SPECIAL_SOURCE_FILES:
        return SPECIAL_SOURCE_FILES[name]
    suffix = path.suffix.lower()
    return SOURCE_EXTENSIONS.get(suffix) or CONFIG_EXTENSIONS.get(suffix)


def is_test(path: PurePosixPath) -> bool:
    parts = {part.lower() for part in path.parts[:-1]}
    name = path.name.lower()
    stem = path.stem.lower()
    original_stem = path.stem
    return bool(
        parts & TEST_DIRS
        or name.startswith("test_")
        or stem.endswith("_test")
        or original_stem.endswith(("Test", "Tests"))
        or ".test." in name
        or ".spec." in name
    )


def category_for(path: PurePosixPath) -> str:
    if is_test(path):
        return "tests"
    suffix = path.suffix.lower()
    parts = {part.lower() for part in path.parts[:-1]}
    if suffix in CONFIG_EXTENSIONS or path.name.lower() in {"dockerfile", "makefile"}:
        return "config"
    if suffix in SCRIPT_EXTENSIONS or parts & SCRIPT_DIRS:
        return "scripts"
    return "product"


def line_counts(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return len(lines), sum(1 for line in lines if line.strip())


def collect(root: Path) -> dict:
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    languages: dict[str, Counter[str]] = defaultdict(Counter)
    totals = Counter()
    skipped_binary = 0

    for rel in tracked_files(root):
        if is_excluded(rel):
            continue
        language = language_for(rel)
        if language is None:
            continue
        counts = line_counts(root / Path(*rel.parts))
        if counts is None:
            skipped_binary += 1
            continue
        physical, nonblank = counts
        category = category_for(rel)
        categories[category].update(files=1, physical=physical, nonblank=nonblank)
        languages[language].update(files=1, physical=physical, nonblank=nonblank)
        totals.update(files=1, physical=physical, nonblank=nonblank)

    commit = git("rev-parse", "HEAD", cwd=root).strip()
    repo_name = Path(git("rev-parse", "--show-toplevel", cwd=root).strip()).name
    return {
        "schema": "rig-loc-metrics@1",
        "repository": repo_name,
        "commit": commit,
        "definition": "tracked nonblank source lines; comments included; docs/vendor/build/generated excluded",
        "totals": dict(totals),
        "categories": {key: dict(categories[key]) for key in ("product", "tests", "scripts", "config")},
        "languages": {
            key: dict(value)
            for key, value in sorted(
                languages.items(), key=lambda item: (-item[1]["nonblank"], item[0].lower())
            )
        },
        "skipped_binary_files": skipped_binary,
    }


def markdown(metrics: dict) -> str:
    lines = [
        f"## LOC metrics — {metrics['repository']}",
        "",
        f"Commit: `{metrics['commit']}`",
        "",
        "Primary metric: **tracked nonblank source lines**. Comments are included; docs, vendor, build and generated directories are excluded.",
        "",
        "| Category | Files | Nonblank | Physical |",
        "|---|---:|---:|---:|",
    ]
    for category in ("product", "tests", "scripts", "config"):
        row = metrics["categories"].get(category, {})
        lines.append(
            f"| {category} | {row.get('files', 0):,} | {row.get('nonblank', 0):,} | {row.get('physical', 0):,} |"
        )
    total = metrics["totals"]
    lines.append(f"| **total** | **{total.get('files', 0):,}** | **{total.get('nonblank', 0):,}** | **{total.get('physical', 0):,}** |")
    lines.extend(["", "### Languages", "", "| Language | Files | Nonblank | Physical |", "|---|---:|---:|---:|"])
    for language, row in metrics["languages"].items():
        lines.append(f"| {language} | {row['files']:,} | {row['nonblank']:,} | {row['physical']:,} |")
    lines.append("")
    return "\n".join(lines)


def self_test() -> None:
    assert is_excluded(PurePosixPath("docs/example.py"))
    assert is_excluded(PurePosixPath("vendor/lib.js"))
    assert is_excluded(PurePosixPath("web/app.min.js"))
    assert language_for(PurePosixPath("worker/app.py")) == "Python"
    assert language_for(PurePosixPath("desktop/App.kt")) == "Kotlin"
    assert category_for(PurePosixPath("tests/test_app.py")) == "tests"
    assert category_for(PurePosixPath("worker/test_router.py")) == "tests"
    assert category_for(PurePosixPath("desktop/FooTest.kt")) == "tests"
    assert category_for(PurePosixPath("worker/latest.py")) == "product"
    assert category_for(PurePosixPath("scripts/check.py")) == "scripts"
    assert category_for(PurePosixPath("deploy.ps1")) == "scripts"
    assert category_for(PurePosixPath(".github/workflows/ci.yml")) == "config"
    assert category_for(PurePosixPath("worker/app.py")) == "product"
    print("loc_metrics self-test: PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", dest="markdown_path", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    root = args.root.resolve()
    metrics = collect(root)
    rendered = markdown(metrics)
    if args.json_path:
        args.json_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_path:
        args.markdown_path.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
