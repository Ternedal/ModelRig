#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
script_path = root / "scripts/agent3_write_pilot_physical_one_click.py"
launcher_path = root / "START_AGENT3_WRITE_PILOT_PHYSICAL.cmd"
runbook_path = root / "AGENT3_WRITE_PILOT_PHYSICAL.md"

script = script_path.read_text(encoding="utf-8")
launcher = launcher_path.read_text(encoding="utf-8")
runbook = runbook_path.read_text(encoding="utf-8")
compile(script, str(script_path), "exec")

main = script[script.index("def main()") :]
sequence = [
    main.index("ensure_candidate()"),
    main.index("ensure_secrets()"),
    main.index("configure_environment(paths)"),
    main.index("ensure_stack()"),
    main.index("prepare_or_resume(paths, planner)"),
    main.index("positive_runs(manifest, paths)"),
    main.index("ensure_journal(manifest)"),
    main.index("negative_cases(manifest, paths)"),
    main.index("collect(paths)"),
]

checks = {
    "script compiles": True,
    "launcher invokes only the operator": (
        "scripts\\agent3_write_pilot_physical_one_click.py" in launcher
        and "git push" not in launcher.lower()
        and "release" not in launcher.lower()
    ),
    "fixed ceremony order is encoded": sequence == sorted(sequence),
    "journal binds only after all positive runs": (
        "Journalen må først initialiseres efter 20/20 positive binds" in script
        and "journal_store._init(JOURNAL, MANIFEST)" in script
    ),
    "preflight remains existing GET-only gate": (
        "preflight.run_preflight(" in script
        and "run_preflight(paths)" in script
        and "urllib.request" not in script
        and "requests.post" not in script
    ),
    "write inventory is candidate-derived": (
        "from app.tools import REGISTRY" in script
        and "if tool.risk != 'read'" in script
    ),
    "note append is the only enabled write": (
        "disabled = [name for name in writes if name != \"note_append\"]" in script
        and '"KALIV_TOOLS_STATE": str(TOOLS_STATE.resolve())' in script
    ),
    "approval and tool gates are explicit": (
        '"KALIV_AGENT3_APPROVAL_REQUIRED": "1"' in script
        and '"KALIV_TOOLS_ENABLED": "1"' in script
    ),
    "secrets use hidden input": (
        'getpass.getpass("  MODELRIG_TOKEN' in script
        and "KALIV_AGENT3_APPROVAL_SECRET (skjult" in script
    ),
    "exact one-device boundary is enforced": (
        "Der skal være præcis én ADB-enhed" in script
        and "build_install_android(adb)" in main
    ),
    "Android and desktop developer surfaces are explicit": (
        "ANDROID_AGENT3_EXTRA" in script
        and '"--args=--agent3"' in script
    ),
    "positive preview phrase is exact": "PREVIEW MATCHER ORDINAL {ordinal}" in script,
    "positive approval phrase is exact": "APPROVAL GIVET ORDINAL {ordinal}" in script,
    "positive completion phrase is exact": "RUN COMPLETED ORDINAL {ordinal}" in script,
    "plain yes cannot close a positive run": (
        "require_phrase(f\"{PREVIEW_PHRASE} ORDINAL {ordinal}\")" in script
        and "require_phrase(f\"{APPROVAL_PHRASE} ORDINAL {ordinal}\")" in script
        and "require_phrase(f\"{COMPLETED_PHRASE} ORDINAL {ordinal}\")" in script
    ),
    "positive run is checked against all durable stores": (
        "forensics._validate_success_run(" in script
        and "load_run_records" in script
        and "load_approval_rows" in script
        and "load_audit_rows" in script
        and "notes.splitlines().count(marker)" in script
    ),
    "unbound successful append is recovered without replay": (
        "def recover_unbound_positive(" in script
        and "RECOVERED EVIDENCE REVIEWED ORDINAL {ordinal}" in script
        and "len(matching) != 1" in script
    ),
    "journal cannot coexist with partial positive binding": (
        "Negativ journal findes, før alle 20 positive runs er bundet" in script
    ),
    "open negative case resumes same case id": (
        "def begin_or_resume_negative(" in script
        and "Genoptager åben case" in script
        and 'str(existing["case_id"])' in script
    ),
    "closed negative cases are skipped": (
        'state.get("finish") is not None' in script
    ),
    "negative observations are append-only": (
        "journal_cases.observe_request(" in script
        and "journal_cases.finish_case(" in script
        and "journal_cases.finalize(JOURNAL, MANIFEST)" in script
    ),
    "response body is copied or pasted then hashed by recorder": (
        'Response-kilde (paste/file)' in script
        and "destination.write_bytes" in script
    ),
    "deny status is pinned": 'valid = statuses == [200]' in script,
    "409 negative statuses are pinned": (
        'name in {"timeout", "changed_args", "stale_revision", "replay"}' in script
        and "valid = statuses == [409]" in script
    ),
    "concurrent approval statuses are pinned": (
        "sorted(statuses) == [200, 409]" in script
    ),
    "stop retry replan needs at least three observations": (
        "len(statuses) >= 3" in script
        and "{200, 202, 409}" in script
    ),
    "negative note and approval deltas are measured": (
        "note_after - note_before" in script
        and "approval_after - approval_before" in script
        and "NEGATIVE_EXPECTED_DELTAS" in script
    ),
    "wrong delta leaves case open": (
        "journalcasen forbliver åben" in script
        and "finish_case(" in script
    ),
    "final collection reuses forensic collector": (
        "reporter.collect_report(" in script
        and "negative_journal_path=JOURNAL" in script
    ),
    "no approval endpoint is automated": (
        "/approve" not in script
        and "/confirm" not in script
        and "approval_token" not in script
    ),
    "no publish or merge implementation exists": all(
        token not in script.lower()
        for token in ("git push", "git merge", "git tag", "gh release", "create_release")
    ),
    "safe stop preserves evidence": (
        "manifest, journal og responses er bevaret" in script
        and "Ingen case er auto-godkendt" in script
    ),
    "runbook states physical non-activation boundary": (
        "kan ikke godkende en write" in runbook
        and '"production_activation": false' in runbook
    ),
}

failed = [label for label, ok in checks.items() if not ok]
for label, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-022 PHYSICAL OPERATOR: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
