#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "milestone3_current_main.py"
SOURCE = code_of(SCRIPT)
spec = importlib.util.spec_from_file_location("milestone3_current_main", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

checks: list[tuple[str, bool]] = []


def check(label: str, condition) -> None:
    checks.append((label, bool(condition)))


check(
    "candidate is exact current-main branch/version bound",
    module.BRANCH == "agent/milestone3-current-main-v2"
    and module.VERSION == "1.58.147",
)
check(
    "operator order is read-only then T-022 final gate then termination UI",
    [item[0] for item in module.OPERATORS]
    == [
        "T-020 read-only developer-pilot",
        "T-022 append-only write-pilot final gate",
        "T-023 termination UI-pilot",
    ],
)
check(
    "T-022 uses current-main final gate rather than obsolete compact operator",
    module.OPERATORS[1][1].name == "agent3_write_pilot_current_main.py"
    and module.OPERATORS[1][2].name == "agent3-write-pilot-final-gate-latest.json"
    and module.OPERATORS[1][3] == "kaliv-agent3-write-pilot-final-gate/v1"
    and "agent3_write_pilot_physical_one_click.py" not in SOURCE,
)
check(
    "canonical schemas are pinned for all three reports",
    [item[3] for item in module.OPERATORS]
    == [
        "kaliv-agent3-readonly-pilot/v1",
        "kaliv-agent3-write-pilot-final-gate/v1",
        "kaliv-agent3-termination-ui-physical/v1",
    ],
)
check(
    "Stage A is evaluated before any Agent 3 child operator",
    SOURCE.index("stage_code = run_stage_a_gate()")
    < SOURCE.index("for label, path, report, schema in OPERATORS"),
)
check(
    "each child runs in an isolated Python process",
    "subprocess.run(" in SOURCE
    and '[sys.executable, "-B", "-c", child_bootstrap(path)]' in SOURCE,
)
bootstrap = module.child_bootstrap(Path("scripts/child.py"))
check(
    "child bootstrap overrides branch and version before main",
    f"m.BRANCH={module.BRANCH!r}" in bootstrap
    and f"m.VERSION={module.VERSION!r}" in bootstrap
    and bootstrap.index("m.BRANCH=") < bootstrap.index("m.main()"),
)
check(
    "coordinator contains no merge push tag release or activation action",
    all(
        marker not in SOURCE
        for marker in (
            'git("merge"',
            'git("push"',
            'git("tag"',
            "merge_pull_request",
            "enable_auto_merge",
            '"production_activation": True',
            "production_activation=true",
        )
    ),
)
check(
    "zero child exit code is not trusted without report verification",
    "status = report_status(report, sha, schema)" in SOURCE
    and 'status.get("schema_match") is not True' in SOURCE
    and 'status.get("candidate_match") is not True' in SOURCE
    and 'status.get("production_activation") is not False' in SOURCE,
)

sha = "a" * 40
with tempfile.TemporaryDirectory(prefix="kaliv-m3-current-") as tmp:
    tmp_root = Path(tmp)
    original_root = module.ROOT
    try:
        module.ROOT = tmp_root
        report_dir = tmp_root / "validation"
        report_dir.mkdir(parents=True)

        cases = (
            (
                "T-020 nested activation schema is accepted",
                "agent3-readonly-pilot-latest.json",
                "kaliv-agent3-readonly-pilot/v1",
                {"target": {"production_activation": False}},
            ),
            (
                "T-022 final-gate schema is accepted",
                "agent3-write-pilot-final-gate-latest.json",
                "kaliv-agent3-write-pilot-final-gate/v1",
                {"production_activation": False},
            ),
            (
                "T-023 top-level activation schema is accepted",
                "agent3-termination-ui-physical-latest.json",
                "kaliv-agent3-termination-ui-physical/v1",
                {"production_activation": False},
            ),
        )
        for label, name, schema, activation in cases:
            report = report_dir / name
            report.write_text(
                json.dumps(
                    {
                        "schema": schema,
                        "success": True,
                        "candidate": {"git_sha": sha},
                        **activation,
                    }
                ),
                encoding="utf-8",
            )
            status = module.report_status(report, sha, schema)
            check(
                label,
                status["success"] is True
                and status["candidate_match"] is True
                and status["schema_match"] is True
                and status["production_activation"] is False,
            )

        bad = report_dir / "bad.json"
        bad.write_text(
            json.dumps(
                {
                    "schema": "wrong",
                    "success": True,
                    "candidate": {"git_sha": "b" * 40},
                    "production_activation": True,
                }
            ),
            encoding="utf-8",
        )
        status = module.report_status(bad, sha, "expected")
        check(
            "wrong schema SHA and activation all fail closed",
            status["success"] is True
            and status["candidate_match"] is False
            and status["schema_match"] is False
            and status["production_activation"] is True,
        )

        malformed = report_dir / "malformed.json"
        malformed.write_text("{", encoding="utf-8")
        status = module.report_status(malformed, sha, "expected")
        check(
            "malformed reports fail closed",
            status["present"] is True
            and status["success"] is False
            and status["candidate_match"] is False,
        )

        status = module.report_status(report_dir / "missing.json", sha, "expected")
        check(
            "missing reports fail closed",
            status["present"] is False
            and status["success"] is False
            and status["candidate_match"] is False,
        )
    finally:
        module.ROOT = original_root

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== MILESTONE 3 CURRENT-MAIN CANDIDATE: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
