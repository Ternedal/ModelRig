#!/usr/bin/env python3
from pathlib import Path

path = Path("scripts/activation_readiness.py")
text = path.read_text(encoding="utf-8")
old = '        f"**Version på main:** `{v}`  ",\n'
new = '        f"**Version på main:** `{v}`",\n'
if text.count(old) != 1:
    raise SystemExit("activation readiness version line did not match exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
