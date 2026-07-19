from pathlib import Path

path = Path("worker/app/research_peer_binding.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "def _validate_egress(plan: EgressPlan, receipt: EgressReceipt, now: int) -> None:\n",
        "def _validate_egress(\n    plan: EgressPlan,\n    receipt: EgressReceipt,\n    now: int,\n    *,\n    require_fresh: bool = True,\n) -> None:\n",
    ),
    (
        "    if receipt.expires_at <= now:\n        raise PeerBindingDenied(\"egress receipt expired\")\n",
        "    if require_fresh and receipt.expires_at <= now:\n        raise PeerBindingDenied(\"egress receipt expired\")\n",
    ),
    (
        '                    "INSERT INTO peer_bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",\n',
        '                    "INSERT INTO peer_bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",\n',
    ),
    (
        '                        None,\n                        None,\n                        None,\n                        None,\n                        None,\n                        None,\n                    ),\n',
        '                        None,\n                        None,\n                        None,\n                        None,\n                        None,\n                    ),\n',
    ),
    (
        "        _validate_egress(plan, receipt, timestamp)\n        canonical, _, _ = _validate_url(plan, url)\n        if outcome not in {\"connected\", \"failed\", \"blocked\"}:\n",
        "        _validate_egress(plan, receipt, timestamp, require_fresh=False)\n        canonical, _, _ = _validate_url(plan, url)\n        if outcome not in {\"connected\", \"failed\", \"blocked\"}:\n",
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match, found {count}: {old[:100]!r}")
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
