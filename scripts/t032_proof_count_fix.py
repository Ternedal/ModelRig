#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected exactly one match, found {count}: {old!r}"
        )
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "PHYSICAL_VALIDATION_CAMPAIGN.md",
    "Denne runbook samler de fysiske **Prove**-opgaver T-004, T-005, T-006,\n"
    "T-007, T-040 og T-043. De enkelte harnesses har fortsat deres egne detaljerede\n",
    "Denne runbook samler de syv fysiske **Prove**-opgaver T-004, T-005, T-006,\n"
    "T-007, T-040, T-043 og T-019. De enkelte harnesses har fortsat deres egne\n"
    "detaljerede\n",
)
replace_once(
    "PHYSICAL_VALIDATION_CAMPAIGN.md",
    "| `0` | I `verify`: alle seks fysiske beviser er present, friske, candidate-bound og grønne. |",
    "| `0` | I `verify`: alle syv fysiske beviser er present, friske, candidate-bound og grønne. |",
)
replace_once(
    "PHYSICAL_VALIDATION_CAMPAIGN.md",
    "- alle seks evidence statuses er `pass`;",
    "- alle syv evidence statuses er `pass`;",
)

replace_once(
    "scripts/physical_validation_campaign.py",
    "The physical validation campaign currently spans independent tools and reports:\n"
    "freeze/preflight, Agent 3 appliance evidence, planner model eval, voice baseline,\n"
    "RAG baseline and appliance lifecycle observations. Each is useful alone, but a\n"
    "folder full of green JSON files is not proof if they describe different commits,\n",
    "The physical validation campaign currently spans seven independent proofs:\n"
    "preflight, Agent 3 appliance evidence, planner model eval, voice baseline,\n"
    "RAG baseline, appliance lifecycle observations and the scheduler pilot. Each is\n"
    "useful alone, but a folder full of green JSON files is not proof if they describe\n"
    "different commits,\n",
)
replace_once(
    "scripts/physical_validation_campaign.py",
    "}\n\nCOMMANDS = {",
    "}\n\nCAMPAIGN_PROOF_COUNT = len(DEFAULT_PATHS)\n\nCOMMANDS = {",
)
replace_once(
    "scripts/physical_validation_campaign.py",
    '            "total": len(evidence),',
    '            "total": CAMPAIGN_PROOF_COUNT,',
)

replace_once(
    "scripts/physical_validation_final_gate.py",
    '"""Combine the six-proof physical campaign with physical T-032 peer evidence.\n\n'
    "This script performs no network request. It validates the existing campaign\n"
    "receipt, the interactive-Windows attestation and the exact underlying browser\n"
    "peer receipt against one current clean candidate, then writes a seventh-proof\n"
    "final receipt with production_activation=false.\n"
    '"""',
    '"""Combine the seven-proof physical campaign with physical T-032 peer evidence.\n\n'
    "This script performs no network request. It validates the existing campaign\n"
    "receipt, the interactive-Windows attestation and the exact underlying browser\n"
    "peer receipt against one current clean candidate, then writes an eighth-proof\n"
    "final receipt with production_activation=false.\n"
    '"""',
)

replace_once(
    "tests/workflow_physical_validation_campaign.py",
    "}\n\n\ndef valid_reports() -> dict[str, dict]:",
    "}\n\n\nRUNBOOK = (ROOT / \"PHYSICAL_VALIDATION_CAMPAIGN.md\").read_text(encoding=\"utf-8\")\n"
    "check(campaign.CAMPAIGN_PROOF_COUNT == 7,\n"
    "      \"campaign proof count is structurally seven\")\n"
    "check(\"alle syv fysiske beviser\" in RUNBOOK\n"
    "      and \"alle syv evidence statuses\" in RUNBOOK,\n"
    "      \"operator runbook names all seven campaign proofs\")\n"
    "check(\"alle seks fysiske beviser\" not in RUNBOOK\n"
    "      and \"alle seks evidence statuses\" not in RUNBOOK,\n"
    "      \"stale six-proof wording cannot return\")\n\n\n"
    "def valid_reports() -> dict[str, dict]:",
)
replace_once(
    "tests/workflow_physical_validation_final_gate.py",
    "    module = load_module()\n"
    "    now = datetime(2026, 7, 20, 18, 30, tzinfo=timezone.utc)",
    "    module = load_module()\n"
    "    assert \"seven-proof physical campaign\" in (module.__doc__ or \"\")\n"
    "    assert \"eighth-proof final receipt\" in (module.__doc__ or \"\")\n"
    "    now = datetime(2026, 7, 20, 18, 30, tzinfo=timezone.utc)",
)
