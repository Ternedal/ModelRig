"""A hand-written document must not claim to be the current state (F-516).

Five documents claimed state at once: HANDOFF, ROADMAP, SECURITY, STATUS, and
the two generated pages. Three were stale, and the two most confident were the
worst -- SECURITY called itself "en *aktuel* trusselsmodel" while being 70
releases old, and HANDOFF carried "Version: v1.58.52" in a header nobody reads
while main was at 1.58.81.

The pattern is the same one this repo has been fixing all day: a document that
ASSERTS state drifts the moment it stops being edited, and nothing tells you.
A document that COMPUTES state cannot. So the rule is not "keep the docs
updated" -- that rule has been in force this whole time and lost. The rule is
that hand-written docs do not get to make claims that can rot.

What this does NOT ban: versions in history ("audit lukket i 1.58.2"), which are
true forever precisely because they are dated.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


HANDWRITTEN = ["HANDOFF.md", "ROADMAP.md", "SECURITY.md", "STATUS.md", "BACKLOG.md"]
GENERATED = ["CURRENT_STATE.md", "ACTIVATION_READINESS.md"]

# A version claim in a header: "**Version:** v1.58.52". Distinct from history.
HEADER_VERSION = re.compile(r"\*\*Version:\*\*\s*v?\d+\.\d+\.\d+")
# Claiming to BE the current picture.
CURRENCY_CLAIM = re.compile(r"\*aktuel\*\s+trusselsmodel|Aktuel autoritativ tilstand:\s*`VERSION`")

for name in HANDWRITTEN:
    p = ROOT / name
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:40])

    m = HEADER_VERSION.search(head)
    check(m is None,
          f"{name}: no hand-written version in the header"
          if m is None
          else f"{name}: HEADER CLAIMS A VERSION ({m.group(0)!r}) -- a number typed "
               "into a header is a timed untruth")

    m = CURRENCY_CLAIM.search(head)
    check(m is None,
          f"{name}: does not claim to be the current picture"
          if m is None
          else f"{name}: CLAIMS CURRENCY ({m.group(0)!r}) -- it will be wrong within "
               "a day and say so to nobody")

    check("CURRENT_STATE.md" in head,
          f"{name}: points the reader at the generated state within the first 40 lines")

for name in GENERATED:
    p = ROOT / name
    check(p.exists(), f"{name}: exists to be pointed at")
    if p.exists():
        head = p.read_text(encoding="utf-8")[:600]
        # One page says "Genereret", the other "GENERATED". Both are honest;
        # this test is about the claim, not about which language it is in.
        check("Genereret" in head or "GENERATED" in head,
              f"{name}: says it is generated, so nobody edits it by hand")

# F-1302: the canonical campaign runbook once forbade running model_eval based
# on a retracted misdiagnosis ("/plan is dead"). These checks pin the runbook
# to the wired reality so the false claim cannot regrow -- and so the
# prerequisites the sandbox smoke proved necessary stay documented.
_runbook = (ROOT / "PHYSICAL_VALIDATION_CAMPAIGN.md").read_text(encoding="utf-8")
check("nedlagte `/plan`" not in _runbook and "Kør IKKE model_eval" not in _runbook,
      "runbook does not claim /plan is dead or forbid model_eval -- that "
      "diagnosis was retracted; the route is wired from 1.58.131")
check("/plans/{id}/start" in _runbook,
      "runbook names the documented production creation path, matching the "
      "wiring the entrypoint suite proves")
check("MODELRIG_TOKEN" in _runbook and "KALIV_AGENT3_ENABLED" in _runbook,
      "runbook documents the model_eval prerequisites the smoke proved "
      "necessary (paired token, flag on both backend and worker)")

# The detector must be able to fail.
check(bool(HEADER_VERSION.search("**Version:** v1.58.52")),
      "self-test: a header version claim IS detected")
check(not HEADER_VERSION.search("audit-P0/P1 lukket (1.58.1/1.58.2)"),
      "self-test: history keeps its version numbers -- those are true forever")

print(f"\n===== DOC AUTHORITY: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
