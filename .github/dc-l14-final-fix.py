from pathlib import Path

path = Path("devcontrol/tests/test_publisher_protocol_inventory_h10f.py")
text = path.read_text(encoding="utf-8")
old = '{"store.py", "_local_candidate_materialization_legacy/__init__.py"}'
new = '{"durable_publication.py", "store.py", "_local_candidate_materialization_legacy/__init__.py"}'
if text.count(old) != 1:
    raise SystemExit("durable publication allowlist marker mismatch")
path.write_text(text.replace(old, new), encoding="utf-8")
