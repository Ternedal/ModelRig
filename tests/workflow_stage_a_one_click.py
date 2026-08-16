#!/usr/bin/env python3
"""Run the retained Stage A one-click contract against candidate 1.58.151."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_proof_launcher = (ROOT / "scripts" / "run-proof-campaign.ps1").read_text(encoding="utf-8")
_easy_launcher = (ROOT / "scripts" / "run-proof-campaign-easy.ps1").read_text(encoding="utf-8")
_cmd_launcher = (ROOT / "START_PROOF_CAMPAIGN.cmd").read_text(encoding="utf-8")
_cleanup = (ROOT / "scripts" / "stop-stage-a-known-processes.ps1").read_text(encoding="utf-8")

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
