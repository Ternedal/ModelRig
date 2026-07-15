"""Experimental Agent 3.0 execution substrate.

Not imported or mounted by the production worker entrypoint. Use
worker/run_worker_agent3.py with KALIV_AGENT3_ENABLED=1.
"""

from .core import *  # noqa: F401,F403
