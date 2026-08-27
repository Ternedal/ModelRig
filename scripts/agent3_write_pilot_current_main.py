#!/usr/bin/env python3
"""Current-main binding for the dormant T-022 physical final gate.

The historical positive, negative, collector and final-gate modules remain
byte-tested artifacts. This entrypoint changes only their candidate identity
before delegating to the established safe operator. It creates no evidence,
sends no HTTP request and cannot approve a write by itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent3_write_pilot_final_gate_operator as operator  # noqa: E402

BRANCH = "agent/t022-final-gate-current-main"
VERSION = "2.0.13"


def configure_candidate() -> None:
    """Bind the complete imported pipeline to this exact review candidate."""
    operator.core.BRANCH = BRANCH
    operator.core.VERSION = VERSION
    operator.core.configure_final_candidate()


def main(argv: list[str] | None = None) -> int:
    configure_candidate()
    return operator.main(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: ingen gammel grøn T-022-gate er efterladt.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1600]}",
            file=sys.stderr,
        )
        print("  Fysisk evidens kan ikke fremstilles af bindingsfladen.", file=sys.stderr)
        raise SystemExit(1)
