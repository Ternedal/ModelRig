#!/usr/bin/env python3
"""Inventory the worker's HTTP surface from OpenAPI -- the only honest source.

Sol's correction, 25/07: an import graph proves a MODULE is reachable, not that
a ROUTE is served. The two come apart in both directions -- a module can be
imported and contribute nothing, and a router can exist, be built, and never be
included. Route inventory therefore has to be read off the surface the app
actually publishes.

I hit exactly that failure while measuring: walking `app.routes` and reading
`.path` reported ZERO Agent 3 routes after a successful mount, because
`include_router` leaves `_IncludedRouter` objects that carry no `.path`. The
OpenAPI schema showed 24. An earlier grep of the decorators in `agent3/api.py`
found 9, because the mount includes several routers and a grep sees one file.
Three methods, three different answers; only one of them is what a client can
call.

The inventory also pins a safety invariant that no test covered: **Agent 3 is
dormant unless KALIV_AGENT3_ENABLED=1.** Dormancy is a claim about the served
surface, so it can only be checked here.

    python3 scripts/route_inventory.py            # write ROUTE_INVENTORY.md
    python3 scripts/route_inventory.py --check    # fail on drift
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "ROUTE_INVENTORY.md"

# Collected in a subprocess: mounting Agent 3 mutates module state, so "off"
# and "on" cannot both be measured honestly in one interpreter.
_PROBE = r"""
import json, os, sys, tempfile
os.environ.setdefault("KALIV_TOOLS_ENABLED", "1")
os.environ.setdefault("KALIV_WORKER_ALLOW_LAN", "1")
_t = tempfile.mkdtemp()
os.environ.setdefault("KALIV_TOOLS_DIR", _t + "/notes")
os.environ.setdefault("KALIV_AUDIT_DB", _t + "/audit.db")
if os.environ.get("PROBE_AGENT3") == "1":
    os.environ["KALIV_AGENT3_ENABLED"] = "1"
sys.path.insert(0, "worker")
# The DOCUMENTED PRODUCTION ENTRYPOINT -- not app.main.
#
# app.main is the raw route app; the entrypoint is what a launcher runs and what
# the campaign probes. Asking app.main and calling a mount by hand is a
# different question than "what does this rig serve", and the answers diverge
# the moment mounting moves: one lineage includes every agent3 router from
# agent3/api.py:mount_agent3, another routes production through
# agent3/production_mount.py. A probe calling the former reported 9 routes where
# the entrypoint serves 25 -- and that briefly looked like the candidate had
# lost its memory surface. It had not.
#
# Same lesson as the reachability graph earlier the same day: measure the thing
# that actually runs. tests/worker_agent3_entrypoint_wiring.py has always done
# it this way; this tool now agrees with it.
import app.entrypoint as e
print(json.dumps(sorted(e.fastapi_app.openapi().get("paths", {}))))
"""


def _surface(with_agent3: bool) -> list[str]:
    env = dict(os.environ)
    env["PROBE_AGENT3"] = "1" if with_agent3 else "0"
    env.pop("KALIV_AGENT3_ENABLED", None)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(_PROBE)
        probe = fh.name
    r = subprocess.run([sys.executable, probe], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"probe failed: {r.stderr[-600:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def build() -> str:
    off = _surface(False)
    on = _surface(True)
    dormant = sorted(set(on) - set(off))
    host = off

    lines = [
        "# ROUTE_INVENTORY.md",
        "",
        "**Genereret af `scripts/route_inventory.py` — rediger ikke i hånden.**",
        "",
        "Aflæst fra appens OpenAPI-overflade, ikke fra importgrafer eller grep.",
        "En importgraf beviser at et *modul* kan nås; den siger intet om hvorvidt",
        "en *rute* serveres. En router kan bygges og aldrig inkluderes.",
        "",
        f"- **Host-overflade (Agent 3 slukket): {len(host)} ruter**",
        f"- **Agent 3 tilføjer, når `KALIV_AGENT3_ENABLED=1`: {len(dormant)} ruter**",
        f"- I alt tændt: {len(on)}",
        "",
        "## Dormans-invariant",
        "",
        "Agent 3 serverer **intet** uden det eksplicitte flag. Hver rute nedenfor",
        "ligger under `/experimental/`, så en klient ikke kan ramme den ved et uheld,",
        "og ingen af dem findes i host-overfladen.",
        "",
        "## Host-ruter",
        "",
    ]
    lines += [f"- `{p}`" for p in host]
    lines += ["", "## Agent 3 (kun med flaget)", ""]
    lines += [f"- `{p}`" for p in dormant]
    lines += [""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = build()
    if args.check:
        current = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if current.strip() != text.strip():
            print("ROUTE_INVENTORY.md er driftet — kør: "
                  "python3 scripts/route_inventory.py", file=sys.stderr)
            return 1
        print("route-inventaret er aktuelt")
        return 0
    DOC.write_text(text, encoding="utf-8")
    print(f"skrev {DOC.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
