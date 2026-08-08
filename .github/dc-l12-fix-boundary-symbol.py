from pathlib import Path

path = Path('.github/workflows/_tests.yml')
text = path.read_text(encoding='utf-8')
old = 'assert callable(finalizer.finalize_publisher_replay_recovery_receipt_v3)'
new = 'assert callable(finalizer.write_publisher_replay_recovery_receipt_v3)'
if text.count(old) != 1:
    raise SystemExit(f'boundary symbol marker count was {text.count(old)}, expected 1')
path.write_text(text.replace(old, new), encoding='utf-8')
