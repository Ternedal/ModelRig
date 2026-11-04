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
    "image_job_store", "media_generation_runner", "diffusers_image_adapter", "comfy_supervisor",
    "comfy_workflow_template", "comfy_video_adapter", "comfy_resident_launcher", "media_executor",
)
# The ComfyUI supervisor is the one module that must start a process and talk
# HTTP. It gets exactly those two, and only in the checked shape below.
SUPERVISOR = "comfy_supervisor"
SUPERVISOR_ALLOWED = {"subprocess", "http"}
# The resident launcher runs inside ComfyUI's own Python and hands control to
# ComfyUI's main.py: runpy, once, on the validated main path, and nothing else.
LAUNCHER = "comfy_resident_launcher"
LAUNCHER_ALLOWED = {"runpy"}
OTHER_SIDE = {"image_media_store", "image_media_mount", "image_asset_service", "image_internal_api",
              "video_media_api", "video_media_catalog"}
FORBIDDEN_ANYWHERE = {"fastapi", "starlette", "httpx", "requests", "urllib", "socket", "subprocess",
                      "http", "importlib", "pickle", "shelve", "ctypes", "multiprocessing", "runpy"}
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
    allowed = SUPERVISOR_ALLOWED if name == SUPERVISOR else LAUNCHER_ALLOWED if name == LAUNCHER else set()
    check(not (roots(every) & (FORBIDDEN_ANYWHERE - allowed)),
          f"{name}: no web framework, network client or dynamic loading"
          + (f" (beyond {sorted(allowed)})" if allowed else ""))
    check(not (roots(top) & GPU_LIBS), f"{name}: torch/diffusers are not imported at module level")
    check(not ({"eval", "exec", "__import__", "system", "popen"} & calls(tree)), f"{name}: no eval/exec/__import__/system")


def supervisor_shape(tree: ast.AST) -> list[str]:
    """Problems with how the supervisor uses its two allowances."""
    problems = []
    loopback = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "LOOPBACK" for t in n.targets)]
    if len(loopback) != 1 or not (isinstance(loopback[0].value, ast.Constant)
                                  and loopback[0].value.value == "127.0.0.1"):
        problems.append("LOOPBACK must be the single constant 127.0.0.1")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "HTTPConnection":
            if not node.args or not (isinstance(node.args[0], ast.Name) and node.args[0].id == "LOOPBACK"):
                problems.append(f"line {node.lineno}: HTTPConnection must target LOOPBACK")
        if node.func.attr in {"Popen", "run", "call", "check_call", "check_output"}:
            keywords = {k.arg: k.value for k in node.keywords}
            if node.func.attr != "Popen":
                problems.append(f"line {node.lineno}: only subprocess.Popen is allowed")
            if "shell" in keywords:
                problems.append(f"line {node.lineno}: no shell= argument")
            if "env" not in keywords:
                problems.append(f"line {node.lineno}: Popen must get an explicit env")
            if not (isinstance(keywords.get("close_fds"), ast.Constant) and keywords["close_fds"].value is True):
                problems.append(f"line {node.lineno}: Popen must use close_fds=True")
    popens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "Popen"]
    if len(popens) != 1:
        problems.append(f"exactly one Popen call expected, found {len(popens)}")
    return problems


if SUPERVISOR in trees:
    problems = supervisor_shape(trees[SUPERVISOR])
    check(not problems, "comfy_supervisor: loopback-only HTTP, one Popen with explicit env, close_fds, no shell"
          + (f" -- {problems}" if problems else ""))
# Control: the shape check can fail.
bad = ast.parse('LOOPBACK = "0.0.0.0"\nimport subprocess, http.client\n'
                'subprocess.Popen(["x"], shell=True)\nhttp.client.HTTPConnection("example.com", 80)\n')
check(len(supervisor_shape(bad)) >= 4, "control: a non-loopback host, shell=True and a missing env would be caught")

if LAUNCHER in trees:
    launcher = trees[LAUNCHER]
    run_calls = [n for n in ast.walk(launcher) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in {"run_path", "run_module"}]
    check(len(run_calls) == 1 and run_calls[0].func.attr == "run_path"
          and isinstance(run_calls[0].args[0], ast.Name) and run_calls[0].args[0].id == "main_py",
          "comfy_resident_launcher: exactly one runpy.run_path, on the validated main_py")
    app_imports = [m for m in imports(launcher, top_level_only=False) if m.startswith(".") or m.startswith("app")]
    check(not app_imports, "comfy_resident_launcher: stdlib only (it runs under ComfyUI's own Python)")

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
check(bool(roots(imports(ast.parse("import http.client\nimport ctypes\n"), top_level_only=False))
           & FORBIDDEN_ANYWHERE), "control: http.client/ctypes outside the supervisor would be caught")
check(bool(roots(imports(probe, top_level_only=True)) & GPU_LIBS)
      and bool(roots(imports(probe, top_level_only=False)) & OTHER_SIDE),
      "control: a module-level torch import and a media-store import would be caught")

print(f"\n===== MEDIA GENERATION BOUNDARY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
