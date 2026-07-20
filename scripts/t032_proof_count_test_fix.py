#!/usr/bin/env python3
from pathlib import Path

path = Path("tests/workflow_physical_validation_final_gate.py")
text = path.read_text(encoding="utf-8")
old = (
    '    assert "seven-proof physical campaign" in (module.__doc__ or "")\n'
    '    assert "eighth-proof final receipt" in (module.__doc__ or "")\n'
)
new = (
    '    doc = " ".join((module.__doc__ or "").split())\n'
    '    assert "seven-proof physical campaign" in doc\n'
    '    assert "eighth-proof final receipt" in doc\n'
)
if text.count(old) != 1:
    raise SystemExit("expected generated final-gate docstring assertions exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
