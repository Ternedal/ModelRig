#!/usr/bin/env python3
"""T-032's besluttede politik, pinnet så den ikke kan skride i stilhed.

Beslutningen er truffet 27/07-2026 og står i ROADMAP.md som D6. Et dokumenteret
valg er kun værd noget hvis koden ikke kan afvige fra det uden at nogen ser det
-- issuen siger selv "ingen route må åbnes før beslutningen er dokumenteret", og
det modsatte gælder også: dokumentet må ikke sige noget andet end koden gør.

Fire ting er besluttet og pinnet her:
  1. defaults beholdes           public=automatic, operational og private=
                                 confirmation_required, secret=forbidden
  2. kategori-kun                destinationstypen registreres og kvitteres,
                                 men indgår IKKE i beslutningen
  3. 300 sekunder                tilladelsens levetid, loft 3600
  4. research først              den eneste flade der håndhæver i dag

Run: PYTHONPATH=worker python3 tests/workflow_data_sharing_decision.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-ds-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from app import data_sharing as ds  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


# --- 1. defaults ----------------------------------------------------------
DECIDED = {
    "public": "automatic",
    "operational": "confirmation_required",
    "private": "confirmation_required",
    "secret": "forbidden",
}
check(ds.DEFAULT_POLICY.rules() == DECIDED,
      f"DEFAULT_POLICY matcher D6 ({ds.DEFAULT_POLICY.rules()})")

# De to invarianter maa ikke kunne slaekkes, uanset hvad nogen beslutter senere.
for kwargs, why in (
    ({"secret": "confirmation_required"}, "secret kan ikke goeres bekraeftbar"),
    ({"secret": "automatic"}, "secret kan ikke goeres automatisk"),
    ({"private": "automatic"}, "private kan ikke goeres automatisk"),
):
    try:
        ds.DataSharingPolicy(**kwargs)
        check(False, why)
    except ds.DataSharingContractError:
        check(True, why)

# --- 2. kategori-kun ------------------------------------------------------
def request_for(category: str, destination_type: str) -> ds.DataSharingRequest:
    return ds.DataSharingRequest(
        surface="research",
        destination_type=destination_type,
        provider="example",
        destination="https://example.com/a",
        data_category=category,
        purpose_code="probe",
        purpose="pinned decision probe",
        summary="probe",
        content_sha256="0" * 64,
        max_bytes=1024,
    )


for category in DECIDED:
    decisions = {
        ds.DEFAULT_POLICY.decision(request_for(category, dest))
        for dest in ("public_web", "cloud_model", "connector")
    }
    check(len(decisions) == 1,
          f"{category}: samme beslutning uanset destination ({decisions})")

# Destinationen skal stadig registreres -- kategori-kun betyder ikke at vi
# holder op med at vide hvorhen. Uden det kan matricen aldrig kalibreres senere.
req = request_for("operational", "cloud_model")
check(req.digest_payload().get("destination_type") == "cloud_model",
      "destinationstypen indgaar i request-digest -- den bindes, selv om den "
      "ikke afgoer beslutningen")
check(req.preview().get("destination_type") == "cloud_model",
      "og previewet viser hvorhen, saa mennesket ser destinationen foer det "
      "bekraefter")
# Kalibrering senere kraever at to ellers ens requests til FORSKELLIGE
# destinationer ikke kollapser til samme digest.
other = request_for("operational", "public_web")
check(req.digest != other.digest,
      "to requests der kun adskiller sig paa destination har forskellig digest")

# --- 3. gyldighedsperiode -------------------------------------------------
import inspect  # noqa: E402

sig = inspect.signature(ds.DataSharingLedger.propose)
check(sig.parameters["ttl_seconds"].default == 300,
      f"tilladelsens levetid er 300 s ({sig.parameters['ttl_seconds'].default})")

ledger = ds.DataSharingLedger(os.path.join(_tmp, "ledger.db"))
try:
    ledger.propose(request_for("operational", "cloud_model"), ttl_seconds=7200)
    check(False, "loftet paa 3600 s haandhaeves")
except ds.DataSharingContractError:
    check(True, "loftet paa 3600 s haandhaeves")

# --- 4. research foerst ---------------------------------------------------
check("research" in ds._SURFACES and "agent3" in ds._SURFACES,
      "politikken daekker alle fire flader, ogsaa dem der ikke er taendt endnu")

served = ROOT / "worker" / "app" / "main_impl.py"
check("data_sharing" not in served.read_text(encoding="utf-8"),
      "ingen serveret rute importerer gaten endnu -- research koerer via "
      "operatoer-scripts, og en rute kraever en ny beslutning")

print(f"\ndata sharing decision (T-032 / D6): {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
