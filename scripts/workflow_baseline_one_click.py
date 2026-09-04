#!/usr/bin/env python3
"""One command for the first workflow completion baseline.

The harness is already two commands (workflow_runner.py, then workflow_eval.py).
This wrapper exists for what sits AROUND them: on a rig day the time goes to
preconditions that fail late and cryptically -- a token the prompt silently
truncated, a worker the phone cannot reach, stale .pyc, an Ollama without the
model. Each of those surfaces here BEFORE anything runs, with the remedy in the
message rather than in a handoff document.

  python3 scripts/workflow_baseline_one_click.py --check
      Preflight only. Answers "is the rig ready" in seconds. Runs nothing,
      writes nothing, touches no port.

  python3 scripts/workflow_baseline_one_click.py --model hermes3:8b
      Preflight, then the full 14-workflow baseline, then the score.

  python3 scripts/workflow_baseline_one_click.py --model hermes3:8b --only W-05
      One workflow. For re-running a single failure without redoing the set.

Fail-closed on purpose: a preflight that passes when it cannot verify something
is worse than no preflight, because it converts a known unknown into a wrong
number in a receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
SPEC = ROOT / "eval" / "workflows_v1.json"
RUN_OUT = VALIDATION / "workflow-run-latest.json"
EVAL_OUT = VALIDATION / "workflow-baseline-latest.json"
SCHEMA = "kaliv-workflow-baseline/v1"

HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Blocked(RuntimeError):
    """A precondition that must be fixed before anything is measured."""


def heading(text: str) -> None:
    print(f"\n== {text}")


def ok(text: str) -> None:
    print(f"   ok    {text}")


def note(text: str) -> None:
    print(f"         {text}")


def _get(url: str, timeout: float = 4.0, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


# --------------------------------------------------------------------------
# Preflight. Every check names the fix, because "det virkede i går" is not a
# diagnosis and the gate table in HANDOFF.md should not need to be consulted.
# --------------------------------------------------------------------------

def check_spec() -> int:
    if not SPEC.is_file():
        raise Blocked(f"workflow-specen mangler: {SPEC.relative_to(ROOT)}")
    data = json.loads(SPEC.read_text(encoding="utf-8"))
    flows = data["workflows"] if isinstance(data, dict) and "workflows" in data else data
    if not isinstance(flows, list) or not flows:
        raise Blocked(f"{SPEC.name} indeholder ingen workflows")
    ok(f"spec: {len(flows)} workflows i {SPEC.name}")
    return len(flows)


def check_bytecode() -> None:
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
        raise Blocked(
            "PYTHONDONTWRITEBYTECODE=1 er ikke sat.\n"
            "         Uden den skriver koerslen .pyc i traeet, og froszen-gaten\n"
            "         melder NOT FROZEN -- efter maalingen, ikke foer.\n"
            "         Fix (PowerShell):  $env:PYTHONDONTWRITEBYTECODE = \"1\"")
    stale = [p for p in (ROOT / "worker").rglob("*.pyc")]
    if stale:
        raise Blocked(
            f"{len(stale)} .pyc-filer ligger i worker/ fra en tidligere koersel.\n"
            "         Fix (PowerShell):\n"
            "           Get-ChildItem -Path worker -Recurse -Include __pycache__ |\n"
            "             Remove-Item -Recurse -Force")
    ok("bytecode: PYTHONDONTWRITEBYTECODE=1, ingen .pyc i worker/")


def check_identity() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Blocked(f"kunne ikke laese kode-identitet fra git: {exc}") from exc
    if dirty:
        n = len(dirty.splitlines())
        raise Blocked(
            f"arbejdstraeet har {n} uncommittede aendringer.\n"
            "         En baseline bundet til en beskidt SHA kan ikke reproduceres.\n"
            "         Commit eller stash foer maaling.")
    ok(f"identitet: {sha[:12]}, arbejdstrae rent")
    return sha


def check_token() -> str:
    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    if not token:
        raise Blocked(
            "MODELRIG_TOKEN er ikke sat.\n"
            "         Wizard'ens prompt er getpass og tager ikke paalideligt imod\n"
            "         indsaet -- saet den i miljoeet i stedet.\n"
            "         Fix (PowerShell):  $env:MODELRIG_TOKEN = \"<64 hex>\"")
    if not HEX64.match(token):
        raise Blocked(
            f"MODELRIG_TOKEN er {len(token)} tegn, ikke 64 hex.\n"
            "         auth.NewToken giver 32 bytes hex = 64 tegn. Alt andet giver\n"
            "         400 paa hver autentificeret rute -- efter maalingen er startet.\n"
            "         Sandsynligvis afkortet af en prompt eller et copy/paste.")
    ok(f"token: 64 hex ({token[:6]}...)")
    return token


def check_worker(base_url: str, token: str) -> None:
    try:
        status, _ = _get(f"{base_url}/healthz")
    except (urllib.error.URLError, OSError) as exc:
        raise Blocked(
            f"workeren svarer ikke paa {base_url}: {exc}\n"
            "         Bemaerk: deploy\\run-windows.ps1 starter worker OG backend i\n"
            "         samme vindue og draeber workeren i sin finally. Start dem\n"
            "         hver for sig.") from exc
    if status != 200:
        raise Blocked(f"{base_url}/healthz svarede HTTP {status}, forventet 200")
    ok(f"worker: {base_url} svarer")

    # W-13 ERKLAERER requires: ["documents_loaded"] -- OG INGEN TJEKKEDE DET.
    # Er RAG-indekset tomt, kan svaret umuligt baere kilder, og scoringen
    # melder "svaret bar ingen kilder" som om modellen fejlede. 20/8 fejlede
    # W-13 i alle 22 runder paa netop det, og fejlen saa ud som modelkvalitet.
    #
    # Workeren rapporterer selv tallet i /healthz. Saa spoerg den.
    try:
        _spec = json.loads(SPEC.read_text(encoding="utf-8"))
    except Exception:
        _spec = {}
    kraever_dokumenter = {
        w["id"] for w in _spec.get("workflows", [])
        if "documents_loaded" in (w.get("requires") or [])
    }
    if kraever_dokumenter:
        try:
            _, krop = _get(f"{base_url}/healthz")
            antal = int(json.loads(krop).get("documents", 0))
        except Exception:
            antal = -1
        if antal == 0:
            raise Blocked(
                f"RAG-indekset er TOMT, men {sorted(kraever_dokumenter)} kraever\n"
                "         dokumenter. Uden dem kan svaret ikke baere kilder, og\n"
                "         workflowet fejler paa noget der ikke er modellens skyld.\n"
                "         Indlaes mindst eet dokument foer koerslen."
            )
        if antal > 0:
            ok(f"dokumenter: {antal} i indekset ({len(kraever_dokumenter)} workflow(s) kraever dem)")
        else:
            note("kunne ikke laese dokumenttallet; fortsaetter")

    try:
        status, _ = _get(f"{base_url}/api/v1/health",
                         headers={"Authorization": f"Bearer {token}"})
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            raise Blocked(
                "workeren svarer 400 paa en autentificeret rute.\n"
                "         Det betyder normalt at tokenet ikke er 64 tegn.") from exc
        if exc.code == 401:
            raise Blocked(
                "workeren svarer 401 paa en autentificeret rute.\n"
                "         Tokenet er sandsynligvis fra foer en backend-genstart.\n"
                "         Hent et nyt og saet MODELRIG_TOKEN igen.") from exc
        note(f"autentificeret probe gav HTTP {exc.code} -- ruten findes maaske ikke;"
             " fortsaetter")
        return
    except (urllib.error.URLError, OSError):
        note("kunne ikke naa en autentificeret rute; fortsaetter")
        return
    ok("auth: tokenet accepteres")


def check_model(model: str | None, ollama_url: str) -> str:
    try:
        _, body = _get(f"{ollama_url}/api/tags", timeout=6.0)
        tags = json.loads(body)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Blocked(
            f"Ollama svarer ikke paa {ollama_url}: {exc}\n"
            "         Baselinen kan ikke maales uden en model der faktisk svarer."
        ) from exc
    names = [m.get("name", "") for m in tags.get("models", [])]
    if not names:
        raise Blocked("Ollama koerer, men har ingen modeller. Hent en foer maaling.")
    if model is None:
        raise Blocked(
            "--model mangler. En baseline uden et navngivet modelnavn kan ikke\n"
            "         sammenlignes med den naeste.\n"
            f"         Tilgaengelige: {', '.join(names[:8])}")
    if model not in names:
        raise Blocked(
            f"modellen {model!r} findes ikke i Ollama.\n"
            f"         Tilgaengelige: {', '.join(names[:8])}\n"
            f"         Fix:  ollama pull {model}")
    ok(f"model: {model} er hentet")
    return model


def preflight(args) -> tuple[str, str, int]:
    heading("Preflight")
    count = check_spec()
    check_bytecode()
    sha = check_identity()
    token = check_token()
    check_worker(args.base_url, token)
    model = check_model(args.model, args.ollama_url)
    return sha, token, count


# --------------------------------------------------------------------------

def run_step(argv: list[str], env: dict[str, str]) -> int:
    print(f"\n   $ {' '.join(argv)}")
    return subprocess.run(argv, cwd=ROOT, env=env).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="kun preflight; koerer og skriver intet")
    ap.add_argument("--model", help="Ollama-modelnavn, fx hermes3:8b")
    ap.add_argument("--base-url", default="http://127.0.0.1:8099")
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ap.add_argument("--only", help="kun eet workflow-id, fx W-05")
    args = ap.parse_args()

    try:
        sha, token, count = preflight(args)
    except Blocked as exc:
        print(f"\n   BLOKERET: {exc}\n")
        return 1

    if args.check:
        print(f"\n   Riggen er klar. {count} workflows, model {args.model}.")
        print("   Koer uden --check for at maale.\n")
        return 0

    env = dict(os.environ)
    env["PYTHONPATH"] = "worker"
    env["MODELRIG_SHA"] = sha
    VALIDATION.mkdir(parents=True, exist_ok=True)

    heading(f"Koerer {count if not args.only else 1} workflow(s)")
    runner = [sys.executable, "scripts/workflow_runner.py",
              "--model", args.model, "--base-url", args.base_url,
              "--token", token, "--out", str(RUN_OUT)]
    if args.only:
        runner += ["--only", args.only]
    if run_step(runner, env) != 0:
        print("\n   Runneren fejlede. Transcriptet er ufuldstaendigt; ingen score.\n")
        return 1

    heading("Scorer")
    ev = [sys.executable, "scripts/workflow_eval.py",
          "--transcripts", str(RUN_OUT), "--out", str(EVAL_OUT)]
    rc = run_step(ev, env)

    if EVAL_OUT.is_file():
        try:
            summary = json.loads(EVAL_OUT.read_text(encoding="utf-8"))
            rate = summary.get("completion_rate", summary.get("summary", {}).get("completion_rate"))
            heading("Baseline")
            print(f"   completion_rate : {rate}")
            print(f"   model           : {args.model}")
            print(f"   sha             : {sha[:12]}")
            print(f"   kvittering      : {EVAL_OUT.relative_to(ROOT)}")
            print(f"   transcripts     : {RUN_OUT.relative_to(ROOT)}\n")
        except (ValueError, OSError):
            note("kvitteringen kunne ikke laeses tilbage")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
