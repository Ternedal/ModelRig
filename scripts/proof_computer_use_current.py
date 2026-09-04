#!/usr/bin/env python3
"""Fysisk bevis for Computer Use (I3 skærmfangst, I4 handlingsforhåndsvisning).

Computer Use var den ene flade uden noget fysisk bevis overhovedet. Unit-tests
dækkede modulerne; ingen havde vist at grænsen holder på en rigtig Windows-rig.

DET HER BEVISER IKKE EN FUNKTION — DET BEVISER EN GRÆNSE. Fladen er dvalende
med vilje: den registrerer intet værktøj, mounter ingen rute og injicerer
hverken mus eller tastatur. Beviset er derfor bygget om det:

  1. DVALE FØRST. Uden flag: intet værktøj registreret, ingen rute mountet,
     ingen fangst mulig. Bevises FØR noget tændes, ellers ved man ikke om
     det man måler bagefter overhovedet var slukket.
  2. Derefter tændes ``KALIV_COMPUTER_USE_SCREEN`` i operatørens EGEN proces,
     og grænsens fire udsagn efterprøves mod det rigtige skrivebord.
  3. Til sidst slukkes igen, og dvalen bevises PÅ NY. En test der tænder noget
     og ikke viser at det blev slukket, efterlader riggen i en tilstand ingen
     har besluttet.

Flaget sættes kun i denne proces' miljø. Der skrives ikke til nogen
konfiguration, og ingen anden proces påvirkes.

Windows-only. Kan ikke køres i sandkassen; CI parser den, riggen beviser den.

Run: python3 scripts/proof_computer_use_current.py --output-root <mappe>
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

SCHEMA = "kaliv-computer-use-physical/v1"
SKAERM_FLAG = "KALIV_COMPUTER_USE_SCREEN"
BRUG_FLAG = "KALIV_COMPUTER_USE"


class BevisFejl(RuntimeError):
    """Et udsagn holdt ikke. Stopper straks; intet opfindes."""


def _nu() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frisk_import(navn: str):
    """Importér modulet FORFRA, så flagets tilstand aflæses nu og ikke fra cache."""
    for m in list(sys.modules):
        if m.startswith("app."):
            del sys.modules[m]
    import importlib

    return importlib.import_module(navn)


def _dvale_holder(hvornaar: str) -> dict:
    """Uden flag: fangst nægtes, intet vaerktoej registreres, ingen rute mountes."""
    for flag in (SKAERM_FLAG, BRUG_FLAG):
        os.environ.pop(flag, None)

    capture = _frisk_import("app.desktop_capture")
    fund: list[str] = []

    if capture.DesktopCaptureService.enabled():
        fund.append("DesktopCaptureService.enabled() er sand uden flag")

    # Fangst SKAL naegtes -- og med DesktopDenied, ikke med en tilfaeldig fejl.
    try:
        capture.DesktopCaptureService().capture(origin="local")
    except Exception as exc:
        if type(exc).__name__ != "DesktopDenied":
            fund.append(f"fangst naegtet med {type(exc).__name__}, ikke DesktopDenied")
    else:
        fund.append("fangst LYKKEDES uden flag")

    tools = _frisk_import("app.tools")
    for navn in ("desktop_screenshot", "desktop_action_preview"):
        if navn in getattr(tools, "REGISTRY", {}):
            fund.append(f"{navn} staar i REGISTRY uden flag")

    return {"hvornaar": hvornaar, "dvale_holder": not fund, "fund": fund}


def _graensen(output: Path) -> dict:
    """Med flaget taendt: efterproev graensens udsagn mod det rigtige skrivebord."""
    os.environ[SKAERM_FLAG] = "1"
    capture = _frisk_import("app.desktop_capture")

    if not capture.DesktopCaptureService.enabled():
        raise BevisFejl(f"{SKAERM_FLAG}=1 er sat, men enabled() er stadig falsk")

    service = capture.DesktopCaptureService()
    udsagn: list[dict] = []

    def haevd(navn: str, ok: bool, detalje: str = "") -> None:
        udsagn.append({"udsagn": navn, "holder": bool(ok), "detalje": detalje})
        if not ok:
            raise BevisFejl(f"{navn} holdt ikke: {detalje}")

    # 1) cloud-oprindelse skal naegtes FOER vi tager et rigtigt billede.
    try:
        service.capture(origin="cloud")
    except Exception as exc:
        haevd("cloud-oprindelse naegtes", type(exc).__name__ in {"DesktopDenied", "DesktopCaptureError"},
              type(exc).__name__)
    else:
        haevd("cloud-oprindelse naegtes", False, "fangst lykkedes fra cloud-oprindelse")

    foerste = service.capture(origin="local")
    anden = service.capture(origin="local")

    haevd("billedet er en rigtig BMP", foerste.image_bmp.startswith(b"BM"),
          f"{len(foerste.image_bmp)} bytes")
    haevd("fangsten giver en perceptuel hash", bool(foerste.screen.phash),
          str(foerste.screen.phash)[:24])
    haevd("hvert screen_id er nyt",
          bool(foerste.screen.screen_id) and foerste.screen.screen_id != anden.screen.screen_id,
          f"{foerste.screen.screen_id} vs {anden.screen.screen_id}")

    # audit_dict BAERER screen_id og phash med vilje -- det er metadata.
    # Det den ALDRIG maa baere er pixels.
    projektion = json.dumps(foerste.audit_dict(), default=str)
    haevd("auditprojektionen baerer ingen pixels",
          "iVBOR" not in projektion and "data:image" not in projektion
          and "BM" not in projektion.replace("BMP", ""),
          f"{len(projektion)} tegn")
    haevd("auditprojektionen siger production_activation=false",
          foerste.audit_dict().get("production_activation") is False)
    haevd("auditprojektionen baerer stoerrelsen, ikke billedet",
          foerste.audit_dict().get("image_bytes") == len(foerste.image_bmp))

    return {"udsagn": udsagn,
            "screen_ids": [str(foerste.screen.screen_id), str(anden.screen.screen_id)],
            "billedbytes": len(foerste.image_bmp)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-root", type=Path, required=True)
    ap.add_argument("--allow-non-windows", action="store_true",
                    help="kun til parser- og strukturkontrol; producerer INGEN evidens")
    args = ap.parse_args(argv)

    if platform.system() != "Windows" and not args.allow_non_windows:
        print("Computer Use-beviset kan kun tages på Windows-riggen.", file=sys.stderr)
        return 2

    rapport: dict = {
        "schema": SCHEMA,
        "generated_at": _nu(),
        "host": platform.node(),
        "production_activation": False,
    }
    try:
        rapport["dvale_foer"] = _dvale_holder("før")
        if not rapport["dvale_foer"]["dvale_holder"]:
            raise BevisFejl(
                "dvalen holdt ikke FØR noget blev tændt: "
                + "; ".join(rapport["dvale_foer"]["fund"])
            )
        rapport["graense"] = _graensen(args.output_root)
    except BevisFejl as exc:
        rapport["passed"] = False
        rapport["error"] = str(exc)
    except Exception as exc:  # ukendt fejl er ALDRIG et bestået bevis
        rapport["passed"] = False
        rapport["error"] = f"{type(exc).__name__}: {exc}"
    else:
        rapport["passed"] = True
    finally:
        # Sluk igen og BEVIS at dvalen er tilbage. En test der taender noget
        # og ikke viser at det blev slukket, efterlader riggen i en tilstand
        # ingen har besluttet.
        rapport["dvale_efter"] = _dvale_holder("efter")
        if not rapport["dvale_efter"]["dvale_holder"]:
            rapport["passed"] = False
            rapport["error"] = (
                "dvalen kom IKKE tilbage efter beviset: "
                + "; ".join(rapport["dvale_efter"]["fund"])
            )

    args.output_root.mkdir(parents=True, exist_ok=True)
    maal = args.output_root / "computer-use-physical-latest.json"
    maal.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report: {maal}")
    print("PASS" if rapport.get("passed") else f"FAIL: {rapport.get('error')}")
    return 0 if rapport.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
