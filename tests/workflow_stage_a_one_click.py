#!/usr/bin/env python3
"""Run the retained Stage A one-click contract against candidate 1.58.151."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_proof_launcher = (ROOT / "scripts" / "run-proof-campaign.ps1").read_text(encoding="utf-8")
_easy_launcher = (ROOT / "scripts" / "run-proof-campaign-easy.ps1").read_text(encoding="utf-8")
_cmd_launcher = (ROOT / "START_PROOF_CAMPAIGN.cmd").read_text(encoding="utf-8")
_cleanup = (ROOT / "scripts" / "stop-stage-a-known-processes.ps1").read_text(encoding="utf-8")
_exit_guard = (ROOT / "scripts" / "proof_campaign_exit_guard.py").read_text(encoding="utf-8")
_runtime_manager = (ROOT / "scripts" / "proof-runtime-manager.ps1").read_text(encoding="utf-8")
_current_adapter = (ROOT / "scripts" / "proof_stage_a_current.py").read_text(encoding="utf-8")
_voice_test = (ROOT / "scripts" / "stage-a-voice-test.ps1").read_text(encoding="utf-8")

assert "function Git(" in _proof_launcher
assert "& git.exe @A" in _proof_launcher
assert "& git @A" not in _proof_launcher
assert "$previousErrorActionPreference = $ErrorActionPreference" in _proof_launcher
assert "$ErrorActionPreference = 'Continue'" in _proof_launcher
assert "$code = $LASTEXITCODE" in _proof_launcher
assert "$ErrorActionPreference = $previousErrorActionPreference" in _proof_launcher
assert "if ($code -ne 0) { throw $v }" in _proof_launcher
print("PASS: physical proof launcher Git helper cannot recurse into itself")
print("PASS: physical proof launcher accepts successful Git stderr and still fails on nonzero exit")

assert "function Git(" in _easy_launcher
assert "& git.exe @A" in _easy_launcher
assert "& git @A" not in _easy_launcher
assert "$previousErrorActionPreference = $ErrorActionPreference" in _easy_launcher
assert "$ErrorActionPreference = 'Continue'" in _easy_launcher
assert "$code = $LASTEXITCODE" in _easy_launcher
assert "$ErrorActionPreference = $previousErrorActionPreference" in _easy_launcher
assert "if ($code -ne 0) { throw $v }" in _easy_launcher
print("PASS: automatic proof wrapper preserves robust Windows Git stderr handling")

assert "run-proof-campaign-easy.ps1" in _cmd_launcher
assert "-Verb RunAs" in _cmd_launcher
assert "/api/v1/pair/start" in _easy_launcher
assert "/api/v1/pair/claim" in _easy_launcher
assert "Read-Host 'MODELRIG_TOKEN" not in _easy_launcher
assert "$env:MODELRIG_TOKEN = $token" in _easy_launcher
assert "Remove-Item Env:MODELRIG_TOKEN" in _easy_launcher
assert "proof-campaign-pairing-data.json" in _easy_launcher
assert "stop-stage-a-known-processes.ps1" in _easy_launcher
assert "run-proof-campaign.ps1" in _easy_launcher
assert "Den stoppes ikke automatisk" in _cleanup
assert "Stop-KnownListener -Port 8080 -Kind backend" in _cleanup
assert "Stop-KnownListener -Port 8099 -Kind worker" in _cleanup
print("PASS: START_PROOF_CAMPAIGN self-elevates through normal Windows UAC")
print("PASS: proof token is minted automatically through local pair/start + pair/claim")
print("PASS: proof token stays process-local and is removed after the core run")
print("PASS: automatic bootstrap cleanup refuses unknown listeners")

assert "proof-runtime-manager.ps1" in _easy_launcher
assert "proof-campaign-suspended-runtime.json" in _easy_launcher
assert "-Action suspend -StatePath $runtimeState" in _easy_launcher
assert "-Action resume -StatePath $runtimeState" in _easy_launcher
assert "$restoreFailed" in _easy_launcher
assert "KalivSupervisor" in _runtime_manager
assert "Stop-ScheduledTask -TaskName 'KalivSupervisor'" in _runtime_manager
assert "Start-ScheduledTask -TaskName ([string]$state.task)" in _runtime_manager
assert "scripts\\modelrig-server-windows-x64.exe" in _runtime_manager
assert "Desktop\\modelrig-server-windows-x64.exe" in _runtime_manager
assert "Classify every occupied proof port BEFORE stopping anything" in _runtime_manager
assert "Den stoppes ikke automatisk" in _runtime_manager
assert "scheduled-supervisor" in _runtime_manager
assert "manual-known-runtime" in _runtime_manager
print("PASS: proof campaign suspends the known Kaliv supervisor instead of racing its child restart loop")
print("PASS: normal ModelRig runtime is restored after proof and unknown port owners remain fail-closed")

assert "def stop_exact_head_stack_for_voice()" in _current_adapter
assert "stop-stage-a-known-processes.ps1" in _current_adapter
_voice_fn = _current_adapter.split("def voice_current", 1)[1].split("def scheduler_current", 1)[0]
assert "stop_exact_head_stack_for_voice()" in _voice_fn
assert _voice_fn.index("stop_exact_head_stack_for_voice()") < _voice_fn.index("stage-a-voice-test.ps1")
assert "Voice-handoff: stopper den kendte loopback Stage A-stack" in _current_adapter
print("PASS: current-head voice flow hands 8080/8099 off from loopback stack before LAN/Pixel stack")

assert "def archive_previous_evidence_current" in _current_adapter
assert "campaign.validate_evidence(" in _current_adapter
assert 'result.get("status") == "pass"' in _current_adapter
assert 'state["carried_forward_proofs"] = sorted(carried)' in _current_adapter
assert "stage.archive_previous_evidence = archive_previous_evidence_current" in _current_adapter
assert "Kun invaliderede rolling reports" in _current_adapter
print("PASS: new candidate SHA does not blanket-delete physical evidence that still passes the authoritative validator")

assert "def voice_observations_current" in _current_adapter
assert 'observations.PHONE_STATE_SCHEMA = "kaliv-stage-a-phone-test-state/v2"' in _current_adapter
assert "python $currentAdapter voice-observations" in _voice_test
assert '& python (Join-Path $PSScriptRoot "stage_a_voice_observations.py")' not in _voice_test
print("PASS: guided voice collector consumes the phone stack's current v2 state schema")

assert 'proof_campaign_exit_guard.py" mark' in _cmd_launcher
assert 'proof_campaign_exit_guard.py" check' in _cmd_launcher
assert 'if "%EXIT_CODE%"=="0" (' in _cmd_launcher
assert 'if not "%ERRORLEVEL%"=="0" set "EXIT_CODE=1"' in _cmd_launcher
assert 'summary.get("passed") is True' in _exit_guard
assert 'summary.get("t023") is True' in _exit_guard
assert 't033.get("passed") is True' in _exit_guard
assert 'int(workflow.get("rounds") or 0) == 22' in _exit_guard
assert 'int(workflow.get("executions") or 0) == 308' in _exit_guard
assert 'path.stat().st_mtime_ns >= started_ns' in _exit_guard
assert 'candidate.get("sha") == sha' in _exit_guard
assert 'summary.get("production_activation") is False' in _exit_guard
print("PASS: launcher cannot report green from Ctrl+C or exit code 0 alone")
print("PASS: launcher requires a fresh exact-SHA full-gate summary before PASS")

_source_path = Path(__file__).with_name("workflow_stage_a_one_click.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "agent/unified-candidate-1.58.151-r2"),
    ("1.58.143", "1.58.151"),
    ("1.58.142", "1.58.144"),
    ("#150", "#161"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())
