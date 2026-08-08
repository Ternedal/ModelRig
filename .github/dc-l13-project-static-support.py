from __future__ import annotations

import ast
from pathlib import Path

PATH = Path("devcontrol/src/kaliv_dev_control/_local_candidate_materialization_legacy/__init__.py")
source = PATH.read_text(encoding="utf-8")
tree = ast.parse(source)

forbidden_classes = {
    "TrustedLocalGit",
    "_GitRunner",
    "LocalCandidateMaterializationGate",
}
forbidden_functions = {
    "materialize_local_candidate",
    "verify_local_candidate_materialization",
    "load_local_candidate_materialization_receipt",
    "write_local_candidate_materialization_receipt",
}

retained: list[ast.stmt] = []
for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        continue
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
        continue
    if isinstance(node, ast.ClassDef) and node.name in forbidden_classes:
        continue
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden_functions:
        continue
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        names: set[str] = set()
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
        if "__all__" in names:
            continue
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        retained.append(node)

header = '''"""Static validation and evidence support for DC-L13 local materialization.

This internal package is projected from the locked historical implementation,
but deliberately excludes its executable Git runner, legacy materialize/verify
gates and all retained v1 compatibility imports. It supplies only deterministic
value objects, canonicalization helpers and repository/object inspection helpers
to the modern TrustedGitRuntime-backed facade.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from ..contract import DevelopmentTask, MergeAuthority
from ..publisher_authorization import PublisherAuthorizationError
from ..publisher_authorization_chain_v2 import (
    PublisherAuthorizationVerifierV2 as PublisherAuthorizationVerifier,
    PublisherPreflightReceiptV2 as PublisherPreflightReceipt,
)
from ..publisher_dry_run import PublisherRequestVerifier
from ..semantic_review import SemanticReviewVerifier

'''
body = "\n\n".join(ast.unparse(node) for node in retained)
output = header + body + "\n"

parsed = ast.parse(output)
top_level = {
    node.name
    for node in parsed.body
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
}
for forbidden in forbidden_classes | forbidden_functions:
    if forbidden in top_level:
        raise SystemExit(f"forbidden support symbol survived: {forbidden}")
for token in (
    "import subprocess",
    "globals().update",
    "._compatibility_v1",
    "Popen(",
    "subprocess.run",
):
    if token in output:
        raise SystemExit(f"forbidden support token survived: {token}")

required = {
    "LocalCandidateMaterializationError",
    "LocalGitEvidence",
    "LocalSourceRepositoryEvidence",
    "LocalCandidateCommitEvidence",
    "LocalCandidateMaterializationReceipt",
    "_inspect_source",
    "_verify_source_unchanged",
    "_inspect_materialized_repository",
    "_load_canonical",
    "_write_canonical",
}
missing = sorted(required - top_level)
if missing:
    raise SystemExit(f"required support symbols missing: {missing}")

compile(output, str(PATH), "exec")
PATH.write_text(output, encoding="utf-8")
