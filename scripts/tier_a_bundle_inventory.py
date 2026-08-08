#!/usr/bin/env python3
"""Generate and verify the reviewable Tier-A authority-bundle inventory."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "kaliv-tier-a-bundle-inventory/v1"
LOCK_SCHEMA = "kaliv-tier-a-bundle-inventory-lock/v1"
BUNDLE_SOURCE = "devcontrol/src/kaliv_dev_control/tier_a_authority.py"
LOCK_PATH = "devcontrol/TIER_A_BUNDLE_INVENTORY.json"
MARKDOWN_PATH = "devcontrol/TIER_A_BUNDLE_INVENTORY.md"
RESPONSIBILITIES = (
    "canonicalization",
    "hashing",
    "path_validation",
    "publication",
)


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


def _module_info(relative: str) -> tuple[str, bool]:
    parts = PurePosixPath(relative).parts
    if parts[:3] == ("devcontrol", "src", "kaliv_dev_control"):
        package, tail = "kaliv_dev_control", parts[3:]
    elif parts[:2] == ("worker", "app"):
        package, tail = "app", parts[2:]
    else:
        raise ValueError(f"unsupported Tier-A bundle source root: {relative}")
    if not tail or not tail[-1].endswith(".py"):
        raise ValueError(f"bundle path is not Python source: {relative}")
    is_package = tail[-1] == "__init__.py"
    module_tail = list(tail[:-1])
    if not is_package:
        module_tail.append(tail[-1][:-3])
    return ".".join((package, *module_tail)), is_package


def _local_imports(
    tree: ast.Module,
    current_module: str,
    is_package: bool,
    bundle_modules: set[str],
) -> list[str]:
    targets: set[str] = set()
    current_package = (
        current_module if is_package else current_module.rpartition(".")[0]
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(
                alias.name
                for alias in node.names
                if alias.name in bundle_modules
            )
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            package_parts = (
                current_package.split(".") if current_package else []
            )
            ascend = node.level - 1
            base = ".".join(
                package_parts[: len(package_parts) - ascend]
            )
            module = ".".join(
                part for part in (base, node.module or "") if part
            )
        else:
            module = node.module or ""
        if module in bundle_modules:
            targets.add(module)
        for alias in node.names:
            candidate = ".".join(
                part for part in (module, alias.name) if part
            )
            if alias.name != "*" and candidate in bundle_modules:
                targets.add(candidate)
    targets.discard(current_module)
    return sorted(targets)


def _call_name(node: ast.Call) -> str:
    current = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _responsibilities(tree: ast.Module) -> list[str]:
    identifiers: set[str] = set()
    calls: set[str] = set()
    definitions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr.lower())
        elif isinstance(node, ast.alias):
            identifiers.add(node.name.lower())
        elif isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            definitions.add(node.name.lower())
            identifiers.add(node.name.lower())
        elif isinstance(node, ast.Call):
            calls.add(_call_name(node).lower())
    leaves = {call.rsplit(".", 1)[-1] for call in calls if call}
    result: list[str] = []

    canonical_dump = any(
        isinstance(node, ast.Call)
        and _call_name(node).lower().endswith("json.dumps")
        and {keyword.arg for keyword in node.keywords if keyword.arg}
        & {"sort_keys", "separators"}
        for node in ast.walk(tree)
    )
    if canonical_dump or any(
        "canonical" in name for name in identifiers
    ):
        result.append("canonicalization")
    if "hashlib" in identifiers or leaves & {
        "sha1",
        "sha224",
        "sha256",
        "sha384",
        "sha512",
        "blake2b",
        "blake2s",
    }:
        result.append("hashing")
    path_tokens = (
        "linkish",
        "symlink",
        "junction",
        "relative_to",
        "canonical_directory",
        "pureposixpath",
    )
    if any(
        any(token in name for token in path_tokens)
        for name in identifiers
    ) or leaves & {
        "is_symlink",
        "is_junction",
        "resolve",
        "relative_to",
        "lstat",
        "samefile",
    }:
        result.append("path_validation")
    if (
        any("publication" in name for name in identifiers)
        or leaves
        & {
            "create_once_file",
            "publish_stream_once",
            "rename_directory_no_replace",
            "mkstemp",
            "namedtemporaryfile",
            "replace",
            "link",
            "fsync",
        }
        or any(
            "publish" in name
            or "stager" in name
            or name.startswith("write_")
            for name in definitions
        )
    ):
        result.append("publication")
    return result


def build_inventory(root: Path) -> dict[str, Any]:
    root = root.resolve()
    paths = _bundle_paths(root)
    modules = {relative: _module_info(relative) for relative in paths}
    module_names = {module for module, _ in modules.values()}
    files: list[dict[str, Any]] = []
    for relative in paths:
        payload = (root / PurePosixPath(relative)).read_bytes()
        text = payload.decode("utf-8")
        tree = ast.parse(text, filename=relative)
        module, is_package = modules[relative]
        imports = _local_imports(tree, module, is_package, module_names)
        files.append(
            {
                "path": relative,
                "bytes": len(payload),
                "physical_lines": text.count("\n")
                + (1 if text and not text.endswith("\n") else 0),
                "top_level_classes": sum(
                    isinstance(node, ast.ClassDef) for node in tree.body
                ),
                "top_level_functions": sum(
                    isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef)
                    )
                    for node in tree.body
                ),
                "local_import_fan_out": len(imports),
                "local_imports": imports,
                "responsibilities": _responsibilities(tree),
            }
        )
    summary = {
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
            "physical_lines": sum(
                item["physical_lines"] for item in files
            ),
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
        "responsibility_summary": summary,
        "files": files,
    }


def render_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"


def render_markdown(inventory: dict[str, Any]) -> str:
    totals = inventory["totals"]
    lines = [
        "# Tier-A authority bundle inventory",
        "",
        f"Schema: `{inventory['schema']}`",
        "",
        "This report is generated from the exact `_TIER_A_BUNDLE_FILES` tuple in "
        f"`{inventory['bundle_source']}`. It records measurements only; it does "
        "not enforce size, line-count, complexity or fan-out thresholds.",
        "",
        "## Totals",
        "",
        "| Files | Bytes | Physical lines | Top-level classes | Top-level functions | Local import edges |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {inventory['file_count']} | {totals['bytes']} | "
        f"{totals['physical_lines']} | {totals['top_level_classes']} | "
        f"{totals['top_level_functions']} | "
        f"{totals['local_import_edges']} |",
        "",
        "## Per-file measurements",
        "",
        "Local import fan-out counts distinct direct imports that resolve to "
        "another file in the exact bundle. Responsibility signals are "
        "deterministic syntactic indicators for split planning, not claims "
        "that every listed implementation is equivalent.",
        "",
        "| Path | Bytes | Lines | Classes | Functions | Fan-out | Responsibility signals |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in inventory["files"]:
        responsibilities = ", ".join(item["responsibilities"]) or "—"
        lines.append(
            f"| `{item['path']}` | {item['bytes']} | "
            f"{item['physical_lines']} | {item['top_level_classes']} | "
            f"{item['top_level_functions']} | "
            f"{item['local_import_fan_out']} | {responsibilities} |"
        )
    lines.extend(
        [
            "",
            "## Duplicated responsibility signals",
            "",
            "| Responsibility | Files with signal |",
            "|---|---:|",
        ]
    )
    for responsibility in RESPONSIBILITIES:
        lines.append(
            f"| {responsibility.replace('_', ' ').title()} | "
            f"{len(inventory['responsibility_summary'][responsibility])} |"
        )
    lines.extend(
        [
            "",
            "## Signal rules",
            "",
            "- **Canonicalization:** canonical-named definitions/references or `json.dumps` calls that explicitly request sorted keys or compact separators.",
            "- **Hashing:** `hashlib` use or cryptographic hash constructor calls.",
            "- **Path validation:** link/junction/symlink, relative-path, canonical-directory or physical resolution checks.",
            "- **Publication:** shared publication primitives, temporary-file/link/replace/fsync calls, or publish/stager/write definitions.",
            "",
            "Run `python scripts/tier_a_bundle_inventory.py --format json` for "
            "the full machine-readable inventory, including direct local-import "
            "targets and category-to-file mappings. Run "
            "`python scripts/tier_a_bundle_inventory.py --check` to verify this "
            "report and its cryptographic lock.",
            "",
        ]
    )
    return "\n".join(lines)


def build_lock(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "lock_schema": LOCK_SCHEMA,
        "inventory_schema": inventory["schema"],
        "generator": "scripts/tier_a_bundle_inventory.py",
        "bundle_source": inventory["bundle_source"],
        "file_count": inventory["file_count"],
        "totals": inventory["totals"],
        "generated_json_sha256": hashlib.sha256(
            render_json(inventory).encode("utf-8")
        ).hexdigest(),
        "generated_markdown_sha256": hashlib.sha256(
            render_markdown(inventory).encode("utf-8")
        ).hexdigest(),
    }


def check(root: Path, inventory: dict[str, Any]) -> None:
    expected_lock = render_json(build_lock(inventory))
    if (root / LOCK_PATH).read_text(encoding="utf-8") != expected_lock:
        raise SystemExit(
            f"Tier-A bundle inventory lock is stale: {root / LOCK_PATH}"
        )
    expected_report = render_markdown(inventory)
    if (root / MARKDOWN_PATH).read_text(
        encoding="utf-8"
    ) != expected_report:
        raise SystemExit(
            f"Tier-A bundle inventory report is stale: "
            f"{root / MARKDOWN_PATH}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "lock"),
        default="markdown",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    inventory = build_inventory(root)
    if args.check:
        check(root, inventory)
        return 0
    output = {
        "json": render_json(inventory),
        "markdown": render_markdown(inventory),
        "lock": render_json(build_lock(inventory)),
    }[args.format]
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
