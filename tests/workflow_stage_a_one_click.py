#!/usr/bin/env python3
"""Run the retained Stage A one-click contract against candidate 2.0.13."""
import os
from pathlib import Path

_source_path = Path(__file__).with_name("workflow_stage_a_one_click.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "physical-proof/2.0.13"),
    ("1.58.143", "2.0.13"),
    ("1.58.142", "2.0.12"),
    ("#150", "#161"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

_seen_headers: list[dict[str, str]] = []
_payloads = [
    b'{"code":"123456"}',
    ('{"token":"' + ('a' * 64) + '"}').encode("utf-8"),
]


class _FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


def _fake_urlopen(request, timeout=5):
    _seen_headers.append(
        {key.lower(): value for key, value in request.header_items()}
    )
    return _FakeResponse(_payloads.pop(0))


_old_urlopen = wizard.urllib.request.urlopen
_old_admin = os.environ.get("MODELRIG_ADMIN_KEY")
os.environ["MODELRIG_ADMIN_KEY"] = "stage-a-contract-secret"
wizard.urllib.request.urlopen = _fake_urlopen
try:
    _minted = wizard._mint_device_token()
finally:
    wizard.urllib.request.urlopen = _old_urlopen
    if _old_admin is None:
        os.environ.pop("MODELRIG_ADMIN_KEY", None)
    else:
        os.environ["MODELRIG_ADMIN_KEY"] = _old_admin

check(_minted == "a" * 64, "admin-key pairing still returns a validated device token")
check(
    bool(_seen_headers)
    and _seen_headers[0].get("x-admin-key") == "stage-a-contract-secret",
    "pair/start carries MODELRIG_ADMIN_KEY as X-Admin-Key when configured",
)

_loader_text = (ROOT / "scripts" / "stage_a_one_click.py").read_text(encoding="utf-8")
check(
    "MODELRIG_ADMIN_KEY" in _loader_text and "X-Admin-Key" in _loader_text,
    "loader keeps the authenticated pairing patch review-visible",
)
_rigdag = (ROOT / "RIGDAG_SIMPEL.md").read_text(encoding="utf-8")
check(
    "et andet PowerShell-vindue kan ikke ændre en allerede kørende wizard" in _rigdag,
    "manual fallback tells the operator to paste into the running wizard",
)

print(f"2.0.13 Stage A additions: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
