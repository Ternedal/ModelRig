#!/usr/bin/env python3
"""The generation slice stays inside its boundary (ModelRig #2296).

Ownership split 6490545753: ChatGPT owns the gallery server, routes, media
store and artifact retrieval; Claude owns generator adapters and GPU
admission. This gate fails when a generation module reaches into the other
side (media store, mount, asset service, internal API, a web framework), when
it gains a network client or dynamic loading, when torch/diffusers become an
import-time dependency, when the worker entrypoint starts importing the
generation layer, or when a GPU library lands in a worker requirements file.
Together these keep "no change to release behaviour" checkable.

Run: python3 tests/workflow_media_generation_boundary.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402  (comments removed: a commented-out line must not pass)

APP = ROOT / "worker" / "app"
SLICE = (
    "media_generation_contract", "media_generation_profiles", "gpu_lease", "image_gpu_admission",
    "image_job_store", "media_generation_runner", "diffusers_image_adapter",
)
OTHER_SIDE = {"image_media_store", "image_media_mount", "image_asset_service", "image_internal_api",
              "video_media_api", "video_media_catalog"}
FORBIDDEN_ANYWHERE = {"fastapi", "starlette", "httpx", "requests", "urllib", "socket", "subprocess",
                      "importlib", "pickle", "shelve"}
GPU_LIBS = {"torch", "diffusers", "transformers", "accelerate"}

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def imports(tree: ast.AST, *, top_level_only: bool) -> set[str]:
    found: set[str] = set()
    nodes = tree.body if top_level_only else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found.add(("." * node.level) + module)
    return found


def roots(names: set[str]) -> set[str]:
    return {name.lstrip(".").split(".")[0] for name in names if name.lstrip(".")}


def calls(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            names.add(fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else "")
    return names


trees = {}
for name in SLICE:
    path = APP / f"{name}.py"
    check(path.is_file(), f"{name}.py exists")
    if path.is_file():
        trees[name] = ast.parse(code_of(path), filename=str(path))

for name, tree in trees.items():
    every = imports(tree, top_level_only=False)
    top = imports(tree, top_level_only=True)
    check(not (roots(every) & OTHER_SIDE), f"{name}: imports nothing from the gallery/media-store side")
    check(not (roots(every) & FORBIDDEN_ANYWHERE), f"{name}: no web framework, network client or dynamic loading")
    check(not (roots(top) & GPU_LIBS), f"{name}: torch/diffusers are not imported at module level")
    check(not ({"eval", "exec", "__import__", "system", "popen"} & calls(tree)), f"{name}: no eval/exec/__import__/system")

entrypoint = ast.parse(code_of(APP / "entrypoint.py"))
check(not (roots(imports(entrypoint, top_level_only=False)) & set(SLICE)),
      "worker entrypoint does not import the generation layer (nothing activates on worker start)")

requirement_files = sorted((ROOT / "worker").glob("requirements*.txt"))
check(bool(requirement_files), f"worker requirements files found ({len(requirement_files)})")
for req in requirement_files:
    names = set()
    for line in code_of(req).splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(line.split(";")[0].split("==")[0].split(">=")[0].split("[")[0].strip().lower())
    check(not (names & GPU_LIBS), f"{req.name}: no GPU generation library")

# Control: the checks can fail.
probe = ast.parse("import torch\nfrom .image_media_store import ExternalMediaStore\n")
check(bool(roots(imports(probe, top_level_only=True)) & GPU_LIBS)
      and bool(roots(imports(probe, top_level_only=False)) & OTHER_SIDE),
      "control: a module-level torch import and a media-store import would be caught")

print(f"\n===== MEDIA GENERATION BOUNDARY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
