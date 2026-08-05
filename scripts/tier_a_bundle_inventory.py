#!/usr/bin/env python3
"""Generate the exact, reviewable Tier-A authority-bundle inventory."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

SCHEMA = "kaliv-tier-a-bundle-inventory/v1"
BUNDLE_SOURCE = "devcontrol/src/kaliv_dev_control/tier_a_authority.py"
SNAPSHOT_PATH = "devcontrol/TIER_A_BUNDLE_INVENTORY.json"
MARKDOWN_PATH = "devcontrol/TIER_A_BUNDLE_INVENTORY.md"
RESPONSIBILITIES = (
    "canonicalization",
    "hashing",
    "path_validation",
    "publication",
)


def _physical_line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _bundle_paths(root: Path) -> tuple[str, ...]:
    source = root / BUNDLE_SOURCE
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_TIER_A_BUNDLE_FILES"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, tuple) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError("_TIER_A_BUNDLE_FILES must be a tuple of strings")
        if len(value) != len(set(value)):
            raise ValueError("_TIER_A_BUNDLE_FILES contains duplicate paths")
        return value
    raise ValueError("_TIER_A_BUNDLE_FILES was not found")


def _module_name(relative: str) -> tuple[str, bool]:
    path = PurePosixPath(relative)
    if path.parts[:3] == ("devcontrol", "src", "kaliv_dev_control"):
        tail = path.parts[3:]
        package = "kaliv_dev_control"
    elif path.parts[:2] == ("worker", "app"):
        tail = path.parts[2:]
        package = "app"
    else:
        raise ValueError(f"unsupported Tier-A bundle source root: {relative}")
    if not tail:
        raise ValueError(f"bundle path does not name a Python source: {relative}")
    filename = tail[-1]
    if not filename.endswith(".py"):
        raise ValueError(f"bundle path is not Python source: {relative}")
    is_package = filename == "__init__.py"
    module_parts = list(tail[:-1])
    if not is_package:
        module_parts.append(filename[:-3])
    return ".".join((package, *module_parts)), is_package


def _relative_base(current_module: str, is_package: bool, level: int) -> str:
    base = current_module if is_package else current_module.rpartition(".")[0]
    parts = base.split(".") if base else []
    ascend = max(level - 1, 0)
    if ascend > len(parts):
        return ""
    return ".".join(parts[: len(parts) - ascend])


def _local_imports(
    tree: ast.Module,
    *,
    current_module: str,
    is_package: bool,
    bundle_modules: set[str],
) -> tuple[str, ...]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in bundle_modules:
                    targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _relative_base(current_module, is_package, node.level)
                module = ".".join(
                    part for part in (base, node.module or "") if part
                )
            else:
                module = node.module or ""
            if module in bundle_modules:
                targets.add(module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = ".".join(
                    part for part in (module, alias.name) if part
                )
                if candidate in bundle_modules:
                    targets.add(candidate)
    targets.discard(current_module)
    return tuple(sorted(targets))


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        parts = [function.attr]
        value = function.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _identifier_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.name)
    return names


def _responsibility_signals(tree: ast.Module) -> tuple[str, ...]:
    identifiers = {name.lower() for name in _identifier_names(tree)}
    calls = {
        _call_name(node).lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    call_leaves = {name.rsplit(".", 1)[-1] for name in calls if name}
    responsibilities: list[str] = []

    has_canonical_name = any("canonical" in name for name in identifiers)
    has_canonical_json_dump = any(
        isinstance(node, ast.Call)
        and _call_name(node).lower().endswith("json.dumps")
        and {keyword.arg for keyword in node.keywords if keyword.arg}
        & {"sort_keys", "separators"}
        for node in ast.walk(tree)
    )
    if has_canonical_name or has_canonical_json_dump:
        responsibilities.append("canonicalization")

    if "hashlib" in identifiers or call_leaves & {
        "sha1",
        "sha224",
        "sha256",
        "sha384",
        "sha512",
        "blake2b",
        "blake2s",
    }:
        responsibilities.append("hashing")

    path_tokens = (
        "linkish",
        "symlink",
        "junction",
        "relative_to",
        "canonical_directory",
        "pureposixpath",
    )
    if any(
        any(token in name for token in path_tokens) for name in identifiers
    ) or call_leaves & {
        "is_symlink",
        "is_junction",
        "resolve",
        "relative_to",
        "lstat",
        "samefile",
    }:
        responsibilities.append("path_validation")

    publication_calls = {
        "create_once_file",
        "publish_stream_once",
        "rename_directory_no_replace",
        "mkstemp",
        "namedtemporaryfile",
        "replace",
        "link",
        "fsync",
    }
    publication_definitions = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and (
            "publish" in node.name.lower()
            or "stager" in node.name.lower()
            or node.name.lower().startswith("write_")
        )
        for node in ast.walk(tree)
    )
    if (
        any("publication" in name for name in identifiers)
        or bool(call_leaves & publication_calls)
        or publication_definitions
    ):
        responsibilities.append("publication")

    return tuple(responsibilities)


def build_inventory(root: Path) -> dict[str, Any]:
    root = root.resolve()
    bundle_paths = _bundle_paths(root)
    module_map = {relative: _module_name(relative) for relative in bundle_paths}
    bundle_modules = {module for module, _ in module_map.values()}
    files: list[dict[str, Any]] = []

    for relative in bundle_paths:
        path = root / PurePosixPath(relative)
        payload = path.read_bytes()
        text = payload.decode("utf-8")
        tree = ast.parse(text, filename=relative)
        current_module, is_package = module_map[relative]
        local_imports = _local_imports(
            tree,
            current_module=current_module,
            is_package=is_package,
            bundle_modules=bundle_modules,
        )
        top_level_classes = sum(
            isinstance(node, ast.ClassDef) for node in tree.body
        )
        top_level_functions = sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in tree.body
        )
        files.append(
            {
                "path": relative,
                "bytes": len(payload),
                "physical_lines": _physical_line_count(text),
                "top_level_classes": top_level_classes,
                "top_level_functions": top_level_functions,
                "local_import_fan_out": len(local_imports),
                "local_imports": list(local_imports),
                "responsibilities": list(_responsibility_signals(tree)),
            }
        )

    responsibility_summary = {
        responsibility: [
            item["path"]
            for item in files
            if responsibility in item["responsibilities"]
        ]
        for responsibility in RESPONSIBILITIES
    }
    return {
        "schema": SCHEMA,
        "bundle_source": BUNDLE_SOURCE,
        "file_count": len(files),
        "totals": {
            "bytes": sum(item["bytes"] for item in files),
            "physical_lines": sum(item["physical_lines"] for item in files),
            "top_level_classes": sum(
                item["top_level_classes"] for item in files
            ),
            "top_level_functions": sum(
                item["top_level_functions"] for item in files
            ),
            "local_import_edges": sum(
                item["local_import_fan_out"] for item in files
            ),
        },
        "responsibility_summary": responsibility_summary,
        "files": files,
    }


def render_json(inventory: dict[str, Any]) -> str:
    return json.dumps(
        inventory,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def _markdown_list(paths: Iterable[str]) -> str:
    values = list(paths)
    if not values:
        return "- None\n"
    return "".join(f"- `{path}`\n" for path in values)


def render_markdown(inventory: dict[str, Any]) -> str:
    totals = inventory["totals"]
    lines = [
        "# Tier-A authority bundle inventory",
        "",
        f"Schema: `{inventory['schema']}`",
        "",
        "This file is generated from the exact `_TIER_A_BUNDLE_FILES` tuple in "
        f"`{inventory['bundle_source']}`. It records measurements only; it does "
        "not enforce size, line-count, complexity or fan-out thresholds.",
        "",
        "## Totals",
        "",
        "| Files | Bytes | Physical lines | Top-level classes | Top-level functions | Local import edges |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {inventory['file_count']} | {totals['bytes']} | "
            f"{totals['physical_lines']} | {totals['top_level_classes']} | "
            f"{totals['top_level_functions']} | {totals['local_import_edges']} |"
        ),
        "",
        "## Per-file measurements",
        "",
        "Local import fan-out counts distinct direct imports that resolve to another file in the exact bundle.",
        "",
        "| Path | Bytes | Lines | Classes | Functions | Fan-out | Responsibility signals |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in inventory["files"]:
        responsibilities = ", ".join(item["responsibilities"]) or "—"
        lines.append(
            f"| `{item['path']}` | {item['bytes']} | {item['physical_lines']} | "
            f"{item['top_level_classes']} | {item['top_level_functions']} | "
            f"{item['local_import_fan_out']} | {responsibilities} |"
        )

    lines.extend(
        [
            "",
            "## Duplicated responsibility signals",
            "",
            "These are deterministic syntactic signals for review and split planning, not claims that every listed implementation is equivalent.",
            "",
        ]
    )
    titles = {
        "canonicalization": "Canonicalization",
        "hashing": "Hashing",
        "path_validation": "Path validation",
        "publication": "Publication",
    }
    for responsibility in RESPONSIBILITIES:
        lines.extend(
            [
                f"### {titles[responsibility]}",
                "",
                _markdown_list(
                    inventory["responsibility_summary"][responsibility]
                ).rstrip("\n"),
                "",
            ]
        )

    lines.extend(
        [
            "## Signal rules",
            "",
            "- **Canonicalization:** canonical-named definitions/references or `json.dumps` calls that explicitly request sorted keys or compact separators.",
            "- **Hashing:** `hashlib` use or cryptographic hash constructor calls.",
            "- **Path validation:** link/junction/symlink, relative-path, canonical-directory or physical resolution checks.",
            "- **Publication:** shared publication primitives, temporary-file/link/replace/fsync calls, or publish/stager/write definitions.",
            "",
            f"The canonical machine-readable snapshot is `{SNAPSHOT_PATH}`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--format", choices=("json", "markdown"), default="markdown"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare generated output with the committed snapshot",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    inventory = build_inventory(root)
    output = (
        render_json(inventory)
        if args.format == "json"
        else render_markdown(inventory)
    )
    target = root / (
        SNAPSHOT_PATH if args.format == "json" else MARKDOWN_PATH
    )
    if args.check:
        if target.read_text(encoding="utf-8") != output:
            raise SystemExit(f"Tier-A bundle inventory is stale: {target}")
        return 0
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
