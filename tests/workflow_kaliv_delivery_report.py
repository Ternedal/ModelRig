"""Run Kaliv delivery regression tests in the shared required test / test gate.

The dedicated delivery workflow remains useful for Python-version matrix checks,
but it is path-filtered and is not a substitute for this required gate.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(SCRIPTS), pattern="test_kaliv_delivery_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
