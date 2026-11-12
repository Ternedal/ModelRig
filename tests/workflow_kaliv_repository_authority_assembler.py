#!/usr/bin/env python3
"""Contract for scripts/kaliv_repository_authority_assembler.py (#2390 F3, #2109).

The assembler turns the four verifiers' saved ``-Json`` outputs into the qualifier's
input. The fixtures below have the exact field sets the four verifiers write on
their current ``main``s: ModelRig and BodyRig through their Python evaluators,
VisionRig and VoiceRig from PowerShell (with ``github_head_revision``). The real
qualifier must accept what the assembler writes, and every way a verdict can be
wrong must be refused.

Run: python3 tests/workflow_kaliv_repository_authority_assembler.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import kaliv_repository_authority_assembler as assembler  # noqa: E402
import kaliv_repository_authority_qualifier as qualifier  # noqa: E402

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


SHAS = {
    "Ternedal/ModelRig": "1" * 40,
    "Ternedal/BodyRig": "2" * 40,
    "Ternedal/VisionRig": "3" * 40,
    "Ternedal/VoiceRig": "4" * 40,
}


def python_evaluator_verdict(repository: str, fmt: str, extra: dict) -> dict:
    # The shape of scripts/repository_authority.py (ModelRig) and bodyrig/repository_authority.py.
    return {
        "format": fmt, "version": 1, "repository": repository, "branch": "main",
        "head_revision": SHAS[repository], "protected": True, "authority_mode": "classic",
        "required_status_checks": ["test"], "required_status_check_app_id": 15368,
        "passed": True, "errors": [], "warnings": [], "classic": {"passed": True},
        "rulesets": {"passed": False}, "production_activation": False, **extra,
    }


def powershell_verdict(repository: str, fmt: str) -> dict:
    # The shape of VisionRig's and VoiceRig's verify-repository-authority.ps1 -Json.
    return {
        "format": fmt, "version": 1, "repository": repository, "branch": "main",
        "head_revision": SHAS[repository], "github_head_revision": SHAS[repository],
        "protected": True, "authority_mode": "classic", "required_status_checks": ["unit"],
        "passed": True, "errors": [], "production_activation": False,
    }


def good() -> dict[str, dict]:
    return {
        "Ternedal/ModelRig": python_evaluator_verdict(
            "Ternedal/ModelRig", "modelrig-repository-authority",
            {"physical_validation_authority": False, "agent3_activation_authority": False}),
        "Ternedal/BodyRig": python_evaluator_verdict(
            "Ternedal/BodyRig", "bodyrig-repository-authority",
            {"physical_acceptance_authority": False, "required_status_check_sources": []}),
        "Ternedal/VisionRig": powershell_verdict("Ternedal/VisionRig", "visionrig-repository-authority"),
        "Ternedal/VoiceRig": powershell_verdict("Ternedal/VoiceRig", "voicerig-repository-authority"),
    }


def as_bytes(verdicts: dict[str, dict]) -> dict[str, bytes]:
    # What `pwsh -File verify-repository-authority.ps1 -Json > file` leaves: one line and a newline.
    return {repo: (json.dumps(v, separators=(",", ":")) + "\n").encode() for repo, v in verdicts.items()}


def refused(outputs: dict[str, bytes], needle: str, expected: dict | None = None) -> bool:
    try:
        assembler.assemble(outputs, expected)
    except assembler.AssemblyError as exc:
        return needle in str(exc)
    return False


# --- the happy path, and the real qualifier accepts it --------------------------------
outputs = as_bytes(good())
evidence = assembler.assemble(outputs)
verdict = qualifier.qualify(evidence)
check(verdict["repository_authority_gate_satisfied"] is True, "the real qualifier accepts the assembled evidence")
check(verdict["production_activation"] is False and verdict["release_gate_satisfied"] is False,
      "the verdict claims nothing beyond repository authority")
check([e["git_sha"] for e in evidence["repositories"]] == list(SHAS.values()), "each entry carries its verifier's head")
check(all(e["evidence_ref"] == f"sha256:{hashlib.sha256(outputs[e['repository']]).hexdigest()}:{assembler.FORMATS[e['repository']]}"
          for e in evidence["repositories"]), "each evidence_ref is the SHA-256 of the exact bytes read")
check(verdict["release_evidence_ref"].startswith("kaliv-repository-authority:" + ":".join(SHAS.values()) + ":"),
      "the release evidence ref embeds the four heads in the qualifier's order")

# Windows PowerShell 5.1 `>` writes UTF-16 with a BOM and CRLF; Set-Content may add a UTF-8 BOM.
voice_line = json.dumps(good()["Ternedal/VoiceRig"])
for label, raw in (("UTF-16 with BOM", (voice_line + "\r\n").encode("utf-16")),
                   ("UTF-8 with BOM", b"\xef\xbb\xbf" + voice_line.encode() + b"\n")):
    check(assembler.assemble({**outputs, "Ternedal/VoiceRig": raw})["repositories"][3]["git_sha"] == SHAS["Ternedal/VoiceRig"],
          f"a {label} file is read")

# ModelRig's REAL evaluator output (scripts/repository_authority.py), not a hand-made shape.
import repository_authority as modelrig_evaluator  # noqa: E402
real_checks = [{"context": c, "app_id": modelrig_evaluator.REQUIRED_STATUS_CHECK_APP_ID}
               for c in modelrig_evaluator.REQUIRED_STATUS_CHECKS]
real = modelrig_evaluator.evaluate_repository_authority(
    {"name": "main", "protected": True, "commit": {"sha": SHAS["Ternedal/ModelRig"]}},
    classic_protection={"required_status_checks": {"strict": True, "checks": real_checks},
                        "required_pull_request_reviews": {"bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []}},
                        "enforce_admins": {"enabled": True}, "allow_force_pushes": {"enabled": False},
                        "allow_deletions": {"enabled": False}, "required_conversation_resolution": {"enabled": True}},
    rulesets=[], expected_head=SHAS["Ternedal/ModelRig"])
check(real["passed"] is True, f"the real ModelRig evaluator passes on good settings ({real['errors']})")
real_bytes = (json.dumps(real, separators=(",", ":")) + "\n").encode()
check(assembler.assemble({**outputs, "Ternedal/ModelRig": real_bytes})["repositories"][0]["git_sha"] == SHAS["Ternedal/ModelRig"],
      "the real ModelRig evaluator output is accepted")
real_failing = modelrig_evaluator.evaluate_repository_authority(
    {"name": "main", "protected": True, "commit": {"sha": SHAS["Ternedal/ModelRig"]}},
    classic_protection=None, rulesets=[], expected_head="9" * 40)
check(refused({**outputs, "Ternedal/ModelRig": (json.dumps(real_failing) + "\n").encode()}, "did not pass"),
      "a real failing ModelRig verdict (wrong head, no protection) is refused")

check(assembler.assemble(outputs, {"Ternedal/BodyRig": SHAS["Ternedal/BodyRig"]})["repositories"][1]["git_sha"]
      == SHAS["Ternedal/BodyRig"], "--expect accepts the matching pin")


# --- every way a verdict can be wrong is refused ---------------------------------------
def mutated(repo: str, change) -> dict[str, bytes]:
    verdicts = good()
    change(verdicts[repo])
    return as_bytes(verdicts)


CASES = [
    ("Ternedal/ModelRig", lambda v: v.update(passed=False), "did not pass"),
    ("Ternedal/BodyRig", lambda v: v.update(errors=["x"]), "no errors"),
    ("Ternedal/VisionRig", lambda v: v.update(format="voicerig-repository-authority"), "format is not visionrig"),
    ("Ternedal/VoiceRig", lambda v: v.update(version=2), "version is not 1"),
    ("Ternedal/VoiceRig", lambda v: v.update(version=True), "version is not 1"),
    ("Ternedal/ModelRig", lambda v: v.update(repository="Ternedal/BodyRig"), "another repository"),
    ("Ternedal/BodyRig", lambda v: v.update(branch="release"), "branch main"),
    ("Ternedal/VisionRig", lambda v: v.update(head_revision="main"), "40-hex"),
    ("Ternedal/VisionRig", lambda v: v.update(head_revision="A" * 40), "40-hex"),
    ("Ternedal/VoiceRig", lambda v: v.update(github_head_revision="9" * 40), "GitHub main was on another revision"),
    ("Ternedal/ModelRig", lambda v: v.pop("production_activation"), "production_activation must be present"),
    ("Ternedal/ModelRig", lambda v: v.update(production_activation=True), "production_activation"),
    ("Ternedal/ModelRig", lambda v: v.update(physical_validation_authority=True), "physical_validation_authority"),
    ("Ternedal/BodyRig", lambda v: v.update(physical_acceptance_authority=True), "physical_acceptance_authority"),
    ("Ternedal/ModelRig", lambda v: v.update(agent3_activation_authority=True), "agent3_activation_authority"),
]
for repo, change, needle in CASES:
    check(refused(mutated(repo, change), needle), f"{repo}: refused ({needle})")

two_lines = dict(outputs)
two_lines["Ternedal/ModelRig"] = b"Repository authority: PASS\n" + outputs["Ternedal/ModelRig"]
check(refused(two_lines, "exactly one JSON line"), "human output mixed in is refused")
check(refused({**outputs, "Ternedal/BodyRig": b"[1]\n"}, "not a JSON object"), "a non-object is refused")
check(refused({**outputs, "Ternedal/BodyRig": b"{not json\n"}, "not JSON"), "garbage is refused")
check(refused({**outputs, "Ternedal/BodyRig": b"\xff\x00\xff"}, "UTF-8 or UTF-16"), "undecodable bytes are refused")
check(refused({**outputs, "Ternedal/BodyRig": b" " * (assembler.MAX_BYTES + 1)}, "too large"), "an oversized file is refused")
check(refused({k: v for k, v in outputs.items() if k != "Ternedal/VisionRig"}, "missing verifier output"),
      "a missing repository is refused")
check(refused(outputs, "not the expected pin", {"Ternedal/ModelRig": "f" * 40}), "--expect refuses another head")
check(refused(outputs, "unknown repository", {"Ternedal/Other": "f" * 40}), "--expect refuses an unknown repository")
check(len({e["evidence_ref"] for e in evidence["repositories"]}) == 4, "the four evidence refs are distinct")

# --- the CLI: exit codes, and nothing written on refusal ------------------------------
with tempfile.TemporaryDirectory() as tmp:
    tmpdir = Path(tmp)
    args = []
    for repo, option in assembler.OPTIONS.items():
        path = tmpdir / f"{option}.json"
        path.write_bytes(outputs[repo])
        args += [f"--{option}", str(path)]
    out = tmpdir / "evidence.json"
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "kaliv_repository_authority_assembler.py"),
                          *args, "--output", str(out)], capture_output=True, text=True)
    check(run.returncode == 0 and out.exists(), f"CLI exit 0 and writes the file ({run.stderr.strip()})")
    q = subprocess.run([sys.executable, str(ROOT / "scripts" / "kaliv_repository_authority_qualifier.py"), str(out)],
                       capture_output=True, text=True)
    check(q.returncode == 0, f"the qualifier CLI accepts the written file ({q.stdout.strip()[:160]} {q.stderr.strip()[:160]})")
    out.unlink()
    (tmpdir / "voicerig.json").write_bytes(mutated("Ternedal/VoiceRig", lambda v: v.update(passed=False))["Ternedal/VoiceRig"])
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "kaliv_repository_authority_assembler.py"),
                          *args, "--output", str(out)], capture_output=True, text=True)
    check(run.returncode == 2 and not out.exists() and "did not pass" in run.stderr,
          "CLI exit 2, and nothing is written, for a failing verdict")

print(f"\n===== REPOSITORY AUTHORITY ASSEMBLER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
